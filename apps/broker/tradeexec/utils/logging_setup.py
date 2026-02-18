"""
Lightweight, centralized logging configuration for the TradeExec project.

Call `setup_logging()` once at process start (e.g., in the runner) to
configure root logging if not already configured by the host application.
Level is controlled by the `LOG_LEVEL` environment variable (default: INFO).
"""

from __future__ import annotations

import logging
import os
from typing import Optional


def setup_logging(level: Optional[str] = None, *, simple: bool = False) -> None:
    """Configure root logging with a sensible default format.

    Does nothing if logging already has handlers (so consumers can override).

    Args:
        level: Optional logging level name. If None, uses `LOG_LEVEL` env var or INFO.
        simple: If True, use a compact console format (for CLI tools).
    """
    root = logging.getLogger()
    if root.handlers:
        return

    level_name = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    fmt = (
        "%(levelname)s | %(message)s"
        if simple
        else "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(numeric_level)
