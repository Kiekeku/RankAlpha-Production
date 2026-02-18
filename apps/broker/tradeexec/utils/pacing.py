"""Lightweight helpers to pace IBKR order submissions."""

from __future__ import annotations

import os
import threading
import time
from typing import Optional


def _coerce_seconds(value: Optional[float], default: float) -> float:
    if value is None:
        return max(default, 0.0)
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return max(default, 0.0)


_DEFAULT_ORDER_PACE_SECONDS = _coerce_seconds(os.getenv("BROKER_ORDER_PACE_SECONDS"), 5.0)


class OrderPacer:
    """Serialize order placement so we respect IBKR per-order rate limits."""

    def __init__(self, seconds: Optional[float] = None) -> None:
        self.seconds = _coerce_seconds(seconds, _DEFAULT_ORDER_PACE_SECONDS)
        self._lock = threading.Lock()
        self._last_submit = 0.0

    def pace(self) -> None:
        """Sleep as needed so consecutive calls are spaced by ``seconds``."""
        if self.seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self.seconds - (now - self._last_submit)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last_submit = now


def make_order_pacer(seconds: Optional[float] = None) -> OrderPacer:
    return OrderPacer(seconds)
