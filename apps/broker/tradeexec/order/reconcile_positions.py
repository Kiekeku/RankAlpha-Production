"""
Position reconciliation for Interactive Brokers portfolios.

This module provides a Python translation of the C# ``ReconcilePosition``
class found in the original ``IBBrokerExecution`` project.  The goal of
this translation is to capture the high‑level intent of the C# code
while embracing the design patterns used throughout the ``ibkrwebapi``
package.  In particular, the translation relies on the
``IBInterfacing`` wrapper to query open orders and current positions
from Interactive Brokers and uses SQLAlchemy models to persist
changes to the QuantDB database.

The reconciliation process performs several tasks:

* Determine the last successful run date for each trading system and
  expire or mark as filled any outstanding trade transactions older
  than this date.
* Update ``TradeTransaction.FilledPrice`` values from live IB
  positions when orders have been placed but not yet marked as
  filled in the database.
* Mark paper filled trades with size ``-1`` as cancelled.
* Optionally close out any positions held in IB that are not
  represented in the system's open positions by inserting an "Exit"
  transaction.
* Terminate manual portfolio positions that have been open for more
  than 30 days and which no longer correspond to an active IB
  position.

This implementation does not reproduce every nuance of the original
C# code – for example, it omits the historical execution check to
deduplicate fills – but it preserves the core behaviour in a clear,
Pythonic manner.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from tradeexec.core.ib import IBInterfacing
from tradeexec.database.model import (
    Portfolio,
    SystemRunStatus,
    SystemTransaction,
    TradeTransaction,
    get_session,
)

# Optional import: allow unit tests to stub sqlalchemy without failing import
try:
    from tradeexec.tools.init_db import table_exists  # type: ignore
except Exception:  # pragma: no cover - used only in prod paths

    def table_exists(table: str, schema: str | None = None) -> bool:  # type: ignore
        return False


logger = logging.getLogger(__name__)


class ReconcilePosition:
    """Reconcile open positions between IBKR and the QuantDB database."""

    def __init__(
        self,
        ib_interface: IBInterfacing,
        program_name: str,
        system_prefixes: Sequence[str],
        *,
        account_number: Optional[str] = None,
        close_unaccounted_positions: bool = True,
        manual_transactions: Optional[Sequence[str]] = None,
    ) -> None:
        """
        Parameters
        ----------
        ib_interface : IBInterfacing
            Authenticated instance used to query IBKR for open orders and
            current positions.
        program_name : str
            Name of the trading program.  Used to assign the ``System``
            field on any automatically generated exit transactions.
        system_prefixes : Sequence[str]
            A list of trading system prefixes to reconcile.  Each prefix
            corresponds to a set of strategy runs recorded in the
            ``SystemTransactions`` and ``SystemRunStatus`` tables.
        account_number : str, optional
            IBKR account number.  If provided, manual positions are
            filtered to this account when pruning stale entries.
        close_unaccounted_positions : bool, default True
            Whether to generate exit transactions for IB positions that
            have no corresponding system entry.
        manual_transactions : Sequence[str], optional
            A list of tickers that represent manually placed orders
            pending on the system.  These are excluded from the
            unaccounted positions check.
        """
        self.ib = ib_interface
        self.program_name = program_name
        self.system_prefixes = list(system_prefixes)
        self.account_number = account_number
        self.close_unaccounted_positions = close_unaccounted_positions
        self.manual_transactions = set(manual_transactions or [])

    # ------------------------------------------------------------------ #
    # Helper methods
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalise_order_list(open_orders: Iterable[dict]) -> List[dict]:
        """Normalise the shape of open order payloads.

        The IBKR API returns different shapes for open orders depending on
        the version of the underlying ``ibind`` library.  This helper
        flattens all supported forms into a uniform list of order
        dictionaries.
        """
        orders: List[dict] = []
        for item in open_orders:
            if isinstance(item, dict):
                orders.append(item)
        return orders

    @staticmethod
    def _extract_order_info(order: dict) -> tuple[str, str, str]:
        """Extract the symbol, action and order type from an order dict."""
        # Newer ibind exposes nested structures, older versions may flatten
        contract = order.get("contract") or order.get("contract_id") or {}
        ticker = (
            contract.get("symbol")
            or contract.get("ticker")
            or order.get("ticker")
            or order.get("symbol")
        )
        order_data = order.get("order") or order
        action = (order_data.get("action") or order_data.get("side") or "").capitalize()
        order_type = order_data.get("orderType") or order_data.get("type") or ""
        return (str(ticker) if ticker is not None else "", action, order_type)

    @staticmethod
    def _extract_position_info(position: dict) -> tuple[str, float, float, str]:
        """Extract symbol, size, average cost and security type from a position dict."""
        ticker = position.get("ticker") or position.get("symbol")
        # Some versions return 'position', others 'position' nested
        size = position.get("position") or position.get("pos", 0.0)
        avg_cost = (
            position.get("avgCost")
            or position.get("averageCost")
            or position.get("avg_price")
            or 0.0
        )
        sec_type = position.get("secType") or position.get("securityType") or ""
        return str(ticker) if ticker is not None else "", float(size), float(avg_cost), sec_type

    def _compute_last_order_placed_date(self, session) -> date:
        """
        Compute the earliest recent run date across all system prefixes.

        The original C# code examines the ``SystemRunStatus`` table for
        each system prefix and returns the earliest ``LastSuccessfulRun``
        within the past 7 days.  Additional adjustments are made for
        weekend cut‑off times.  Those rules are reproduced here.
        """
        today = date.today()
        last_order_placed_date = today

        for prefix in self.system_prefixes:
            # Grab all runs matching the prefix
            statuses = (
                session.query(SystemRunStatus)
                .filter(SystemRunStatus.System.startswith(prefix))
                .all()
            )
            for status in statuses:
                run_date = status.LastSuccessfulRun.date() if status.LastSuccessfulRun else None
                if not run_date:
                    continue
                if run_date < last_order_placed_date and (run_date + timedelta(days=7) > today):
                    last_order_placed_date = run_date

        # Apply weekend adjustments similar to the C# logic
        if last_order_placed_date.weekday() == 4 and today.weekday() != 4:
            # If last run was Friday and today isn't Friday, bump forward a day
            last_order_placed_date = last_order_placed_date + timedelta(days=1)
        if last_order_placed_date.weekday() == 0:
            # If last run was Monday and before market open, move back to previous Friday
            # The ExecutionProgram.MarketOpenTime default is 9:30, we assume 9:30 for now
            market_open = datetime.combine(last_order_placed_date, datetime.min.time()).replace(
                hour=9, minute=30
            )
            if datetime.now() < market_open:
                last_order_placed_date = last_order_placed_date - timedelta(days=2)
        return last_order_placed_date

    def _prefetch_existing_exit_keys(
        self, session, as_of_date: date
    ) -> Optional[set[tuple[str, str]]]:
        """Load existing exit-style txns once for quick symbol/action lookup."""
        try:
            rows = (
                session.query(
                    TradeTransaction.Ticker,
                    TradeTransaction.TradeType,
                    TradeTransaction.Description,
                )
                .filter(TradeTransaction.TransactionDate >= as_of_date)
                .filter(TradeTransaction.System.startswith(self.program_name))
                .filter(TradeTransaction.TradeType.in_(["Buy", "Sell", "Exit"]))
                .all()
            )
        except Exception as exc:
            logger.debug("Failed to prefetch reconcile exits: %s", exc)
            return None

        keys: set[tuple[str, str]] = set()
        for ticker, trade_type, description in rows:
            symbol = str(ticker or "").upper()
            if not symbol:
                continue
            kind = str(trade_type or "").capitalize()
            if kind in {"Buy", "Sell"}:
                keys.add((symbol, kind))
                continue
            if kind == "Exit" and str(description or "") == "Reconcile Systems with IB":
                keys.add((symbol, "Buy"))
                keys.add((symbol, "Sell"))
        return keys

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def reconcile(self) -> List[TradeTransaction]:
        """
        Perform a full reconciliation of IB positions against the database.

        Returns
        -------
        list of TradeTransaction
            Newly created exit transactions, if any.  The caller may
            choose to forward these to an order placement component or
            inspect them for further processing.
        """
        new_exit_transactions: List[TradeTransaction] = []

        # Safety: legacy tables may not exist in the shared RankAlpha schema.
        # If any required table is missing, skip reconciliation gracefully.
        try:
            needed = [
                ("TradeTransaction", None),
                ("SystemRunStatus", None),
                ("SystemTransactions", None),
            ]
            missing = [name for name, schema in needed if not table_exists(name, schema=schema)]
            if missing:
                logger.info(
                    "ReconcilePosition skipped: missing legacy table(s): %s",
                    ", ".join(missing),
                )
                return []
        except Exception:
            # If inspector fails, err on the side of skipping to avoid noisy crashes
            logger.info("ReconcilePosition skipped: unable to verify legacy tables")
            return []
        with get_session() as session:
            # Pull live data from IBKR
            open_orders_raw = self.ib.get_open_orders()
            open_orders = self._normalise_order_list(open_orders_raw)
            current_positions = self.ib.get_positions()

            # Extract open order meta for quick checks
            open_order_info = [self._extract_order_info(o) for o in open_orders]

            # Compute last order placed date across systems
            last_order_placed_date = self._compute_last_order_placed_date(session)
            logger.info("Reconciliation: last order placed date = %s", last_order_placed_date)

            # ------------------------------------------------------------------
            # Step 1: Expire or mark unfilled transactions
            # ------------------------------------------------------------------
            for prefix in self.system_prefixes:
                # Fetch unfilled transactions for this system
                unfilled = (
                    session.query(TradeTransaction)
                    .filter(TradeTransaction.OrderPlaced.is_(None))
                    .filter(TradeTransaction.FilledPrice.is_(None))
                    .filter(
                        (TradeTransaction.PaperFilledSize.is_(None))
                        | (TradeTransaction.PaperFilledSize >= 0)
                    )
                    .filter(TradeTransaction.System.startswith(prefix))
                    .all()
                )
                for tx in unfilled:
                    tx_date = tx.TransactionDate
                    if tx_date and tx_date < last_order_placed_date:
                        tx.OrderPlaced = False
                        note = tx.Description or ""
                        tx.ExecutionNote = f"Expired: {note}"
                        logger.debug(
                            "Transaction %s expired (date %s < %s)",
                            tx.ID,
                            tx_date,
                            last_order_placed_date,
                        )
                    # The original code also cancels trades if a matching historical execution is found.
                    # That step is omitted here because historical executions are not fetched.
                session.flush()

            # ------------------------------------------------------------------
            # Step 2: Fill in FilledPrice from IB positions
            # ------------------------------------------------------------------
            # Pre‑index current positions by symbol for quick lookup
            from typing import Any

            position_map: dict[str, dict[str, Any]] = {}
            for pos in current_positions:
                symbol, size, avg_cost, sec_type = self._extract_position_info(pos)
                if symbol:
                    position_map[symbol.upper()] = {
                        "size": size,
                        "avg_cost": avg_cost,
                        "sec_type": sec_type,
                    }

            filled = (
                session.query(TradeTransaction)
                .filter(TradeTransaction.OrderPlaced.is_(True))
                .filter(TradeTransaction.FilledPrice.is_(None))
                .all()
            )
            today = date.today()
            for tx in filled:
                # Check if recent (within three days)
                if tx.TransactionDate and (tx.TransactionDate + timedelta(days=3) > today):
                    key = (tx.Ticker or "").upper()
                    pos_info = position_map.get(key)
                    if pos_info:
                        tx.FilledPrice = float(pos_info["avg_cost"])
                        logger.debug(
                            "Filled price for transaction %s set to %s based on live position.",
                            tx.ID,
                            tx.FilledPrice,
                        )
            session.flush()

            # ------------------------------------------------------------------
            # Step 3: Reconcile paper filled trades (size == -1)
            # ------------------------------------------------------------------
            paper = (
                session.query(TradeTransaction)
                .filter(TradeTransaction.PaperFilledSize == -1)
                .filter(TradeTransaction.OrderPlaced.is_(None))
                .all()
            )
            for tx in paper:
                tx.OrderPlaced = False
                tx.ExecutionNote = "Reconcile Paper Fill Size -1"
                logger.debug("Paper filled transaction %s marked as cancelled.", tx.ID)
            session.flush()

            # ------------------------------------------------------------------
            # Step 4: Close IB positions not present in system positions
            # ------------------------------------------------------------------
            if self.close_unaccounted_positions:
                existing_exit_keys = self._prefetch_existing_exit_keys(session, today)
                # Fetch all open system positions
                system_positions = (
                    session.query(SystemTransaction)
                    .filter(SystemTransaction.CloseDate.is_(None))
                    .all()
                )
                # Build a set for quick membership testing: (symbol, trans_type)
                syspos_set = set()
                for sp in system_positions:
                    syspos_set.add((sp.Ticker.upper(), sp.TransactionType))

                for pos in current_positions:
                    symbol, size, avg_cost, sec_type = self._extract_position_info(pos)
                    if not symbol or sec_type.upper() != "STK" or size == 0:
                        continue  # Only handle stock positions for now
                    # Determine expected transaction type for closing this position
                    trans_type = "Sell" if size > 0 else "Buy"
                    in_sys = (symbol.upper(), trans_type) in syspos_set
                    if in_sys:
                        continue  # position accounted for by a system
                    if symbol.upper() in self.manual_transactions:
                        continue  # skip manual transactions
                    if existing_exit_keys is not None:
                        if (symbol.upper(), trans_type) in existing_exit_keys:
                            continue
                    else:
                        # Fallback: check no active exit order in DB for today or later
                        exists_exit = (
                            session.query(TradeTransaction)
                            .filter(TradeTransaction.Ticker.ilike(symbol))
                            .filter(TradeTransaction.TransactionDate >= today)
                            .filter(TradeTransaction.System.startswith(self.program_name))
                            .filter(
                                (TradeTransaction.TradeType == trans_type)
                                | (
                                    (TradeTransaction.TradeType == "Exit")
                                    & (TradeTransaction.Description == "Reconcile Systems with IB")
                                )
                            )
                            .first()
                        )
                        if exists_exit:
                            continue
                    # Check no open order in IB that already exits this position
                    order_exists = False
                    for order_sym, action, order_type in open_order_info:
                        if order_sym and order_sym.upper() == symbol.upper():
                            # Action in IB orders is capitalised (Sell/Buy)
                            if action == trans_type and order_type in {
                                "LMT",
                                "MOC",
                                "MarketOnClose",
                                "Moc",
                                "LmtOrder",
                            }:
                                order_exists = True
                                break
                    if order_exists:
                        continue
                    # Create a new exit transaction
                    new_tx = TradeTransaction()
                    new_tx.Ticker = symbol
                    new_tx.TradeType = "Exit"
                    new_tx.OrderType = "MarketOnClose"
                    new_tx.TransactionDate = today
                    new_tx.Description = "Reconcile Systems with IB"
                    new_tx.System = self.program_name
                    new_tx.ExecutionNote = ""
                    new_tx.CreateDate = datetime.now()
                    session.add(new_tx)
                    new_exit_transactions.append(new_tx)
                    logger.info(
                        "Created reconcile exit transaction for %s (%s size: %s)",
                        symbol,
                        trans_type,
                        size,
                    )
                session.flush()

                # Terminate stale manual portfolio positions older than 30 days
                if self.account_number:
                    cutoff_date = today - timedelta(days=30)
                    manual_positions = (
                        session.query(Portfolio)
                        .filter(Portfolio.Account == self.account_number)
                        .filter(Portfolio.EffStartDate <= cutoff_date)
                        .filter(Portfolio.EffEndDate >= today)
                        .all()
                    )
                    for mp in manual_positions:
                        # Only terminate if no matching live IB position exists
                        if mp.Ticker and mp.Ticker.upper() not in position_map:
                            mp.EffEndDate = today
                            logger.info(
                                "Terminated manual portfolio position %s (ticker %s)",
                                mp.ID,
                                mp.Ticker,
                            )
                    session.flush()

        return new_exit_transactions
