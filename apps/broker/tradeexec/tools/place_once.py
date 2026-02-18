"""
place_once.py

Run a single DB-driven trade placement cycle for a specific account and exit.

Usage:
    uv run -m tradeexec.tools.place_once <ACCOUNT_NUMBER>

This performs the same DB -> IB order placement as the main runner's loop,
but only once, making it easier to test database connectivity and sizing.
"""

from __future__ import annotations

import logging
import sys

from tradeexec.order.place_transaction import PlaceTransaction
from tradeexec.risk.portfolio_management import PortfolioManagement
from tradeexec.settings import settings
from tradeexec.trade_execution import ExecutionProgram
from tradeexec.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    if len(sys.argv) <= 1:
        logger.error("Usage: uv run -m tradeexec.tools.place_once <ACCOUNT_NUMBER>")
        return 2

    account_number = sys.argv[1]
    account_config = settings.get_account_config(account_number)
    if not account_config:
        logger.error("Account %s not found in configuration", account_number)
        return 1

    # Echo enabled systems for this account
    try:
        systems = [ts.name for ts in (account_config.trading_systems or [])]
        print(
            f"Account {account_config.account_number} enabled systems: "
            + (", ".join(systems) if systems else "(none)")
        )
    except Exception:
        print(f"Account {account_config.account_number} enabled systems: (unknown)")

    # No audit table required; idempotence uses fact_trade_recommendation per account

    program = ExecutionProgram(account_config, settings)
    try:
        program.connect()
    except Exception as e:
        logger.error("Failed to connect to IB: %s", e)
        return 1

    if not program.broker_ib:
        logger.error("Broker IB connection not established")
        return 1

    # Optional: initialise portfolio management for parity (not used here)
    program.portfolio_management = PortfolioManagement(
        ib=program.broker_ib,
        hedge_threshold=program.hedge_threshold,
        telegram_bot=program.telegram_bot,
        wait_for_confirmation=program.wait_for_confirmation,
        order_pacer=program.order_pacer,
    )

    # Run a single placement cycle
    allowed_systems = [ts.name for ts in (account_config.trading_systems or [])]
    placer = PlaceTransaction(
        ib_interface=program.broker_ib,
        account_number=program.account_number,
        allowed_systems=allowed_systems,
        order_pacer=program.order_pacer,
    )

    try:
        if not program.execute_order:
            logger.info("execute_order=False — skipping placement (no-op)")
            return 0
        placer.execute()
        logger.info("Placement cycle complete.")
        return 0
    except Exception as e:
        logger.exception("Placement cycle failed: %s", e)
        return 1


if __name__ == "__main__":
    setup_logging(simple=True)
    raise SystemExit(main())
