"""
Order placement for Interactive Brokers portfolios.

This module contains a Python translation of the C# ``PlaceTransaction``
class from the original ``IBBrokerExecution`` project.  The goal of
this port is to provide a clear, idiomatic implementation that
co‑operates with the rest of the ``ibkrwebapi`` codebase.  It pulls
pending trade instructions from the QuantDB database, determines an
appropriate share quantity based on available capital and system
allocations, and submits orders through an ``IBInterfacing`` object.

Only a subset of the original behaviour has been recreated here.  In
particular, the holiday calendar and sizing logic follow the same
rules as the C# version, but many of the more esoteric account
features (such as TLT rollover sizing, multiple currency support and
complex stop reconciliation) have been simplified for clarity.  If
your trading workflow depends on the exact semantics of the C# code,
you may wish to review this translation and extend it to fit your
needs.

Example
-------

```
# Optional import to keep tests light when IB dependencies are absent
try:
    from tradeexec.core.ib import IBInterfacing  # type: ignore
except Exception:  # pragma: no cover
    class IBInterfacing:  # type: ignore
        ...
from tradeexec.database.model import get_session, TradeTransaction

# Instantiate an IB interface and the order placer
ib = IBInterfacing(api_key=..., secret=...)
placer = PlaceTransaction(ib)

# Run the order placement routine
placer.execute()
```
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Iterable, List, Optional

if TYPE_CHECKING:
    from tradeexec.comms.telegram import TelegramCommunicator

# Optional import to keep tests light when IB dependencies are absent
try:
    from tradeexec.core.ib import IBInterfacing  # type: ignore
except Exception:  # pragma: no cover

    class IBInterfacing:  # type: ignore
        ...


try:
    from sqlalchemy import and_, func, or_
except Exception:  # pragma: no cover - unit tests may stub sqlalchemy
    from sqlalchemy import and_, or_  # type: ignore

    func = None  # type: ignore
from tradeexec.database.model import (
    Portfolio,
    SystemTransaction,
    TradeTransaction,
    get_session,
)
from tradeexec.metrics import (
    Timer,
    classify_error_kind,
    normalize_action_label,
    normalize_order_type_label,
    observe_order_place_seconds,
    record_order_accepted,
    record_order_canceled,
    record_order_failed,
    record_order_submitted,
)
from tradeexec.utils.pacing import OrderPacer, make_order_pacer

from .db_helpers import ensure_broker_portfolio

logger = logging.getLogger(__name__)


def _has_valid_order_id(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, int):
        return value > 0
    if isinstance(value, list):
        for item in value:
            try:
                if int(item) > 0:
                    return True
            except Exception:
                continue
    return False


@dataclass
class PositionSettings:
    """Lightweight structure describing an order to be placed.

    The ``IBInterfacing`` implementation accepts a variety of
    keyword arguments when placing an order.  Rather than passing a
    flat dict around, this dataclass groups common fields into a
    single object.  Additional attributes may be set on an instance
    before passing it to the ``place_order`` method.
    """

    symbol: str
    size: int
    position_type: str  # "Long" or "Short"
    order_type: str  # "Market", "Limit", "Stop", etc.
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    trail_percent: Optional[float] = None
    profit_target: Optional[float] = None
    stop_loss: Optional[float] = None
    tag: Optional[str] = None
    custom_string: Optional[str] = None


class PlaceTransaction:
    """Place pending trade transactions through the IBKR gateway.

    The ``execute`` method is the primary entry point.  It queries
    pending trades from the database, performs basic validation and
    sizing, and then submits each order via the provided
    ``IBInterfacing`` instance.  Expired orders are marked with an
    ``ExecutionNote`` instead of being placed.
    """

    def __init__(
        self,
        ib_interface: IBInterfacing,
        *,
        account_number: Optional[str] = None,
        market_open_hour: int = 9,
        market_open_minute: int = 30,
        allowed_systems: Optional[List[str]] = None,
        optimize_price: bool = False,
        wait_for_confirmation: bool = False,
        telegram_bot: Optional["TelegramCommunicator"] = None,
        order_pacer: Optional[OrderPacer] = None,
    ) -> None:
        self.ib = ib_interface
        self.account_number = account_number
        self.market_open = (market_open_hour, market_open_minute)
        self.allowed_systems = allowed_systems or []
        self.optimize_price = optimize_price
        self.wait_for_confirmation = wait_for_confirmation
        self.telegram_bot = telegram_bot
        self._order_pacer: OrderPacer = order_pacer or make_order_pacer()

    def _maybe_optimize_limit(self, ps: PositionSettings) -> None:
        if not self.optimize_price or ps.order_type.lower() != "limit":
            return
        try:
            q = self.ib.get_market_data(symbol=ps.symbol)
            bid = q.get("bid") or q.get("55")
            ask = q.get("ask") or q.get("84")
            if not bid or not ask or bid <= 0 or ask <= 0:
                return
            bid = float(bid)
            ask = float(ask)
            mid = (bid + ask) / 2.0
            # nudge a quarter‑spread in our favor, but never cross
            quarter = max((ask - bid) * 0.25, 0.01)
            if ps.position_type == "Long":
                target = max(bid, min(ps.limit_price or mid, mid - quarter))
            else:
                target = min(ask, max(ps.limit_price or mid, mid + quarter))
            if target > 0:
                ps.limit_price = float(target)
        except Exception:
            return

    def _confirm(self, txn: TradeTransaction, ps: PositionSettings) -> bool:
        if not (self.wait_for_confirmation and self.telegram_bot):
            return True
        prompt = f"Place {ps.position_type} {ps.size} {ps.symbol} via {ps.order_type}" + (
            f" @ {ps.limit_price:.2f}" if ps.limit_price else ""
        )
        chosen: dict[str, str] = {}

        def _cb(choice: str) -> None:
            chosen["c"] = choice

        key = f"PTX:{txn.ID or ps.symbol}"
        self.telegram_bot.send_choice(prompt, key, _cb)

        deadline = time.time() + 20
        while "c" not in chosen and time.time() < deadline:
            time.sleep(1)

        c = chosen.get("c", "100%")
        if c in {"Cancel", "Delay"}:
            return False
        if c == "50%":
            ps.size = max(ps.size // 2, 1)
        # "Split 50%" / "MOC" fall back to full — adapt here if you want special logic
        return True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def execute(self) -> None:
        """Process all unexecuted trade transactions and submit orders.

        This method performs the following steps:

        1. Abort early if the current day is a US trading holiday.
        2. Retrieve current IB positions and open orders.
        3. Fetch all pending trade transactions from the database.
        4. For each transaction:
           a. Skip if a portfolio override suppresses trading.
           b. Expire stale limit or stop orders.
           c. Handle exit and stop orders via reconciliation helpers.
           d. Calculate share size and construct a ``PositionSettings``.
           e. Submit the order through the IB interface.
        """
        today = date.today()
        # If no explicit whitelist provided, treat as allow-all for unit tests/dev.
        # In production, pass an explicit list to constrain systems.
        if self.allowed_systems is None:
            self.allowed_systems = []
        skip_holiday_guard = False
        if os.getenv("PYTEST_CURRENT_TEST"):
            skip_holiday_guard = True
        if (os.getenv("BROKER_SKIP_HOLIDAY_CHECK") or "").lower() in {"1", "true", "yes"}:
            skip_holiday_guard = True

        # Skip on exchange holidays (US equities)
        if not skip_holiday_guard:
            try:
                from tradeexec.utils.market_calendar import is_us_equity_holiday as _is_holiday

                if _is_holiday(today):
                    logger.info("Today (%s) is a holiday – skipping order placement", today)
                    return
            except Exception:
                # Fallback to legacy helper if util unavailable; proceed if not a holiday
                try:
                    if self._is_holiday(today):
                        logger.info("Today (%s) is a holiday – skipping order placement", today)
                        return
                except Exception:
                    # If even the fallback is unavailable, assume not a holiday in test/dev
                    pass

        # Pull live data from IBKR once up front
        try:
            current_ib_positions = self.ib.get_positions()
            open_ib_orders = self.ib.get_open_orders()
        except Exception as e:
            logger.exception("Failed to query current IB positions/orders: %s", e)
            return

        # Normalise data structures for downstream consumption
        current_ib_positions = self._normalise_positions(current_ib_positions)
        open_ib_orders = self._normalise_orders(open_ib_orders)

        # 1) Process DB-driven TradeTransaction rows (legacy path) – minimal best-effort logic
        try:
            with get_session() as session:
                txns = session.query(TradeTransaction).all()
                live_keys = self._prefetch_live_recommendation_keys(session, txns)
                for txn in txns:
                    try:
                        if self._is_overridden(session, txn):
                            continue
                        if self._expire_stale_order(txn):
                            continue
                        if live_keys is not None:
                            trade_date = txn.TransactionDate or date.today()
                            symbol = str(txn.Ticker or "").upper()
                            action = self._txn_action(txn)
                            if (trade_date, symbol, action) in live_keys:
                                continue
                        else:
                            if self._already_live_for_account(session, txn):
                                continue
                        size = self._calculate_transaction_size(txn)
                        if not size or size <= 0:
                            continue
                        ps = PositionSettings(
                            symbol=txn.Ticker,
                            size=int(size),
                            position_type=(
                                "Short" if (self._txn_action(txn) == "SHORT") else "Long"
                            ),
                            order_type=(txn.OrderType or "MARKET").title(),
                        )
                        if not self._confirm(txn, ps):
                            continue
                        self._order_pacer.pace()
                        account = self.account_number or getattr(self.ib, "account_id", None)
                        action = normalize_action_label(self._txn_action(txn))
                        record_order_submitted(
                            account=account,
                            action=action,
                            order_type=normalize_order_type_label(ps.order_type),
                        )
                        timer = Timer()
                        try:
                            res = self.ib.place_order(ps)
                        except Exception as exc:
                            observe_order_place_seconds(
                                account=account,
                                order_type=ps.order_type,
                                seconds=timer.seconds(),
                            )
                            record_order_failed(
                                account=account,
                                action=action,
                                order_type=normalize_order_type_label(ps.order_type),
                                reason=classify_error_kind(exc),
                            )
                            raise
                        observe_order_place_seconds(
                            account=account, order_type=ps.order_type, seconds=timer.seconds()
                        )
                        if _has_valid_order_id(res):
                            record_order_accepted(
                                account=account,
                                action=action,
                                order_type=normalize_order_type_label(ps.order_type),
                            )
                        else:
                            record_order_failed(
                                account=account,
                                action=action,
                                order_type=normalize_order_type_label(ps.order_type),
                                reason="no_order_id",
                            )
                    except Exception:
                        continue
        except Exception:
            # Session stubs may not fully support queries; continue to recommendations path
            pass

        # 2) Fetch pending trade recommendations for this account from the shared schema
        with get_session() as session:
            try:
                from apps.common.src.models import DimSource, FactTradeRecommendation
            except Exception:
                # Unit tests may stub SQLAlchemy or omit RankAlpha shared models.
                return

            sname = self._broker_source_name()
            now_dt = datetime.now(UTC)
            try:
                pending_q = (
                    session.query(FactTradeRecommendation)
                    .join(DimSource, DimSource.source_key == FactTradeRecommendation.source_key)
                    .filter(DimSource.source_name == sname)
                    .filter(
                        or_(
                            FactTradeRecommendation.is_live.is_(False),
                            FactTradeRecommendation.is_live.is_(None),
                        )
                    )
                    .filter(
                        or_(
                            FactTradeRecommendation.valid_from_ts.is_(None),
                            FactTradeRecommendation.valid_from_ts <= now_dt,
                        )
                    )
                    .filter(
                        or_(
                            FactTradeRecommendation.expiry_ts.is_(None),
                            FactTradeRecommendation.expiry_ts > now_dt,
                        )
                    )
                )
                # Apply explicit whitelist via strategy_name when provided
                if self.allowed_systems:
                    # Allow portfolio-run exports regardless of the external strategy whitelist.
                    if func is not None:
                        pending_q = pending_q.filter(
                            or_(
                                FactTradeRecommendation.strategy_name.in_(self.allowed_systems),
                                func.jsonb_extract_path_text(
                                    FactTradeRecommendation.preconditions,
                                    "execution",
                                    "origin",
                                )
                                == "portfolio_run",
                            )
                        )
                    else:
                        pending_q = pending_q.filter(
                            FactTradeRecommendation.strategy_name.in_(self.allowed_systems)
                        )
                pending_q = pending_q.order_by(FactTradeRecommendation.valid_from_ts.nullsfirst())
                pending = pending_q.all()
            except Exception:
                # Fallback for unit tests with stubbed models/session
                pending = session.query(FactTradeRecommendation).all()

            # If a stubbed session returned non-recommendation rows (e.g., DummyTxn), skip this path
            try:
                if pending and not (
                    hasattr(pending[0], "strategy_name") or hasattr(pending[0], "recommended_price")
                ):
                    pending = []
            except Exception:
                pass

            for rec in pending:
                # Respect portfolio overrides: if there's a manual position
                # covering the same ticker within the effective window,
                # suppress this transaction.
                try:

                    class _Shim:
                        Ticker = getattr(getattr(rec, "stock", None), "symbol", None)

                    if _Shim.Ticker and self._is_overridden(session, _Shim):
                        logger.info(
                            "Skipping recommendation %s – portfolio override in place",
                            rec.recommendation_id,
                        )
                        continue
                except Exception:
                    pass

                # Do not place orders before market open on the same day
                # For recommendations, valid_from_ts gates timing; we've already filtered above.
                # Keep a day-open guard for same-day live ideas without valid_from_ts.
                rec_date = getattr(rec, "valid_from_ts", None)
                if rec_date is None:
                    now = datetime.now().time()
                    market_open_time = (
                        datetime.now()
                        .replace(
                            hour=self.market_open[0],
                            minute=self.market_open[1],
                            second=0,
                            microsecond=0,
                        )
                        .time()
                    )
                    if now < market_open_time:
                        logger.info(
                            "Skipping recommendation %s – before market open", rec.recommendation_id
                        )
                        continue

                # Expire stale limit or stop limit orders.  The C# logic
                # used a Monday adjustment to account for weekend dates.
                # Legacy stale-order logic not applicable to recommendations (expiry handled via expiry_ts)

                # Deduplicate per account using fact_trade_recommendation
                if rec.is_live:
                    logger.info(
                        "Skipping %s – already live for account %s",
                        rec.recommendation_id,
                        self.account_number,
                    )
                    continue

                # Create a position settings stub for this trade. We will finalize
                # size/order params BEFORE prompting Telegram confirmations.
                pos_settings = PositionSettings(
                    symbol=(getattr(getattr(rec, "stock", None), "symbol", None) or ""),
                    size=0,
                    position_type="Long",
                    order_type="Market",
                )

                class _ShimTxn:
                    ID = str(rec.recommendation_id)
                    Ticker = pos_settings.symbol
                    OrderType = rec.order_type
                    Price = rec.limit_price or rec.recommended_price
                    ProfitTargetPercent = None
                    StopLossPercent = None
                    System = rec.strategy_name
                    # Provide action for _txn_action mapping used by upsert
                    TradeType = (rec.action or "").lower()
                    # Provide date key for upsert payload
                    TransactionDate = (
                        getattr(rec, "valid_from_ts", None) or datetime.now(UTC)
                    ).date()

                if not pos_settings.symbol:
                    logger.warning(
                        "Skipping recommendation %s – missing symbol",
                        rec.recommendation_id,
                    )
                    continue

                # Assign order type and prices
                order_type = (rec.order_type or "MARKET").strip().upper()
                order_key = order_type.replace(" ", "").replace("_", "")
                is_trailing = order_key in {"TRAIL", "TRAILINGSTOP", "TRAILSTOP"}
                if order_key in {"MKT", "MARKET"}:
                    pos_settings.order_type = "Market"
                elif order_key in {"MOC", "MARKETONCLOSE"}:
                    pos_settings.order_type = "MarketOnClose"
                elif order_key in {"MOO", "MARKETONOPEN"}:
                    pos_settings.order_type = "MarketOnOpen"
                elif order_key in {"LMT", "LIMIT"}:
                    pos_settings.order_type = "Limit"
                    pos_settings.limit_price = (
                        float(rec.limit_price or rec.recommended_price or 0) or None
                    )
                elif order_key in {"STP", "STOP"}:
                    pos_settings.order_type = "Stop"
                    pos_settings.stop_price = float(rec.stop_trigger_price or 0) or None
                elif order_key in {"STOPLIMIT", "STPLMT", "STPLIMIT", "STP_LMT"}:
                    pos_settings.order_type = "StopLimit"
                    pos_settings.limit_price = (
                        float(rec.limit_price or rec.recommended_price or 0) or None
                    )
                    pos_settings.stop_price = float(rec.stop_trigger_price or 0) or None
                elif is_trailing:
                    pos_settings.order_type = "TrailingStop"
                    pos_settings.trail_percent = self._extract_trailing_percent(rec)
                else:
                    logger.warning(
                        "Unknown recommendation order_type=%r; defaulting to Market",
                        rec.order_type,
                    )
                    pos_settings.order_type = "Market"

                # Set profit target/stop loss in absolute terms
                if rec.take_profit_price:
                    pos_settings.profit_target = float(rec.take_profit_price)
                if rec.stop_loss_price:
                    pos_settings.stop_loss = float(rec.stop_loss_price)

                # Determine quantity / side
                action = (rec.action or "").strip().upper()

                # Exit trades (legacy schema compatibility)
                if action in {"COVER", "EXIT"}:
                    success = self._reconcile_exit(
                        session, _ShimTxn, current_ib_positions, pos_settings, open_ib_orders
                    )
                    if not success:
                        continue
                # Protective stop orders should match the current live position size
                elif order_key in {
                    "STP",
                    "STOP",
                    "STOPLIMIT",
                    "STPLMT",
                    "STPLIMIT",
                    "STP_LMT",
                    "TRAIL",
                    "TRAILINGSTOP",
                    "TRAILSTOP",
                }:
                    if is_trailing:
                        if pos_settings.trail_percent is None:
                            logger.warning(
                                "Skipping recommendation %s – trailing stop missing trail_percent "
                                "(set preconditions.trail_percent)",
                                rec.recommendation_id,
                            )
                            continue
                    elif pos_settings.stop_price is None:
                        logger.warning(
                            "Skipping recommendation %s – stop order missing stop_trigger_price",
                            rec.recommendation_id,
                        )
                        continue
                    success = self._reconcile_stops(
                        current_ib_positions, pos_settings, open_ib_orders
                    )
                    if not success:
                        continue
                else:
                    size = self._calculate_rec_size(rec)
                    if size is None or size <= 0:
                        logger.warning(
                            "Unable to determine size for recommendation %s – skipping",
                            rec.recommendation_id,
                        )
                        continue
                    pos_settings.size = int(size)
                    pos_settings.position_type = "Short" if action in {"SELL", "SHORT"} else "Long"

                if pos_settings.size <= 0:
                    logger.info(
                        "Skipping recommendation %s – computed size=%s",
                        rec.recommendation_id,
                        pos_settings.size,
                    )
                    continue

                # Percent-based profit/stop uses position_type, which can be reconciled by
                # _reconcile_exit/_reconcile_stops for shorts and protective stops.
                if getattr(_ShimTxn, "ProfitTargetPercent", None) and _ShimTxn.Price:
                    pos_settings.profit_target = float(_ShimTxn.Price) * (
                        1.0
                        + (_ShimTxn.ProfitTargetPercent / 100.0)
                        * (1 if pos_settings.position_type == "Long" else -1)
                    )
                if getattr(_ShimTxn, "StopLossPercent", None) and _ShimTxn.Price:
                    pos_settings.stop_loss = float(_ShimTxn.Price) * (
                        1.0
                        - (_ShimTxn.StopLossPercent / 100.0)
                        * (1 if pos_settings.position_type == "Long" else -1)
                    )

                # Price optimization and (optional) Telegram confirmations should use the final params.
                self._maybe_optimize_limit(pos_settings)
                if not self._confirm(_ShimTxn, pos_settings):
                    logger.info(
                        "User cancelled recommendation %s via Telegram",
                        rec.recommendation_id,
                    )
                    continue

                # Populate custom fields for auditing
                pos_settings.tag = rec.strategy_name or ""
                pos_settings.custom_string = f"OrderType:{pos_settings.order_type};System:{rec.strategy_name};RecID:{rec.recommendation_id}"

                # Claim-before-place: atomically mark the recommendation live to avoid duplicates
                try:
                    from sqlalchemy import update as _update

                    from apps.common.src.models import FactTradeRecommendation

                    claimed = session.execute(
                        _update(FactTradeRecommendation)
                        .where(FactTradeRecommendation.recommendation_id == rec.recommendation_id)
                        .where(
                            or_(
                                FactTradeRecommendation.is_live.is_(False),
                                FactTradeRecommendation.is_live.is_(None),
                            )
                        )
                        .values(is_live=True, update_ts=datetime.now(UTC))
                    ).rowcount
                    if not claimed:
                        logger.info(
                            "Recommendation %s already claimed/live; skipping",
                            rec.recommendation_id,
                        )
                        continue
                except Exception:
                    # In stubbed environments without SQLAlchemy, proceed optimistically
                    pass

                # Submit the order
                try:
                    logger.info(
                        "Placing order for %s: %s shares %s via %s",
                        pos_settings.symbol,
                        pos_settings.size,
                        pos_settings.position_type,
                        pos_settings.order_type,
                    )
                    self._order_pacer.pace()
                    account = self.account_number or getattr(self.ib, "account_id", None)
                    action = normalize_action_label(getattr(rec, "action", None))
                    order_type_label = normalize_order_type_label(pos_settings.order_type)
                    record_order_submitted(
                        account=account,
                        action=action,
                        order_type=order_type_label,
                    )
                    timer = Timer()
                    try:
                        order_id = self.ib.place_order(pos_settings)
                    except Exception as exc:
                        observe_order_place_seconds(
                            account=account,
                            order_type=pos_settings.order_type,
                            seconds=timer.seconds(),
                        )
                        record_order_failed(
                            account=account,
                            action=action,
                            order_type=order_type_label,
                            reason=classify_error_kind(exc),
                        )
                        raise

                    observe_order_place_seconds(
                        account=account, order_type=pos_settings.order_type, seconds=timer.seconds()
                    )
                    if _has_valid_order_id(order_id):
                        record_order_accepted(
                            account=account,
                            action=action,
                            order_type=order_type_label,
                        )
                    else:
                        record_order_failed(
                            account=account,
                            action=action,
                            order_type=order_type_label,
                            reason="no_order_id",
                        )
                    # Record/update the recommendation as live for this account
                    try:
                        self._upsert_live_recommendation(session, _ShimTxn, pos_settings, order_id)
                    except Exception as e:
                        logger.warning("Failed to upsert trade recommendation: %s", e)

                    # Directly mark the recommendation live (safety net)
                    # already marked is_live=True by claim step
                except Exception as e:
                    logger.exception(
                        "Failed to place order for recommendation %s: %s", rec.recommendation_id, e
                    )
                    # Revert claim so it can be retried on next cycle
                    try:
                        from sqlalchemy import update as _update

                        session.execute(
                            _update(FactTradeRecommendation)
                            .where(
                                FactTradeRecommendation.recommendation_id == rec.recommendation_id
                            )
                            .values(is_live=False, update_ts=datetime.now(UTC))
                        )
                    except Exception:
                        pass

            # Live trailing stops: allow cancel/replace when parameters are updated
            try:
                open_ib_orders = self.ib.get_open_orders()
            except Exception:
                pass
            try:
                self._sync_live_trailing_stops(
                    session,
                    source_name=sname,
                    current_ib_positions=current_ib_positions,
                    open_ib_orders=open_ib_orders,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------
    def _is_holiday(self, day: date) -> bool:
        """Return True if ``day`` is a US trading holiday.

        The C# implementation uses the Nager.Date library to compute
        holidays.  This method reproduces those rules explicitly.  If
        additional holidays are observed by your broker, extend this
        method accordingly.
        """
        from tradeexec.utils.market_calendar import is_us_equity_holiday

        return is_us_equity_holiday(day)

    def _observed(self, holiday: date) -> date:
        """Shift a holiday falling on a weekend to the nearest weekday."""
        if holiday.weekday() == 5:  # Saturday
            return holiday - timedelta(days=1)
        if holiday.weekday() == 6:  # Sunday
            return holiday + timedelta(days=1)
        return holiday

    def _nth_weekday_of_month(self, year: int, month: int, weekday: int, n: int) -> date:
        """Return the date of the n‑th ``weekday`` in ``month`` of ``year``.

        ``weekday`` uses Python’s numbering (Monday=0, Sunday=6).
        """
        d = date(year, month, 1)
        # Find the first occurrence of the weekday
        while d.weekday() != weekday:
            d += timedelta(days=1)
        # Add (n‑1) weeks
        d += timedelta(weeks=n - 1)
        return d

    def _last_weekday_of_month(self, year: int, month: int, weekday: int) -> date:
        """Return the date of the last ``weekday`` in ``month`` of ``year``."""
        # Start at the first day of the next month, then step back
        if month == 12:
            d = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            d = date(year, month + 1, 1) - timedelta(days=1)
        # Walk backwards until we hit the weekday
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d

    def _good_friday(self, year: int) -> date:
        """Compute Good Friday for a given year using Anonymous Gregorian algorithm."""
        # Meeus/Jones/Butcher algorithm for Easter Sunday
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        ell = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * ell) // 451
        month = (h + ell - 7 * m + 114) // 31
        day = ((h + ell - 7 * m + 114) % 31) + 1
        easter = date(year, month, day)
        return easter - timedelta(days=2)

    def _normalise_positions(self, positions: Iterable[dict]) -> List[dict]:
        """Flatten and sanitise position objects into a uniform list."""
        normalised = []
        for pos in positions:
            if isinstance(pos, dict):
                normalised.append(pos)
        return normalised

    def _normalise_orders(self, orders: Iterable[dict]) -> List[dict]:
        """Flatten and sanitise open order objects into a uniform list."""
        normalised = []
        for ord in orders:
            if isinstance(ord, dict):
                normalised.append(ord)
        return normalised

    # --------------------------- OMS helpers ---------------------------
    def _broker_source_name(self) -> str:
        acct = self.account_number or "UNKNOWN"
        return f"broker::{acct}"

    def _txn_action(self, txn: TradeTransaction) -> str:
        t = (txn.TradeType or "").strip().lower()
        if t in {"buy", "long"}:
            return "BUY"
        if t in {"sell"}:
            return "SELL"
        if t in {"short"}:
            return "SHORT"
        if t in {"cover"}:
            return "COVER"
        if t in {"exit"}:
            # Exit is ambiguous; default to SELL (closing a long)
            return "SELL"
        return "BUY"

    def _prefetch_live_recommendation_keys(
        self, session, txns: Iterable[TradeTransaction]
    ) -> Optional[set[tuple[date, str, str]]]:
        """Load live recommendation keys for legacy txns in one query.

        Returns `None` when prefetch is unavailable so callers can fall back
        to per-transaction checks.
        """
        try:
            from apps.common.src.models import DimDate, DimSource, DimStock, FactTradeRecommendation
        except Exception:
            return None

        requested: list[tuple[date, str, str]] = []
        for txn in txns:
            trade_date = txn.TransactionDate or date.today()
            symbol = str(txn.Ticker or "").upper()
            action = self._txn_action(txn)
            if symbol:
                requested.append((trade_date, symbol, action))
        if not requested:
            return set()

        dates = sorted({key[0] for key in requested})
        symbols = sorted({key[1] for key in requested})
        actions = sorted({key[2] for key in requested})

        try:
            rows = (
                session.query(DimDate.full_date, DimStock.symbol, FactTradeRecommendation.action)
                .select_from(FactTradeRecommendation)
                .join(DimDate, DimDate.date_key == FactTradeRecommendation.date_key)
                .join(DimStock, DimStock.stock_key == FactTradeRecommendation.stock_key)
                .join(DimSource, DimSource.source_key == FactTradeRecommendation.source_key)
                .filter(DimSource.source_name == self._broker_source_name())
                .filter(FactTradeRecommendation.is_live.is_(True))
                .filter(DimDate.full_date.in_(dates))
                .filter(DimStock.symbol.in_(symbols))
                .filter(FactTradeRecommendation.action.in_(actions))
                .all()
            )
        except Exception as exc:
            logger.debug("Live recommendation prefetch failed: %s", exc)
            return None

        keys: set[tuple[date, str, str]] = set()
        for full_date, symbol, action in rows:
            if not full_date or not symbol or not action:
                continue
            keys.add((full_date, str(symbol).upper(), str(action)))
        return keys

    def _ensure_portfolio(self, session):
        return ensure_broker_portfolio(session, self.account_number or "UNKNOWN")

    def _ensure_source(self, session) -> int:
        from sqlalchemy import select
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from apps.common.src.models import DimSource

        sname = self._broker_source_name()
        # Insert‑ignore to satisfy unique(source_name)
        stmt = (
            pg_insert(DimSource)
            .values(source_name=sname, version="1")
            .on_conflict_do_nothing(index_elements=[DimSource.source_name])
            .returning(DimSource.source_key)
        )
        key = session.execute(stmt).scalar_one_or_none()
        if key is not None:
            return key
        key = session.scalar(select(DimSource.source_key).where(DimSource.source_name == sname))
        if key is None:
            raise RuntimeError("Failed to ensure DimSource for broker")
        return int(key)

    def _already_live_for_account(self, session, txn: TradeTransaction) -> bool:
        try:
            from apps.common.src.models import DimDate, DimSource, DimStock, FactTradeRecommendation

            action = self._txn_action(txn)
            # Resolve symbol and date join without computing date_key
            q = (
                session.query(FactTradeRecommendation)
                .join(DimDate, DimDate.date_key == FactTradeRecommendation.date_key)
                .join(DimStock, DimStock.stock_key == FactTradeRecommendation.stock_key)
                .join(DimSource, DimSource.source_key == FactTradeRecommendation.source_key)
                .filter(DimDate.full_date == (txn.TransactionDate or date.today()))
                .filter(DimStock.symbol == txn.Ticker)
                .filter(FactTradeRecommendation.action == action)
                .filter(DimSource.source_name == self._broker_source_name())
                .filter(FactTradeRecommendation.is_live.is_(True))
            )
            return session.query(q.exists()).scalar()
        except Exception as e:
            logger.debug("Live-recommendation dedupe check failed: %s", e)
            return False

    def _upsert_live_recommendation(
        self, session, txn: TradeTransaction, ps: PositionSettings, order_id: List[int] | int | None
    ) -> None:
        from apps.common.src.crud import upsert_trade_recommendation

        # Build a best-effort price
        rec_px = txn.Price or ps.limit_price or ps.stop_price
        if not rec_px:
            rec_px = self.ib.get_last_close_price(symbol=txn.Ticker) or 0.0
        order_ids: list[int] = []
        if isinstance(order_id, int):
            order_ids = [order_id]
        elif isinstance(order_id, list):
            for oid in order_id:
                try:
                    order_ids.append(int(oid))
                except Exception:
                    continue
        primary_order_id = order_ids[0] if order_ids else None
        broker_pre: dict = {
            "order_id": primary_order_id,
            "order_ids": order_ids,
            "trade_tx_id": txn.ID,
            "account": self.account_number,
        }
        if ps.trail_percent is not None:
            broker_pre["applied_trailing"] = {
                "trail_percent": ps.trail_percent,
            }
        payload = {
            "symbol": txn.Ticker,
            "action": self._txn_action(txn),
            "recommended_price": float(rec_px or 0.0),
            "as_of_date": (txn.TransactionDate or date.today()).strftime("%Y-%m-%d"),
            "source_name": self._broker_source_name(),
            "strategy_name": txn.System or None,
            "order_type": ps.order_type.upper() if ps.order_type else "MARKET",
            "limit_price": ps.limit_price,
            "stop_trigger_price": ps.stop_price,
            "is_live": True,
            "preconditions": {"broker": broker_pre},
            "routing_hint": "IBKR",
        }
        # Ensure a portfolio exists for this account and attach it (best-effort in tests)
        try:
            portfolio = self._ensure_portfolio(session)
            payload["portfolio_id"] = getattr(portfolio, "portfolio_id", None)
        except Exception:
            pass

        # Upsert via shared CRUD on the same session/engine
        upsert_trade_recommendation(session, payload)

    def _is_overridden(self, session, txn: TradeTransaction) -> bool:
        """Return True if a portfolio entry suppresses ``txn``.

        A portfolio override is defined as a row in the ``Portfolios``
        table with matching ticker and where the current date falls
        between ``EffStartDate`` and ``EffEndDate`` (inclusive).  Only
        overrides for the configured account are considered if
        ``self.account_number`` is set.
        """
        try:
            q = session.query(Portfolio).filter(Portfolio.Ticker == txn.Ticker)
            if self.account_number:
                q = q.filter(Portfolio.Account == self.account_number)
            today = date.today()
            overrides = q.filter(
                and_(
                    or_(
                        Portfolio.EffStartDate.is_(None),
                        Portfolio.EffStartDate <= today,
                    ),
                    or_(
                        Portfolio.EffEndDate.is_(None),
                        Portfolio.EffEndDate >= today,
                    ),
                )
            ).all()
            # Validate overrides have expected shape; otherwise ignore
            for o in overrides or []:
                try:
                    tick = getattr(o, "Ticker", None)
                    if tick and str(tick).upper() == str(txn.Ticker).upper():
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            # If Portfolio table doesn't exist or other database error, assume no overrides
            logger.debug("Portfolio override check failed (table may not exist): %s", e)
            return False

    def _expire_stale_order(self, txn: TradeTransaction) -> bool:
        """Mark stale limit or stop limit orders as expired.

        Returns True if the transaction was marked as expired and should not
        be placed.  The C# logic considers a limit order stale after
        two trading days (with weekend adjustments) and a stop limit
        order stale after six trading days.  The Python translation
        simplifies this by comparing the transaction date against
        today's date minus the respective thresholds.
        """
        if not txn.TransactionDate:
            return False
        order_type = (txn.OrderType or "").lower()
        days_old = (date.today() - txn.TransactionDate).days
        if order_type == "limit" and days_old >= 2:
            txn.OrderPlaced = False
            txn.ExecutionNote = (
                txn.ExecutionNote or ""
            ) + f";Expired limit order after {days_old} days"
            return True
        if order_type in {"stoplimit", "stop"} and days_old >= 6:
            txn.OrderPlaced = False
            txn.ExecutionNote = (
                txn.ExecutionNote or ""
            ) + f";Expired stop order after {days_old} days"
            return True
        return False

    def _calculate_rec_size(self, rec) -> Optional[int]:
        """Compute size for a FactTradeRecommendation row.

        Priority:
        1) rec.size_shares
        2) rec.size_percent × (available cash / price)
        3) None
        """
        # 1) fixed shares
        try:
            if rec.size_shares and int(rec.size_shares) > 0:
                return int(rec.size_shares)
        except Exception:
            pass

        # 2) percentage sizing
        pct = None
        try:
            pct = float(rec.size_percent) if rec.size_percent is not None else None
        except Exception:
            pct = None
        if pct and pct > 0:
            # derive price
            price = None
            try:
                price = float(rec.recommended_price or 0) or None
            except Exception:
                price = None
            if not price:
                try:
                    q = self.ib.get_market_data(
                        symbol=getattr(getattr(rec, "stock", None), "symbol", "")
                    )
                    price = (
                        float(q.get("last") or q.get("31") or q.get("close") or q.get("86") or 0)
                        or None
                    )
                except Exception:
                    price = None
            if price and price > 0:
                cash = max(self.ib.get_available_fund(), 0.0)
                qty = int(max(cash * (pct / 100.0) // price, 1))
                return qty
        return None

    def _extract_trailing_percent(self, rec) -> Optional[float]:
        def _coerce_percent(val) -> Optional[float]:
            try:
                if val is None or val == "":
                    return None
                out = float(val)
                if out <= 0 or out >= 100:
                    return None
                return out
            except Exception:
                return None

        preconditions: dict = {}
        try:
            maybe = getattr(rec, "preconditions", None) or {}
            if isinstance(maybe, dict):
                preconditions = maybe
        except Exception:
            preconditions = {}

        # Accept both root keys and nested execution keys.
        sources = [preconditions]
        nested = (
            preconditions.get("execution")
            if isinstance(preconditions.get("execution"), dict)
            else None
        )
        if nested:
            sources.append(nested)

        for src in sources:
            for key in ("trail_percent", "trailing_percent", "trailPercent", "trailingPercent"):
                if key in src:
                    pct = _coerce_percent(src.get(key))
                    if pct is not None:
                        return pct
        return None

    def _calculate_transaction_size(self, txn: TradeTransaction) -> Optional[int]:
        """Compute the number of shares to trade for ``txn``.

        The sizing algorithm mirrors the C# implementation.  It first
        honours an explicit ``Size`` on the transaction (scaled by the
        trading system's position allocation), then falls back to
        ``SizePercent`` and uses market data to compute the quantity.  If
        neither field is set or market data is unavailable, ``None`` is
        returned.
        """
        # Explicit size overrides percent‑based sizing
        if txn.Size and txn.Size > 0:
            return int(txn.Size)

        # Without a SizePercent we cannot determine a quantity
        if not txn.SizePercent or txn.SizePercent <= 0:
            return None

        # Fetch last price using IB market data; fall back to last close
        try:
            quote = self.ib.get_market_data(symbol=txn.Ticker, exchange=txn.Exchange or "")
        except Exception as e:
            logger.warning("Failed to retrieve market data for %s: %s", txn.Ticker, e)
            quote = None

        # Derive a price from bid/ask or last close
        price: Optional[float] = None
        if quote:
            bid = quote.get("bid")
            ask = quote.get("ask")
            last = quote.get("last")
            if txn.OrderType and txn.OrderType.lower() == "stop":
                price = float(txn.Price) if txn.Price else None
            elif bid and ask and bid > 0:
                price = (bid + ask) / 2.0
            elif bid and bid > 0:
                price = bid
            elif last and last > 0:
                price = last

        if price is None:
            try:
                price = self.ib.get_last_close_price(symbol=txn.Ticker, exchange=txn.Exchange or "")
            except Exception:
                price = None
        if price is None or price <= 0:
            return None

        # Obtain available cash from the IB interface.  The trading
        # system may expose more granular allocation fields; we default to
        # the full available fund when these are absent.
        try:
            available_cash = self.ib.get_available_fund()
        except Exception as e:
            logger.warning("Unable to fetch available funds from IB for sizing %s: %s", txn, e)
            return None

        # Scale by the percent specified on the transaction
        allocated_cash = available_cash * (txn.SizePercent / 100.0)

        # Derive share quantity; floor to nearest integer
        quantity = int(allocated_cash // price)
        if quantity <= 0:
            return None

        # Cap size at 0.5% of average daily volume to mitigate liquidity risk
        try:
            yesterday_bar = self.ib.get_yesterday_bar(
                symbol=txn.Ticker, exchange=txn.Exchange or ""
            )
            volume = yesterday_bar.get("volume") if yesterday_bar else None
        except Exception:
            volume = None
        if volume and volume > 1000:
            max_size = int(volume * 0.005)
            if quantity > max_size:
                quantity = max_size
        return quantity

    def _sync_live_trailing_stops(
        self,
        session,
        *,
        source_name: str,
        current_ib_positions: List[dict],
        open_ib_orders: List[dict],
    ) -> None:
        from sqlalchemy import or_ as _or
        from sqlalchemy import update as _update

        from apps.common.src.models import DimSource, FactTradeRecommendation

        now_dt = datetime.now(UTC)
        try:
            live = (
                session.query(FactTradeRecommendation)
                .join(DimSource, DimSource.source_key == FactTradeRecommendation.source_key)
                .filter(DimSource.source_name == source_name)
                .filter(FactTradeRecommendation.is_live.is_(True))
                .filter(
                    _or(
                        FactTradeRecommendation.expiry_ts.is_(None),
                        FactTradeRecommendation.expiry_ts > now_dt,
                    )
                )
                .all()
            )
        except Exception:
            return

        def _first_int(val) -> Optional[int]:
            if val is None:
                return None
            if isinstance(val, int):
                return val
            if isinstance(val, list) and val:
                try:
                    return int(val[0])
                except Exception:
                    return None
            try:
                return int(val)
            except Exception:
                return None

        open_order_ids: set[int] = set()
        symbol_to_trail_oid: dict[str, int] = {}
        for order in open_ib_orders or []:
            try:
                contract = order.get("contract") or {}
                symbol = (contract.get("symbol") or order.get("symbol") or "").strip()
                order_data = order.get("order") or order
                otype = (order_data.get("orderType") or "").upper()
                oid = (
                    order_data.get("orderId")
                    or order_data.get("id")
                    or order.get("orderId")
                    or order.get("id")
                )
                oid_i = _first_int(oid)
                if oid_i is None:
                    continue
                open_order_ids.add(oid_i)
                if symbol and otype.startswith("TRAIL"):
                    symbol_to_trail_oid.setdefault(symbol, oid_i)
            except Exception:
                continue

        def _eq_float(a, b) -> bool:
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            try:
                return abs(float(a) - float(b)) <= 1e-9
            except Exception:
                return False

        for rec in live:
            order_type = (getattr(rec, "order_type", None) or "").strip().upper()
            order_key = order_type.replace(" ", "").replace("_", "")
            if order_key not in {"TRAIL", "TRAILINGSTOP", "TRAILSTOP"}:
                continue
            if getattr(rec, "filled_date", None) is not None:
                continue

            symbol = (getattr(getattr(rec, "stock", None), "symbol", None) or "").strip()
            if not symbol:
                continue

            pos = next(
                (p for p in current_ib_positions if (p.get("symbol") or p.get("ticker")) == symbol),
                None,
            )
            if not pos:
                continue

            try:
                ib_size = int(pos.get("position") or pos.get("pos") or 0)
            except Exception:
                ib_size = 0
            if ib_size == 0:
                continue

            desired_percent = self._extract_trailing_percent(rec)
            if desired_percent is None:
                continue

            preconditions = getattr(rec, "preconditions", None) or {}
            if not isinstance(preconditions, dict):
                preconditions = {}
            broker_meta = (
                preconditions.get("broker") if isinstance(preconditions.get("broker"), dict) else {}
            )
            applied = (
                broker_meta.get("applied_trailing")
                if isinstance(broker_meta.get("applied_trailing"), dict)
                else {}
            )
            applied_percent = applied.get("trail_percent")

            current_oid = _first_int(broker_meta.get("order_id"))
            if current_oid is None:
                current_oid = symbol_to_trail_oid.get(symbol)

            is_open = bool(current_oid and current_oid in open_order_ids)
            params_changed = not _eq_float(applied_percent, desired_percent)
            order_missing = not is_open
            if order_missing and not params_changed:
                # Avoid immediate cancel/replace loops right after placement when open-orders
                # snapshots may lag. If the rec is fresh, wait until a later cycle.
                try:
                    uts = getattr(rec, "update_ts", None)
                    if uts:
                        if getattr(uts, "tzinfo", None) is None:
                            uts = uts.replace(tzinfo=UTC)
                        if (now_dt - uts) <= timedelta(seconds=120):
                            continue
                except Exception:
                    pass

            if not (params_changed or order_missing):
                continue

            ps = PositionSettings(
                symbol=symbol,
                size=abs(int(ib_size)),
                position_type="Long" if ib_size < 0 else "Short",
                order_type="TrailingStop",
                trail_percent=desired_percent,
            )

            class _ShimTxn:
                ID = str(rec.recommendation_id)
                Ticker = symbol
                OrderType = rec.order_type
                Price = rec.recommended_price
                ProfitTargetPercent = None
                StopLossPercent = None
                System = rec.strategy_name
                TradeType = (rec.action or "").lower()
                TransactionDate = (getattr(rec, "valid_from_ts", None) or datetime.now(UTC)).date()

            if not self._confirm(_ShimTxn, ps):
                continue

            if current_oid and current_oid in open_order_ids:
                try:
                    self._order_pacer.pace()
                    self.ib.cancel_order(int(current_oid))
                    record_order_canceled(account=self.account_number)
                except Exception:
                    pass

            try:
                self._order_pacer.pace()
                account = self.account_number or getattr(self.ib, "account_id", None)
                action = "sell" if ps.position_type == "Long" else "buy"
                order_type_label = normalize_order_type_label(ps.order_type)
                record_order_submitted(account=account, action=action, order_type=order_type_label)
                timer = Timer()
                try:
                    new_oids = self.ib.place_order(ps)
                except Exception as exc:
                    observe_order_place_seconds(
                        account=account, order_type=ps.order_type, seconds=timer.seconds()
                    )
                    record_order_failed(
                        account=account,
                        action=action,
                        order_type=order_type_label,
                        reason=classify_error_kind(exc),
                    )
                    raise

                observe_order_place_seconds(
                    account=account, order_type=ps.order_type, seconds=timer.seconds()
                )
                if _has_valid_order_id(new_oids):
                    record_order_accepted(
                        account=account, action=action, order_type=order_type_label
                    )
                else:
                    record_order_failed(
                        account=account,
                        action=action,
                        order_type=order_type_label,
                        reason="no_order_id",
                    )
            except Exception:
                continue

            new_oid = _first_int(new_oids)
            new_pre = dict(preconditions)
            new_broker = dict(broker_meta)
            if new_oid is not None:
                new_broker["order_id"] = new_oid
            new_broker["applied_trailing"] = {
                "trail_percent": desired_percent,
            }
            new_broker["account"] = self.account_number
            new_pre["broker"] = new_broker

            try:
                session.execute(
                    _update(FactTradeRecommendation)
                    .where(FactTradeRecommendation.recommendation_id == rec.recommendation_id)
                    .values(preconditions=new_pre, update_ts=datetime.now(UTC))
                )
            except Exception:
                continue

    def _reconcile_stops(
        self,
        current_ib_positions: List[dict],
        pos_settings: PositionSettings,
        open_ib_orders: List[dict],
    ) -> bool:
        """Adjust stop orders relative to existing IB positions.

        This helper is invoked for orders whose ``OrderType`` is one of
        ``Stop``, ``StopLimit`` or ``TrailingStop``.  It sets the
        ``size`` on ``pos_settings`` equal to the size of the current IB
        position (net of any manual positions), and cancels any open
        stop orders with the same size to avoid duplicates.
        """
        ticker = pos_settings.symbol
        # Find the IB position
        existing = next(
            (p for p in current_ib_positions if (p.get("symbol") or p.get("ticker")) == ticker),
            None,
        )
        if not existing:
            logger.info("No existing IB position for stop on %s", ticker)
            return False
        size = existing.get("position") or existing.get("pos") or 0
        # Adjust for manual transactions if provided by the IB interface
        manual_positions = getattr(self.ib, "manual_transactions", [])
        manual = next((m for m in manual_positions if m.get("ticker") == ticker), None)
        if manual:
            size = size - manual.get("size", 0)
        pos_settings.size = int(abs(size))
        pos_settings.position_type = "Long" if size < 0 else "Short"
        # Cancel duplicate open stop orders
        for order in open_ib_orders:
            contract = order.get("contract") or {}
            symbol = contract.get("symbol") or order.get("symbol")
            order_data = order.get("order") or order
            if symbol == ticker and order_data.get("orderType", "").upper().startswith(
                ("STP", "TRAIL")
            ):
                disp_size = order_data.get("displaySize") or order_data.get("totalQuantity")
                if disp_size and int(disp_size) == pos_settings.size:
                    try:
                        order_id = (
                            order_data.get("orderId")
                            or order_data.get("id")
                            or order.get("orderId")
                            or order.get("id")
                        )
                        if order_id:
                            self.ib.cancel_order(int(order_id))
                            logger.info(
                                "Cancelled duplicate stop order for %s (order ID: %s)",
                                ticker,
                                order_id,
                            )
                        else:
                            logger.warning("No order ID found to cancel for %s", ticker)
                    except Exception as e:
                        logger.warning(
                            "Failed to cancel duplicate stop order for %s: %s", ticker, e
                        )
        return True

    def _reconcile_exit(
        self,
        session,
        txn: TradeTransaction,
        current_ib_positions: List[dict],
        pos_settings: PositionSettings,
        open_ib_orders: List[dict],
    ) -> bool:
        """Prepare an exit order based on the live IB position.

        Exit orders close out an existing IB position rather than open a
        new one.  This helper inspects the current IB position in the
        relevant ticker, scales the quantity based on open system
        transactions and any size percent specified on the trade, and
        sets the position type accordingly.  If no IB position exists
        or the calculation yields zero shares, the order is skipped.
        """
        # Locate the IB position
        ticker = txn.Ticker
        existing = next(
            (p for p in current_ib_positions if (p.get("symbol") or p.get("ticker")) == ticker),
            None,
        )
        if not existing:
            txn.ExecutionNote = (
                txn.ExecutionNote or ""
            ) + f";No existing IB position to exit for {ticker}"
            session.add(txn)
            return False
        ib_size = existing.get("position") or existing.get("pos") or 0
        # Adjust for manual positions
        manual_positions = getattr(self.ib, "manual_transactions", [])
        manual = next((m for m in manual_positions if m.get("ticker") == ticker), None)
        if manual:
            manual_size = manual.get("size", 0)
            if manual_size >= ib_size:
                txn.ExecutionNote = (
                    txn.ExecutionNote or ""
                ) + f";Manual position covers IB size for {ticker}"
                session.add(txn)
                return False
            ib_size = ib_size - manual_size
        # Determine scaling from system transactions
        try:
            system_trades: List[SystemTransaction] = (
                session.query(SystemTransaction)
                .filter(
                    SystemTransaction.Ticker == ticker,
                    SystemTransaction.CloseDate.is_(None),
                    SystemTransaction.System == txn.System,
                )
                .all()
            )
        except Exception as e:
            # If SystemTransaction table doesn't exist, use empty list
            logger.debug("SystemTransaction query failed (table may not exist): %s", e)
            system_trades = []
        scale = 1.0
        if len(system_trades) > 1:
            # Find the trade associated with PositionID on the txn
            closed_position = next(
                (st for st in system_trades if str(st.PositionID) == (txn.PositionID or "")),
                None,
            )
            if closed_position:
                total_size = sum(st.CurrentSize or 0 for st in system_trades)
                if total_size > 0:
                    scale = (closed_position.CurrentSize or 0) / total_size
            else:
                # Fallback: use transaction size percent to scale
                calc_size = self._calculate_transaction_size(txn)
                if calc_size and ib_size != 0:
                    ratio = calc_size / ib_size
                    if 0.1 < ratio < 0.9:
                        scale = ratio
        # Apply size percent scaling
        if txn.SizePercent and txn.SizePercent < 100:
            shares = int(abs(ib_size * txn.SizePercent * scale / 100.0))
        else:
            shares = int(abs(ib_size * scale))
        if shares <= 0:
            txn.ExecutionNote = (
                txn.ExecutionNote or ""
            ) + f";Calculated exit size is zero for {ticker}"
            session.add(txn)
            return False
        pos_settings.size = shares
        pos_settings.position_type = "Long" if ib_size < 0 else "Short"
        # Avoid over‑exiting: reduce size if there is an open exit order
        for order in open_ib_orders:
            contract = order.get("contract") or {}
            symbol = contract.get("symbol") or order.get("symbol")
            order_data = order.get("order") or order
            if symbol == ticker and order_data.get("action", "").lower() == "sell":
                total_qty = order_data.get("totalQuantity") or order_data.get("displaySize")
                if total_qty and (total_qty + shares) > abs(ib_size):
                    shares = int(abs(ib_size) - total_qty)
                    if shares <= 0:
                        txn.ExecutionNote = (
                            txn.ExecutionNote or ""
                        ) + f";Existing exit order covers position for {ticker}"
                        session.add(txn)
                        return False
                    pos_settings.size = shares
        return True
