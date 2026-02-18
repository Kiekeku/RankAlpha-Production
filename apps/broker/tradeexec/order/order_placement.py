"""
Order submission helper for Interactive Brokers.

This module provides a Python translation of the C# ``OrderPlacement``
class from the ``IBBrokerExecution`` project.  The original class
implemented a number of features such as interactive Telegram
confirmations, nuanced limit‑price optimisation using moving
averages, and day‑trading specific skip logic.  In the interest of
clarity and maintainability, the translation presented here focuses
on the core responsibilities of the class: adjusting existing open
orders and submitting new orders in sensible chunks.  It omits
interactive confirmations and complex price tuning heuristics.

If your workflow depends on the exact behaviour of the C# version
(for example, size halving for penny stocks or earnings calendar
checks), you can extend this translation by borrowing additional
logic from the source file.

Example
-------

```
from tradeexec.core.ib import IBInterfacing
from tradeexec.database.model import TradeTransaction
from tradeexec.place_transaction import PositionSettings

ib = IBInterfacing(api_key=..., secret=...)
order_placer = OrderPlacement(ib)

position = PositionSettings(
    symbol="AAPL", size=500, position_type="Long", order_type="Limit", limit_price=150.0
)
txn = session.query(TradeTransaction).get(123)
order_placer.open_new_order(position, txn)
```
"""

from __future__ import annotations

import logging
from datetime import datetime
from math import ceil
from typing import List, Optional, Tuple

from tradeexec.core.ib import IBInterfacing
from tradeexec.database.model import TradeTransaction, get_session
from tradeexec.order.place_transaction import PositionSettings
from tradeexec.utils.pacing import OrderPacer, make_order_pacer

logger = logging.getLogger(__name__)


