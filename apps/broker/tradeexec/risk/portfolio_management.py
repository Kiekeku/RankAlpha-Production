"""
portfolio_management.py

A Python port of the C# PortfolioManagement class from the RightEdgePlugIns
project.  This module integrates with the ibkrwebapi IBInterfacing class and
uses PositionSettings from tradeexec.order.place_transaction.  It retains the
core hedging logic — logging portfolio values, computing drawdown ratios,
monitoring index movements, issuing Telegram reminders, and placing hedge orders.

This translation omits direct database writes in favour of in‑memory tracking
and uses IBInterfacing methods to query account summaries, positions, quotes
and to place or cancel orders.

© 2025 ACC.  Python 3.12
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from tradeexec.core.ib import IBInterfacing
from tradeexec.order.place_transaction import PositionSettings
from tradeexec.utils.pacing import OrderPacer, make_order_pacer

if TYPE_CHECKING:
    from tradeexec.comms.telegram import TelegramCommunicator

logger = logging.getLogger(__name__)


@dataclass
class HedgeWarning:
    """Track the number of hedge warnings issued per day."""

    date: date
    long_count: int = 0
    short_count: int = 0


class PortfolioManagement:
    """
    A simplified risk management helper built on top of IBKRWebAPI.

    It mirrors the high-level behaviour of the original C# class: log account
    values, monitor daily performance of SPX/NDX (or their futures) and
    automatically suggest/execute hedges when drawdowns exceed a threshold.
    """

    def __init__(
        self,
        ib: IBInterfacing,
        hedge_threshold: float = 0.95,
        telegram_bot: Optional["TelegramCommunicator"] = None,
        wait_for_confirmation: bool = False,
        order_pacer: Optional[OrderPacer] = None,
    ) -> None:
        self.ib = ib
        self.hedge_threshold = hedge_threshold
        self.telegram_bot = telegram_bot
        self.wait_for_confirmation = wait_for_confirmation
        self._order_pacer: OrderPacer = order_pacer or make_order_pacer()

        self.hedge_reminder = 0
        self.chat_response: Optional[str] = None

        # History of net liquidity values for the current run.
        self.portfolio_history: List[float] = []

        # Hedge warning counts (reset daily).
        self.warning = HedgeWarning(date=date.today())

    def log_portfolio_values(self) -> float:
        """Fetch account summary and append net liquidity to the internal history."""
        try:
            summary = self.ib.get_account_summary()
        except Exception as e:
            logger.warning("Failed to fetch account summary: %s", e)
            return 0.0

        net_liq = 0.0
        if isinstance(summary, dict):
            for _key, value in summary.items():
                # IBKR ledger returns nested dicts keyed by currency
                if isinstance(value, dict):
                    netliquid = value.get("netliquidation") or value.get("NetLiquidation")
                    if netliquid is not None:
                        net_liq = float(netliquid)
                        break

        self.portfolio_history.append(net_liq)
        logger.info("Logged net liquidity: %.2f", net_liq)
        return net_liq

    def short_symbols(self) -> List[str]:
        """
        Determine which symbols are currently held short (or long in inverse ETFs).
        Mirrors the logic in the C# ShortSymbols method:contentReference[oaicite:0]{index=0}.
        """
        try:
            positions = self.ib.get_positions()
        except Exception as e:
            logger.warning("Failed to fetch positions: %s", e)
            return []

        shorts: List[str] = []
        for pos in positions:
            ticker = pos.get("ticker") or pos.get("symbol")
            size = pos.get("position") or pos.get("pos", 0.0)
            avg_cost = pos.get("avgCost") or pos.get("averageCost") or pos.get("avg_price") or 0.0
            if not ticker or avg_cost == 0:
                continue
            # negative size means short; positive size in inverse ETFs counts as a short proxy
            if size < 0 and ticker in ("NQ", "QQQ", "ES", "SPY"):
                shorts.append(ticker)
                break
            if size > 0 and ticker in ("SQQQ", "SH", "TF"):
                shorts.append(ticker)
                break
        return shorts

    def _get_daily_ratio(self, ticker: str, sec_type: str = "IND") -> float:
        """
        Compute the ratio of the most recent closing price to the opening price for a ticker.
        Uses intraday historical data (1 hour bars) from IBKR; falls back to 1.0 on error.
        """
        try:
            bars = self.ib.get_historical_data(
                symbol=ticker, period="1 D", bar="1 hour", sec_type=sec_type
            )
            if isinstance(bars, list) and bars:
                closes = [
                    b.get("close") or b.get("CLOSE")
                    for b in bars
                    if b.get("close") or b.get("CLOSE")
                ]
                if closes and closes[0]:
                    return float(closes[-1] / closes[0]) if closes[0] != 0 else 1.0
        except Exception as e:
            logger.warning("Failed to fetch historical data for %s: %s", ticker, e)
        return 1.0

    def send_reminder(self) -> bool:
        """
        C# reminder logic:contentReference[oaicite:1]{index=1}:
        only send a message every 60th call to run_hedge.
        """
        return self.hedge_reminder % 60 == 0

    def log_hedge_warning(self, hedge_long: bool) -> HedgeWarning:
        """
        Increment the long or short hedge warning count for today's date:contentReference[oaicite:2]{index=2}.
        """
        today = date.today()
        if self.warning.date != today:
            self.warning = HedgeWarning(date=today)
        if hedge_long:
            self.warning.long_count += 1
        else:
            self.warning.short_count += 1
        return self.warning

    def run_hedge(self) -> None:
        """
        Execute the full hedging routine.

        This follows the core logic of the C# RunHedge method:contentReference[oaicite:3]{index=3}:
        * log portfolio values and compute drawdown ratios,
        * calculate daily index ratios for SPX and NDX,
        * notify on existing shorts if market rallies,
        * determine appropriate hedge instrument and quantity,
        * optionally prompt for user confirmation and place the hedge order.
        """
        net_liq = self.log_portfolio_values()
        if len(self.portfolio_history) < 2:
            return  # need at least two points to compute a ratio

        current_ratio = net_liq / self.portfolio_history[0] if self.portfolio_history[0] else 1.0
        highest_value = max(self.portfolio_history)
        highest_ratio = net_liq / highest_value if highest_value else 1.0
        hedge_required = (
            current_ratio < self.hedge_threshold or highest_ratio < self.hedge_threshold
        )

        logger.info(
            "Hedge check: current_ratio=%.3f, highest_value=%.2f, highest_ratio=%.3f, hedge_required=%s",
            current_ratio,
            highest_value,
            highest_ratio,
            hedge_required,
        )
        if not hedge_required:
            return

        # Compute ratios for SPX and NDX indices
        current_es_ratio = self._get_daily_ratio("SPX")
        current_nq_ratio = self._get_daily_ratio("NDX")
        if current_es_ratio == 0 or current_nq_ratio == 0:
            current_es_ratio = current_nq_ratio = 1.0

        shorts = self.short_symbols()

        # Remind to exit if market has rallied
        if current_es_ratio > 1 and any(sym in shorts for sym in ("SPY", "SH", "ES")):
            if self.send_reminder() and self.telegram_bot:
                self.telegram_bot.send_text("Get out of Short SPX!!!")
                warn = self.log_hedge_warning(True)
                if warn.long_count > 1:
                    self.cancel_open_orders()
            self.hedge_reminder += 1

        if current_nq_ratio > 1 and any(sym in shorts for sym in ("NQ", "QQQ", "SQQQ")):
            if self.send_reminder() and self.telegram_bot:
                self.telegram_bot.send_text("Get out of Short NDX!!!")
            self.hedge_reminder += 1

        short_symbol: Optional[str] = None
        number_of_contracts = 2
        short_price: Optional[float] = None
        stop_price: Optional[float] = None

        if not shorts:
            if current_nq_ratio < current_es_ratio:
                short_symbol = "NQ"
                number_of_contracts = max(int(round(current_ratio / current_nq_ratio)), 1)
                price = self.ib.get_last_close_price("NQ")
                if price:
                    short_price = price
                    stop_price = price
            else:
                short_symbol = "ES"
                number_of_contracts = max(int(round(current_ratio / current_es_ratio)), 1)
                price = self.ib.get_last_close_price("ES")
                if price:
                    short_price = price
                    stop_price = price

        if not short_symbol:
            return

        # Prompt user with choice if needed
        if self.send_reminder() and self.telegram_bot:
            self.telegram_bot.send_choice(
                "!!!Hedge Required!!!",
                f"Short {number_of_contracts} of {short_symbol}",
                self.chat_response_handler,
            )
            warn = self.log_hedge_warning(False)
            if warn.short_count > 1:
                self.cancel_open_orders()
            self.hedge_reminder = 0

        self.hedge_reminder += 1

        # Await user confirmation
        if self.wait_for_confirmation:
            wait_sec = 0
            while self.chat_response is None and wait_sec < 20:
                time.sleep(10)
                wait_sec += 10
            if self.chat_response == "Delay":
                return
            if self.chat_response == "50%":
                number_of_contracts = max(number_of_contracts // 2, 1)
            if self.chat_response == "Cancel":
                return
            # '100%' means proceed

        # Send execution notice
        if self.telegram_bot:
            self.telegram_bot.send_text(f"Execute hedge of {number_of_contracts} of {short_symbol}")

        # Place the hedge order
        if short_price is not None:
            settings = PositionSettings(
                symbol=short_symbol,
                size=number_of_contracts,
                position_type="Short",
                order_type="Limit",
                limit_price=short_price,
                stop_price=stop_price,
                tag="Hedge",
            )
            try:
                self._order_pacer.pace()
                self.ib.place_order(position_settings=settings)
            except Exception as e:
                logger.warning("Failed to place hedge order: %s", e)

    def chat_response_handler(self, response: str) -> None:
        """Callback for handling chat responses."""
        self.chat_response = response

    def cancel_open_orders(self) -> None:
        """
        Cancel parent open orders:contentReference[oaicite:4]{index=4}.
        """
        try:
            orders = self.ib.get_open_orders()
            for order in orders:
                order_data = order.get("order") or order
                parent_id = order_data.get("parentId") or order_data.get("parent_id") or 0
                if parent_id == 0:
                    try:
                        order_id = order_data.get("orderId") or order_data.get("order_id")
                        if order_id:
                            self.ib.cancel_order(order_id)
                            logger.info(
                                "Cancelled order %s for %s",
                                order_id,
                                (order.get("contract") or {}).get("symbol"),
                            )
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Failed to cancel open orders: %s", e)

    def get_positions_with_stops(self) -> List[Dict[str, Any]]:
        """
        Return positions that have a stop or MOC order:contentReference[oaicite:5]{index=5}.
        """
        positions_with_stops: List[Dict[str, Any]] = []
        try:
            orders = self.ib.get_open_orders()
            positions = self.ib.get_positions()
            for order in orders:
                order_data = order.get("order") or order
                otype = order_data.get("orderType") or order_data.get("type")
                if otype in ("MOC", "STP", "STOP"):
                    ticker = (order.get("contract") or {}).get("symbol") or order.get("ticker")
                    for pos in positions:
                        if (pos.get("ticker") or pos.get("symbol")) == ticker:
                            positions_with_stops.append(pos)
                            break
        except Exception as e:
            logger.warning("Failed to compute positions with stops: %s", e)
        return positions_with_stops
