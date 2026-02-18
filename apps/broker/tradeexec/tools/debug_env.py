"""
debug_env.py

Small utility to report how TradeExec settings are loaded and which accounts
are visible to the runtime. Helps diagnose "account not found" errors.

Run:
    uv run -m tradeexec.tools.debug_env
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from tradeexec.settings import AccountConfig, settings
from tradeexec.utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def mask(s: str, show: int = 4) -> str:
    if not s:
        return ""
    if len(s) <= show:
        return "*" * len(s)
    return s[:show] + "…" + "*" * (len(s) - show - 1)


def list_env_candidates() -> List[str]:
    keys = []
    for k in sorted(os.environ.keys()):
        if k.startswith("ACCOUNT") and any(
            x in k
            for x in ["ACCOUNT_NUMBER", "BROKER_OAUTH_CONSUMER_KEY", "BROKER_OAUTH_ACCESS_TOKEN"]
        ):
            keys.append(k)
    return keys


def main() -> int:
    logger.info("TradeExec Settings Debug")

    # Resolve .env path from settings
    env_path = getattr(settings, "_env_file_path", None)
    exists = Path(env_path).exists() if env_path else False
    logger.info(".env path: %s exists=%s", env_path, exists)

    # Report detected accounts
    accounts: List[AccountConfig] = getattr(settings, "accounts", [])
    logger.info("Loaded accounts: %d", len(accounts))
    for i, acc in enumerate(accounts, start=1):
        logger.info("[%d] account_number=%s", i, acc.account_number)
        # Minimal auth presence check (masked)
        ck = mask(acc.broker_oauth_consumer_key)
        at = mask(acc.broker_oauth_access_token)
        logger.info("    broker.consumer_key=%s", ck)
        logger.info("    broker.access_token=%s", at)

    # Show relevant environment keys present
    env_keys = list_env_candidates()
    if env_keys:
        logger.info("Environment candidates:")
        for k in env_keys:
            v = os.getenv(k, "")
            if "ACCOUNT_NUMBER" in k:
                logger.info("  %s=%s", k, v)
            else:
                logger.info("  %s=%s", k, mask(v))
    else:
        logger.info("No ACCOUNT{N}_* variables detected in process environment.")

    # No legacy single-account env supported
    return 0


if __name__ == "__main__":
    setup_logging(simple=True)
    raise SystemExit(main())