class OrderPlacement:
    """Submit and adjust orders via an Interactive Brokers interface."""

    def __init__(
        self,
        ib_interface: IBInterfacing,
        *,
        chunk_size: int = 10_000,
        order_pacer: Optional[OrderPacer] = None,
    ) -> None:
        """
        Parameters
        ----------
        ib_interface : IBInterfacing
            Authenticated wrapper used to place and modify orders.
        chunk_size : int, default 10,000
            Maximum number of shares to submit per order chunk.  Large
            orders will be split into multiple submissions to improve
            execution quality and to avoid potential broker limits.
        """
        self.ib = ib_interface
        self.chunk_size = chunk_size
        self._order_pacer: OrderPacer = order_pacer or make_order_pacer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def adjust_open_order(self, open_order: Tuple[dict, Optional[TradeTransaction]]) -> None:
        """Modify an existing limit order if the market has moved.

        The C# version of this method updates an open limit order when
        the current bid/ask has diverged materially from the order’s
        limit price.  The translation replicates that high‑level
        behaviour: it fetches the latest quote, computes a new limit
        price using a simple midpoint of the bid/ask spread, and
        invokes ``modify_order`` on the IB interface if the absolute
        difference exceeds 0.2 % of the existing limit price.

        Parameters
        ----------
        open_order : tuple
            A tuple consisting of an order dictionary (as returned from
            ``ib.get_open_orders()``) and an optional ``TradeTransaction``
            associated with the order.  The transaction is used to
            determine the system tag for logging purposes.
        """
        order_dict, txn = open_order
        contract = order_dict.get("contract") or {}
        order_data = order_dict.get("order") or order_dict
        symbol = contract.get("symbol") or order_dict.get("symbol")
        exchange = contract.get("exchange") or order_dict.get("exchange") or ""
        action = order_data.get("action", "").capitalize()
        order_type = order_data.get("orderType", "").upper()
        limit_price = order_data.get("lmtPrice") or order_data.get("limitPrice")
        quantity = order_data.get("totalQuantity") or order_data.get("displaySize")

        if order_type != "LMT" or not limit_price or not quantity:
            # Only adjust limit orders with a valid price and quantity
            return
        if not symbol:
            return

        try:
            quote = self.ib.get_market_data(symbol, exchange)
        except Exception as e:
            logger.warning("Unable to retrieve market data for %s: %s", symbol, e)
            return
        bid = quote.get("bid")
        ask = quote.get("ask")
        if not bid or not ask or bid <= 0 or ask <= 0:
            return
        new_limit = (bid + ask) / 2.0
        price_diff = abs(new_limit - limit_price)
        if limit_price > 0 and (price_diff / limit_price) > 0.002:
            # Price has moved by more than 0.2 % – adjust the order
            pos_settings = PositionSettings(
                symbol=symbol,
                size=int(quantity),
                position_type="Long" if action == "Buy" else "Short",
                order_type="Limit",
                limit_price=new_limit,
            )
            try:
                logger.info(
                    "Modifying open order for %s: new limit %s (old %s)",
                    symbol,
                    new_limit,
                    limit_price,
                )
                order_id = order_data.get("orderId") or order_data.get("id")
                self.ib.modify_order(pos_settings, order_id)
                # Update execution note if a transaction is attached
                if txn and isinstance(txn, TradeTransaction):
                    txn.ExecutionNote = (
                        txn.ExecutionNote or ""
                    ) + f";Modified limit from {limit_price} to {new_limit}"
                    with get_session() as session:
                        session.merge(txn)
            except Exception as e:
                logger.error("Failed to modify order for %s: %s", symbol, e)

    def open_new_order(self, position: PositionSettings, transaction: TradeTransaction) -> None:
        """Submit a new order according to the given settings.

        This method encapsulates the main workflow of the C# ``OpenNewOrder``
        implementation.  It fetches current market data to compute an
        indicative trade value, halves position size for penny stocks,
        and then delegates to ``_place_order_chunks`` to perform the
        actual order submission.  Interactive confirmations and
        elaborate skip logic (earnings calendar, big drop checks, etc.)
        are intentionally omitted.

        Parameters
        ----------
        position : PositionSettings
            A fully specified order descriptor.  ``symbol``, ``size`` and
            ``order_type`` must be populated.  ``limit_price`` and
            ``stop_price`` may be provided for limit and stop orders.
        transaction : TradeTransaction
            Database row associated with the order.  Its ``ExecutionNote``
            and status flags will be updated based on the outcome.
        """
        symbol = position.symbol
        exchange = getattr(position, "exchange", "")
        # Fetch current quote if possible
        try:
            quote = self.ib.get_market_data(symbol, exchange)
        except Exception as e:
            logger.warning("Unable to fetch market data for %s: %s", symbol, e)
            quote = None
        bid = quote.get("bid") if quote else None
        ask = quote.get("ask") if quote else None
        close_price = None
        try:
            close_price = self.ib.get_last_close_price(symbol, exchange)
        except Exception:
            close_price = None

        # Halve size for cheap stocks (< $5) to reduce risk exposure
        def is_price_low(val: Optional[float]) -> bool:
            return val is not None and val > 0 and val < 5

        if any(is_price_low(p) for p in [close_price, (bid + ask) / 2.0 if bid and ask else None]):
            original_size = position.size
            position.size = max(1, position.size // 2)
            logger.info(
                "Price below $5 for %s – halving order size from %s to %s",
                symbol,
                original_size,
                position.size,
            )
        # Write a descriptive execution note
        amount = None
        if bid and ask and position.order_type.lower() in {"market", "marketonclose"}:
            amount = position.size * ((bid + ask) / 2.0)
        elif position.limit_price:
            amount = position.size * position.limit_price
        elif close_price:
            amount = position.size * close_price
        if amount:
            exec_note = (
                f"Submitting {position.position_type} {position.size} {symbol} for ${amount:,.2f}"
            )
        else:
            exec_note = f"Submitting {position.position_type} {position.size} {symbol}"
        transaction.ExecutionNote = (transaction.ExecutionNote or "") + f";{exec_note}"
        # Persist the note immediately
        with get_session() as session:
            session.merge(transaction)
        # Submit the order in chunks
        try:
            self._place_order_chunks(position, transaction)
        except Exception as e:
            logger.error("Error while placing order for %s: %s", symbol, e)
            transaction.ExecutionNote = (
                transaction.ExecutionNote or ""
            ) + f";Failed to place order: {e}"
            with get_session() as session:
                session.merge(transaction)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _place_order_chunks(
        self, position: PositionSettings, transaction: TradeTransaction
    ) -> None:
        """Split a large order into smaller chunks and submit sequentially."""
        total_size = position.size
        chunk_count = ceil(total_size / self.chunk_size)
        remaining = total_size
        placed_ids: List[int] = []
        for chunk_index in range(chunk_count):
            this_size = min(remaining, self.chunk_size)
            remaining -= this_size
            chunk_pos = PositionSettings(
                symbol=position.symbol,
                size=this_size,
                position_type=position.position_type,
                order_type=position.order_type,
                limit_price=position.limit_price,
                stop_price=position.stop_price,
                profit_target=position.profit_target,
                stop_loss=position.stop_loss,
                tag=position.tag,
                custom_string=position.custom_string,
            )
            # Choose an indicative price for partial fills
            price_hint = None
            if chunk_pos.limit_price:
                price_hint = chunk_pos.limit_price
            elif transaction.LastPrice:
                price_hint = float(transaction.LastPrice)
            # Submit the order via the IB interface
            self._order_pacer.pace()
            order_ids: List[int] = self.ib.place_order(chunk_pos, price_hint)
            placed_ids.extend(order_ids or [])
            logger.info(
                "Placed order chunk %s/%s for %s shares of %s (order IDs: %s)",
                chunk_index + 1,
                chunk_count,
                this_size,
                position.symbol,
                order_ids,
            )
        # Update the transaction to reflect that the order has been placed
        transaction.OrderPlaced = True
        transaction.OrderPlacedTime = datetime.now()
        note_suffix = " ".join(str(o) for o in placed_ids)
        transaction.ExecutionNote = (transaction.ExecutionNote or "") + f";IDs {note_suffix}"
        with get_session() as session:
            session.merge(transaction)
