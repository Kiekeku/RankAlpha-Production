"""
fills_ingestor.py

Polls IBKR recent executions and records them into RankAlpha:
  - Inserts rows into rankalpha.fact_portfolio_trade (ledger)
  - Marks corresponding rankalpha.fact_trade_recommendation rows as filled

Idempotence: computes a deterministic UUID for each fill using
  account|symbol|exec_ts|side|qty|price, and inserts with ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tradeexec.core.ib import IBInterfacing
from tradeexec.database.model import get_session
from tradeexec.metrics import (
    normalize_action_label,
    observe_time_to_fill_seconds,
    record_fill_ingested,
)

from .db_helpers import ensure_broker_portfolio


class FillsIngestor:
    def __init__(self, ib: IBInterfacing, account_number: str | None) -> None:
        self.ib = ib
        self.account_number = account_number or "UNKNOWN"

    # --------------------------- public API ----------------------------
    def ingest_once(self, lookback_seconds: int = 900) -> int:
        """Fetch recent fills and write them to the DB. Returns rows inserted."""
        trades = self.ib.get_recent_trades(since_seconds=lookback_seconds)
        if not trades:
            return 0

        inserted = 0
        with get_session() as session:
            portfolio = self._ensure_portfolio(session)
            for t in trades:
                norm = self._normalise_trade(t)
                if norm is None:
                    continue

                # symbol -> stock_key
                stock_key = self._get_or_create_stock(session, norm["symbol"])  # type: ignore[arg-type]
                trade_id = self._compute_trade_uuid(
                    self.account_number,
                    norm["symbol"],
                    norm["exec_ts"],
                    norm["side"],
                    norm["quantity"],
                    norm["price"],
                )

                # Insert into fact_portfolio_trade (idempotent)
                did_insert = self._insert_trade_row(
                    session,
                    trade_id=trade_id,
                    portfolio_id=getattr(portfolio, "portfolio_id"),
                    stock_key=stock_key,
                    exec_ts=norm["exec_ts"],
                    side=norm["side"],
                    quantity=norm["quantity"],
                    price=norm["price"],
                    commission=norm.get("commission"),
                    venue=norm.get("venue"),
                    strategy_tag=None,
                )
                inserted += did_insert
                if did_insert:
                    record_fill_ingested(account=self.account_number, count=1)

                # Update recommendation filled fields if a matching one exists
                try:
                    self._mark_recommendation_filled(
                        session,
                        symbol=norm["symbol"],
                        action=self._action_from_side(norm["side"]),
                        exec_ts=norm["exec_ts"],
                        trade_date=norm["exec_ts"].date(),
                        price=norm["price"],
                    )
                except Exception:
                    pass

        return inserted

    # -------------------------- internals ------------------------------
    def _ensure_portfolio(self, session):
        return ensure_broker_portfolio(session, self.account_number)

    def _get_or_create_stock(self, session, symbol: str) -> int:
        from apps.common.src.crud import get_or_create_stock as _get

        return int(_get(session, symbol))

    def _action_from_side(self, side: str) -> str:
        s = side.upper()
        if s in ("BUY", "BOT"):
            return "BUY"
        return "SELL"

    def _mark_recommendation_filled(
        self,
        session,
        *,
        symbol: str,
        action: str,
        exec_ts: datetime,
        trade_date: date,
        price: float,
    ) -> None:
        # Update rankalpha.fact_trade_recommendation for this account+symbol+date+action
        from apps.common.src.models import DimDate, DimSource, DimStock, FactTradeRecommendation

        sname = f"broker::{self.account_number}"
        subq = (
            select(FactTradeRecommendation.recommendation_id, FactTradeRecommendation.create_ts)
            .join(DimDate, DimDate.date_key == FactTradeRecommendation.date_key)
            .join(DimStock, DimStock.stock_key == FactTradeRecommendation.stock_key)
            .join(DimSource, DimSource.source_key == FactTradeRecommendation.source_key)
            .where(DimDate.full_date == trade_date)
            .where(DimStock.symbol == symbol)
            .where(FactTradeRecommendation.action == action)
            .where(DimSource.source_name == sname)
            .where(FactTradeRecommendation.filled_date.is_(None))
            .order_by(FactTradeRecommendation.create_ts.desc())
            .limit(1)
        )
        row = session.execute(subq).one_or_none()
        if not row:
            return
        rec_id, create_ts = row
        session.execute(
            update(FactTradeRecommendation)
            .where(FactTradeRecommendation.recommendation_id == rec_id)
            .values(filled_price=price, filled_date=trade_date)
        )
        try:
            if create_ts is not None:
                if getattr(create_ts, "tzinfo", None) is not None:
                    create_ts = create_ts.astimezone(timezone.utc).replace(tzinfo=None)
                if getattr(exec_ts, "tzinfo", None) is not None:
                    exec_ts = exec_ts.astimezone(timezone.utc).replace(tzinfo=None)
                seconds = (exec_ts - create_ts).total_seconds()
                observe_time_to_fill_seconds(
                    account=self.account_number,
                    action=normalize_action_label(action),
                    seconds=seconds,
                )
        except Exception:
            return

    def _compute_trade_uuid(
        self,
        account: str,
        symbol: str,
        exec_ts: datetime,
        side: str,
        qty: float,
        price: float,
    ) -> uuid.UUID:
        key = f"{account}|{symbol}|{exec_ts.isoformat()}|{side.upper()}|{qty:.8f}|{price:.8f}"
        return uuid.uuid5(uuid.NAMESPACE_URL, f"rankalpha://portfolio_trade/{key}")

    def _insert_trade_row(
        self,
        session,
        *,
        trade_id: uuid.UUID,
        portfolio_id,
        stock_key: int,
        exec_ts: datetime,
        side: str,
        quantity: float,
        price: float,
        commission: Optional[float],
        venue: Optional[str],
        strategy_tag: Optional[str],
    ) -> int:
        from apps.common.src.models import FactPortfolioTrade

        stmt = (
            pg_insert(FactPortfolioTrade)
            .values(
                trade_id=trade_id,
                portfolio_id=portfolio_id,
                stock_key=stock_key,
                exec_ts=exec_ts,
                side="BUY" if side.upper() in ("BUY", "BOT") else "SELL",
                quantity=quantity,
                price=price,
                commission=commission,
                venue=venue,
                strategy_tag=strategy_tag,
            )
            .on_conflict_do_nothing(index_elements=[FactPortfolioTrade.trade_id])
        )
        res = session.execute(stmt)
        # rowcount is 0 on DO NOTHING when conflict
        return 1 if res.rowcount and res.rowcount > 0 else 0

    def _normalise_trade(self, t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            symbol = t.get("symbol") or t.get("localSymbol") or t.get("ticker")
            side = (t.get("side") or t.get("action") or "").upper()
            qty = float(t.get("quantity") or t.get("qty") or t.get("size") or 0)
            px = float(t.get("price") or t.get("avgPrice") or t.get("fillPrice") or 0)
            if not symbol or not side or qty == 0 or px == 0:
                return None
            # exec time: epoch ms/sec or ISO string
            exec_raw = t.get("time") or t.get("timestamp") or t.get("dateTime")
            exec_ts = self._parse_when(exec_raw)
            commission = t.get("commission") or t.get("comm")
            commission = float(commission) if commission not in (None, "") else None
            venue = t.get("venue") or t.get("exchange")
            return {
                "symbol": str(symbol),
                "side": side,
                "quantity": float(qty),
                "price": float(px),
                "exec_ts": exec_ts,
                "commission": commission,
                "venue": str(venue) if venue else None,
            }
        except Exception:
            return None

    def _parse_when(self, val: Any) -> datetime:
        if val is None:
            return datetime.now(timezone.utc).replace(tzinfo=None)
        # epoch (ms or sec)
        try:
            iv = int(val)
            if iv > 10_000_000_000:  # ms
                iv = iv // 1000
            return datetime.fromtimestamp(iv, tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
        # ISO string
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            return datetime.now(timezone.utc).replace(tzinfo=None)
