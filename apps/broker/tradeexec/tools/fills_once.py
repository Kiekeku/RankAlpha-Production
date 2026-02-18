"""
fills_once.py

CLI utility to ingest recent IBKR fills once and exit.

Usage:
  uv run -m tradeexec.tools.fills_once <ACCOUNT_NUMBER> [--since 900]
"""

from __future__ import annotations

import argparse
import logging

from tradeexec.core.ib import IBInterfacing
from tradeexec.order.fills_ingestor import FillsIngestor
from tradeexec.settings import settings
from tradeexec.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest recent IBKR fills once and exit")
    ap.add_argument("account", help="IB account number, e.g., DU-changeme")
    ap.add_argument("--since", type=int, default=900, help="Lookback seconds (default 900)")
    args = ap.parse_args()

    acc = settings.get_account_config(args.account)
    if not acc:
        logger.error("Account %s not found in configuration", args.account)
        return 2

    ib = IBInterfacing(
        account_id=acc.account_number,
        oauth_params=acc.get_broker_oauth_params(),
        use_global_settings=False,
    )
    ing = FillsIngestor(ib, acc.account_number)
    try:
        n = ing.ingest_once(lookback_seconds=int(max(args.since, 0)))
        logger.info("Ingested %s fill(s) for %s", n, acc.account_number)
        return 0
    except Exception as e:
        logger.error("Fills ingest failed: %s", e)
        return 1


if __name__ == "__main__":
    setup_logging(simple=True)
    raise SystemExit(main())
