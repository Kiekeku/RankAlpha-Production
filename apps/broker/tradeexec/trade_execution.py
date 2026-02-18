"""
execution_program.py

A rough port of C# ExecutionProgram.cs from RightEdgePlugIns to Python 3.12.
Uses the IBKR **Client Portal (Web) API** via `tradeexec.core.ib` (ibind). Handles
account‑based configuration, connection management, portfolio reporting and
hedging triggers.

© 2025 ACC.  Python 3.12
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from tradeexec.core.ib import IBInterfacing
from tradeexec.events import RealTimeSignal, SignalBus
from tradeexec.metrics import (
    Timer,
    observe_executor_cycle_seconds,
    prime_executor_cycle_metrics,
    record_executor_cycle,
)
from tradeexec.order.fills_ingestor import FillsIngestor
from tradeexec.order.place_transaction import PlaceTransaction, PositionSettings
from tradeexec.order.reconcile_positions import ReconcilePosition
from tradeexec.risk.portfolio_management import PortfolioManagement
from tradeexec.settings import AccountConfig
from tradeexec.utils.pacing import OrderPacer, make_order_pacer
from tradeexec.utils.sentry_quiet import is_broker_sentry_quiet_hours, is_ibkr_maintenance_error

if TYPE_CHECKING:
    from tradeexec.comms.telegram import TelegramCommunicator

logger = logging.getLogger(__name__)


def _log_broker_exception(message: str, exc: BaseException) -> None:
    if is_broker_sentry_quiet_hours() and is_ibkr_maintenance_error(exc):
        logger.warning("%s (maintenance window): %s", message, exc)
    else:
        logger.error("%s: %s", message, exc)


class ExecutionProgram:
    """
    A Python port of the C# ExecutionProgram that supports multiple IB connections.

    Supports separate OAuth configurations for broker (order execution) and
    market data connections. This allows using different accounts for placing
    orders vs. receiving market data.
    """

    def __init__(self, account_config: AccountConfig, settings_module=None):
        """
        Initialize the execution program.

        Args:
            account_config: Either an AccountConfig object or account number string
            settings_module: Settings module (for backward compatibility)
        """
        self.account_config = account_config

        self.account_number = self.account_config.account_number
        self.settings = settings_module

        self.broker_ib: Optional[IBInterfacing] = None  # for order execution
        self.market_ib: Optional[IBInterfacing] = None  # for market data
        self.account_values: Dict[str, float] = {}
        self.current_positions: List[Dict[str, Any]] = []
        self.market_data_cache: Dict[str, Dict[str, Any]] = {}
        self.telegram_bot: Optional["TelegramCommunicator"] = (
            None  # assign your TelegramCommunicator if needed
        )
        self.is_running: bool = False
        self.last_tick: Optional[datetime] = None
        self._account_values_logged: bool = False
        self._positions_logged: bool = False

        # Use account-specific configuration
        self.execute_order = self.account_config.execute_order
        self.use_snapshot = self.account_config.use_snapshot
        self.wait_for_confirmation = self.account_config.wait_for_confirmation
        self.hedge_threshold = self.account_config.hedge_threshold
        self.close_unaccounted_positions = self.account_config.close_unaccounted_positions
        self.optimize_price = self.account_config.optimize_price

        # Trading systems from account config
        self.trading_system_settings = self.account_config.trading_systems

        # Initialize portfolio management later after IB connection is established
        self.portfolio_management: Optional[PortfolioManagement] = None
        # Order placement helper (DB -> IB orders)
        self.transaction_placer: Optional[PlaceTransaction] = None
        # Fills ingestor (executions -> ledger)
        self.fills_ingestor: Optional[FillsIngestor] = None

        self._signal_queue: Optional[asyncio.Queue[RealTimeSignal]] = None  # for real-time signals
        self._order_pacer: OrderPacer = make_order_pacer()

    async def attach_signal_bus(self, bus: SignalBus) -> None:
        """Subscribe to the per‑account real‑time signal queue."""
        self._signal_queue = await bus.subscribe(self.account_number)

    @property
    def order_pacer(self) -> OrderPacer:
        return self._order_pacer

    def connect(self):
        """
        Connect to IB with separate broker and market data connections.
        Supports different OAuth configurations for each connection.
        """
        logger.info("Connecting to IB for account %s", self.account_number)

        # Connect broker IB (for orders)
        broker_oauth = self.account_config.get_broker_oauth_params()
        logger.info(
            "Connecting broker IB with OAuth consumer key: %s",
            broker_oauth.get("consumer_key", "")[:10] + "...",
        )

        self.broker_ib = IBInterfacing(
            account_id=self.account_number, oauth_params=broker_oauth, use_global_settings=False
        )

        # Connect market IB (for market data)
        market_oauth = self.account_config.get_market_oauth_params()

        # Check if market OAuth is different from broker OAuth
        if market_oauth.get("consumer_key") != broker_oauth.get("consumer_key") or market_oauth.get(
            "access_token"
        ) != broker_oauth.get("access_token"):
            logger.info(
                "Connecting separate market IB with OAuth consumer key: %s",
                market_oauth.get("consumer_key", "")[:10] + "...",
            )
            self.market_ib = IBInterfacing(
                account_id=self.account_number,  # Can be different account if needed
                oauth_params=market_oauth,
                use_global_settings=False,
            )
        else:
            logger.info("Using same connection for market data")
            self.market_ib = self.broker_ib

        logger.info("Connected to IB account: %s", self.account_number)

    # ------------ Account and Position Helpers ------------

    def retrieve_account_values(self) -> Dict[str, float]:
        """
        Populate self.account_values with the account summary.
        """
        try:
            if not self.broker_ib:
                logger.error("Broker IB not connected")
                return {}
            summary = self.broker_ib.get_account_summary()
            vals: Dict[str, float] = {}

            # IBInterfacing returns nested dict by currency
            for currency, data in summary.items():
                if isinstance(data, dict):
                    for key, value in data.items():
                        try:
                            vals[f"{key}_{currency}"] = float(value)
                        except (TypeError, ValueError):
                            vals[f"{key}_{currency}"] = value

            self.account_values = vals
            if not self._account_values_logged:
                logger.info("Account %s values: %s", self.account_number, vals)
                self._account_values_logged = True
            else:
                logger.debug("Account %s values refreshed", self.account_number)
            return vals
        except Exception as e:
            _log_broker_exception("Failed to retrieve account values", e)
            return {}

    def get_current_positions(self, refresh: bool = False):
        """
        Retrieve open positions from the broker session.
        """
        if not self.current_positions or refresh:
            try:
                if not self.broker_ib:
                    logger.error("Broker IB not connected")
                    self.current_positions = []
                    return self.current_positions
                positions = self.broker_ib.get_positions()
                # Filter out zero positions
                self.current_positions = [
                    pos for pos in positions if (pos.get("position") or pos.get("pos", 0)) != 0
                ]
            except Exception as e:
                _log_broker_exception("Failed to get positions", e)
                self.current_positions = []
        return self.current_positions

    def _log_positions_once(self) -> None:
        if self._positions_logged:
            return
        positions = self.get_current_positions(refresh=True)
        if not positions:
            logger.info("Account %s portfolio is empty", self.account_number)
        else:
            logger.info("Account %s portfolio (%d positions):", self.account_number, len(positions))
            for pos in positions:
                try:
                    logger.info(
                        "  %s %s @ %.2f size=%s unrealized=%s",
                        pos.get("position"),
                        pos.get("symbol"),
                        float(pos.get("avgCost")) if pos.get("avgCost") is not None else 0.0,
                        pos.get("position"),
                        pos.get("unrealizedPNL"),
                    )
                except Exception:
                    logger.info("  %s", pos)
        self._positions_logged = True

    def get_market_data(
        self, symbol: str, exchange: str = "SMART", refresh: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Request market data for a ticker/exchange combination, with caching.
        """
        key = f"{symbol}:{exchange}"
        if not refresh and key in self.market_data_cache:
            return self.market_data_cache[key]

        try:
            if not self.market_ib:
                logger.error("Market IB not connected")
                return None
            # IBInterfacing uses get_market_data for quotes
            quote: Dict[str, Any] = self.market_ib.get_market_data(symbol=symbol)
            if quote:
                self.market_data_cache[key] = quote
                return quote
        except Exception as e:
            _log_broker_exception(f"Failed to get market data for {symbol}", e)

        return None

    # ------------ Order Helpers ------------

    def place_order(
        self, position: PositionSettings, last_price: Optional[float] = None
    ) -> List[int]:
        """
        Submit an order via the broker session using IBInterfacing.
        """
        if not self.execute_order:
            return []

        try:
            # IBInterfacing.place_order accepts position_settings directly
            if not self.broker_ib:
                logger.error("Broker IB not connected")
                return []
            self._order_pacer.pace()
            order_resp = self.broker_ib.place_order(
                position_settings=position, price_hint=last_price
            )
            # IBInterfacing.place_order returns List[int] (order ids) or [0]
            if isinstance(order_resp, list):
                # Ensure all items are ints
                ids: List[int] = []
                for oid in order_resp:
                    try:
                        ids.append(int(oid))
                    except (TypeError, ValueError):
                        continue
                return ids
            # Fallback: try to coerce a single id
            try:
                return [int(order_resp)]
            except Exception:
                logger.warning("Could not extract order ID list from response: %s", order_resp)
                return []
        except Exception as e:
            _log_broker_exception("Failed to place order", e)
            return []

    def cancel_order(self, order_id: int):
        """
        Cancel an order using IBInterfacing.
        """
        if order_id:
            try:
                if self.broker_ib:
                    self.broker_ib.cancel_order(order_id)
                else:
                    logger.error("Broker IB not connected")
                logger.info("Cancelled order %s", order_id)
            except Exception as e:
                _log_broker_exception(f"Failed to cancel order {order_id}", e)

    # ------------ Main Run Loop ------------

    async def run(self):
        """
        High‑level run loop analogous to the C# Main method:contentReference[oaicite:6]{index=6}.
        Executes hedging, logs account values, processes trades (simplified),
        and exits when the market is closed.
        """
        self.is_running = True
        # `connect()` performs synchronous network I/O (OAuth/session init). Run it off the event loop
        # so the FastAPI control-plane remains responsive.
        await asyncio.to_thread(self.connect)
        prime_executor_cycle_metrics(account=self.account_number)

        # Initialize portfolio management after connection
        if self.broker_ib:
            self.portfolio_management = PortfolioManagement(
                ib=self.broker_ib,
                hedge_threshold=self.hedge_threshold,
                telegram_bot=self.telegram_bot,
                wait_for_confirmation=self.wait_for_confirmation,
                order_pacer=self.order_pacer,
            )
            # Initialize transaction placer for DB‑driven trades
            # Restrict to this account's configured trading systems
            allowed_systems = (
                [ts.name for ts in self.trading_system_settings]
                if self.trading_system_settings
                else []
            )
            self.transaction_placer = PlaceTransaction(
                ib_interface=self.broker_ib,
                account_number=self.account_number,
                allowed_systems=allowed_systems,
                optimize_price=self.optimize_price,
                wait_for_confirmation=self.wait_for_confirmation,
                telegram_bot=self.telegram_bot,
                order_pacer=self.order_pacer,
            )
        else:
            logger.error("Cannot initialize portfolio management without broker connection")

        await asyncio.to_thread(self.retrieve_account_values)
        await asyncio.to_thread(self._log_positions_once)
        # Prepare fills ingestor
        if self.broker_ib:
            self.fills_ingestor = FillsIngestor(self.broker_ib, self.account_number)

        # hedging loop (run until market close)
        while self._within_market_hours():
            cycle_timer = Timer()
            cycle_had_error = False
            # refresh Telegram messages if necessary, process manual overrides, etc.
            # fetch pending transactions from DB and process trades
            if self.transaction_placer and self.execute_order:
                try:
                    await asyncio.to_thread(self.transaction_placer.execute)
                except Exception as e:
                    cycle_had_error = True
                    logger.error("Trade placement cycle failed: %s", e)
            elif not self.execute_order:
                logger.debug("Execute order flag disabled; skipping DB trade execution")

                # optionally reconcile positions to close out IB holdings not in the system
            if self.close_unaccounted_positions and self.broker_ib and self.trading_system_settings:
                prefixes = [ts.name for ts in self.trading_system_settings]
                reconciler = ReconcilePosition(
                    ib_interface=self.broker_ib,
                    program_name=self.account_config.program_name,
                    system_prefixes=prefixes,
                    account_number=self.account_number,
                    close_unaccounted_positions=True,
                )
                exit_txs = await asyncio.to_thread(reconciler.reconcile)
                # If any exit transactions were generated, you could place them via
                # transaction_placer.
                for tx in exit_txs:
                    pos_settings = PositionSettings(
                        symbol=tx.Ticker,
                        position_type="Short" if tx.TradeType == "Sell" else "Long",
                        size=abs(tx.Size or 0),
                        order_type="MarketOnClose",
                        custom_string=str(tx.ID),
                        tag="Reconcile",
                    )
                    await asyncio.to_thread(self.place_order, pos_settings)

            # update account values and run hedge logic
            await asyncio.to_thread(self.retrieve_account_values)
            if self.portfolio_management:
                await asyncio.to_thread(self.portfolio_management.run_hedge)

            # Ingest any recent fills into the shared ledger (idempotent)
            try:
                if self.fills_ingestor:
                    await asyncio.to_thread(self.fills_ingestor.ingest_once, lookback_seconds=900)
            except Exception as e:
                cycle_had_error = True
                logger.debug("Fills ingest skipped: %s", e)

            # maintain open positions; cancel stale orders (omitted)
            self.last_tick = datetime.now()
            observe_executor_cycle_seconds(
                account=self.account_number,
                seconds=cycle_timer.seconds(),
            )
            record_executor_cycle(
                account=self.account_number,
                outcome="error" if cycle_had_error else "success",
            )
            await asyncio.sleep(60)  # wait 1 minute between cycles

        logger.info("Market closed. Exiting execution loop.")
        self.is_running = False

    def _within_market_hours(self) -> bool:
        """
        Check if current time in the configured market timezone is within
        MARKET_OPEN_TIME .. MARKET_CLOSE_TIME and today is a trading day.

        - Uses the IANA timezone from settings.market_timezone (default America/New_York).
        - Daylight Saving Time is handled automatically by zoneinfo.
        """
        tzname = (
            getattr(self.settings, "market_timezone", "America/New_York")
            if self.settings
            else "America/New_York"
        )
        try:
            now_dt = datetime.now(ZoneInfo(tzname))
        except Exception:
            # Fallback to naive local time if timezone not available
            now_dt = datetime.now()
        now = now_dt.time()
        market_open = (
            getattr(self.settings, "market_open_time", time(9, 30))
            if self.settings
            else time(9, 30)
        )
        market_close = (
            getattr(self.settings, "market_close_time", time(16, 0))
            if self.settings
            else time(16, 0)
        )
        # Holiday / early close check on the market-local calendar date
        try:
            from tradeexec.utils.market_calendar import _effective_close_time, is_trading_day

            if not is_trading_day(now_dt.date()):
                return False
            session_close = _effective_close_time(now_dt.date(), market_open, market_close)
            return market_open <= now <= session_close
        except Exception:
            return market_open <= now <= market_close

    async def _signal_loop(self) -> None:
        if not self._signal_queue:
            return
        while True:
            sig: RealTimeSignal = await self._signal_queue.get()
            try:
                await self.handle_signal(sig)
            except Exception as e:
                logger.exception("Signal handling error (%s): %s", sig, e)

    async def handle_signal(self, sig: RealTimeSignal) -> None:
        """Convert a RealTimeSignal into a PositionSettings and place it now."""
        if not self.broker_ib:
            logger.error("Broker IB not connected; dropping %s", sig)
            return

        # System whitelist for real-time signals (relaxed via settings toggles)
        allowed = [ts.name for ts in (self.trading_system_settings or [])]
        allow_fallback = bool(getattr(self.settings, "allow_realtime_without_system", False))
        rt_name = getattr(self.settings, "realtime_system_name", "real-time")

        def _is_allowed_system(tag: Optional[str]) -> bool:
            if not allowed:
                return allow_fallback
            if tag and tag in allowed:
                return True
            if tag and rt_name and tag == rt_name and rt_name in allowed:
                return True
            return allow_fallback

        if not _is_allowed_system(getattr(sig, "system", None)):
            logger.warning(
                "Real-time signal rejected (account=%s, system=%s, allowed=%s, fallback=%s)",
                self.account_number,
                sig.system,
                ",".join(allowed) if allowed else "(none)",
                allow_fallback,
            )
            return

        # Determine side/size
        side = "Long" if sig.action.lower() == "buy" else "Short"
        size = sig.quantity

        # handle 'exit' by sizing to the open IB position
        if sig.action.lower() == "exit":
            positions = await asyncio.to_thread(self.get_current_positions, True)
            pos = next(
                (p for p in positions if (p.get("ticker") or p.get("symbol")) == sig.symbol),
                None,
            )
            if not pos:
                logger.warning("Exit for %s but no IB position; skipping", sig.symbol)
                return
            ib_size = int(pos.get("position") or pos.get("pos") or 0)
            if ib_size == 0:
                logger.warning("Exit for %s but position size=0; skipping", sig.symbol)
                return
            size = abs(ib_size)
            side = "Long" if ib_size < 0 else "Short"

        if not size or size <= 0:
            # Fallback: naïve 100% cash sizing at last price (fast and serviceable)
            try:
                quote = await asyncio.to_thread(self.broker_ib.get_market_data, symbol=sig.symbol)
                px = quote.get("last") or quote.get("31") or quote.get("close") or quote.get("86")
                px = float(px) if px else 0.0
                if px > 0:
                    cash = max(await asyncio.to_thread(self.broker_ib.get_available_fund), 0.0)
                    size = max(int(cash // px), 1)
                else:
                    logger.warning("Cannot infer price for sizing %s; dropping", sig.symbol)
                    return
            except Exception as e:
                logger.warning("Sizing failed for %s: %s", sig.symbol, e)
                return

        order_type = sig.order_type.upper()
        from tradeexec.order.place_transaction import PositionSettings

        ps = PositionSettings(
            symbol=sig.symbol,
            size=size,
            position_type=side,
            order_type={"MKT": "Market", "LMT": "Limit", "STP": "Stop", "MOC": "MarketOnClose"}.get(
                order_type, "Market"
            ),
            limit_price=sig.limit_price,
            stop_price=sig.stop_price,
            tag=sig.tag or (sig.system or ""),
            custom_string=sig.custom_string or f"RT:{sig.action}",
        )
        self.place_order(ps)

    # --- NEW: forever supervisor that restarts the normal run() loop ---
    async def run_supervised(self, bus: Optional[SignalBus] = None) -> None:
        """Run forever: attach bus, consume signals in background, restart run() on errors."""
        if bus:
            await self.attach_signal_bus(bus)
            asyncio.create_task(self._signal_loop())
        while True:
            try:
                await self.run()
            except Exception as e:
                if is_broker_sentry_quiet_hours() and is_ibkr_maintenance_error(e):
                    logger.warning("run() crashed during quiet hours: %s", e)
                else:
                    logger.exception("run() crashed: %s", e)
            # Sleep a bit whether market closed or error, then re‑enter
            await asyncio.sleep(30)


if __name__ == "__main__":
    """
    Example usage with multiple account support:
        from tradeexec.trade_execution import ExecutionProgram
        from tradeexec.settings import settings
        
        # Option 1: Use first configured account
        if settings.accounts:
            account_config = settings.accounts[0]
            program = ExecutionProgram(account_config, settings)
            asyncio.run(program.run())
            
        # Option 2: Use specific account by number
        account_config = settings.get_account_config("DU-changeme")
        if account_config:
            program = ExecutionProgram(account_config, settings)
            asyncio.run(program.run())
    """
    # Delay import of settings to avoid circular imports
    import sys

    from tradeexec.settings import settings
    from tradeexec.utils.logging_setup import setup_logging

    # Configure logging once for the process
    setup_logging()

    # Require explicit account number via CLI argument
    if len(sys.argv) <= 1:
        logger.error(
            "Missing account number. Usage: uv run -m tradeexec.trade_execution <ACCOUNT_NUMBER>"
        )
        sys.exit(1)

    account_number = sys.argv[1]
    account_config = settings.get_account_config(account_number)
    if not account_config:
        logger.error("Account %s not found in configuration", account_number)
        sys.exit(1)

    # No audit table is required; idempotence uses fact_trade_recommendation per account

    # Echo enabled trading systems for visibility
    try:
        systems = [ts.name for ts in (account_config.trading_systems or [])]
        logger.info(
            "Account %s enabled systems: %s",
            account_config.account_number,
            ", ".join(systems) if systems else "(none)",
        )
    except Exception:
        logger.info("Account %s enabled systems: (unknown)", account_config.account_number)

    program = ExecutionProgram(account_config, settings)

    # Lightweight health server for runner-only containers
    def _start_health_server(_program: ExecutionProgram) -> None:
        port = int(os.getenv("BROKER_RUNNER_HEALTH_PORT", "8795"))

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/health"):
                    payload = {
                        "account": _program.account_number,
                        "executing": bool(_program.is_running),
                        "last_tick": _program.last_tick.isoformat() if _program.last_tick else None,
                    }
                    body = json.dumps(payload).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/metrics":
                    try:
                        from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
                    except Exception:
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = generate_latest(REGISTRY)
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_response(404)
                self.end_headers()
                return

            def log_message(self, fmt, *args):
                return

        try:
            server = HTTPServer(("0.0.0.0", port), _Handler)
            t = threading.Thread(target=server.serve_forever, daemon=True)
            t.start()
            logger.info("Runner health server listening on :%s", port)
        except Exception as e:
            logger.debug("Health server not started: %s", e)

    _start_health_server(program)

    asyncio.run(program.run())
