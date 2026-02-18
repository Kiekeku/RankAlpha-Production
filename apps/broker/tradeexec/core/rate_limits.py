"""Shared rate-limiting primitives for IBKR REST calls."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, Tuple


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return int(default)


_GLOBAL_RPS = _env_float("IBKR_GLOBAL_RPS", 40.0)
_GLOBAL_BURST = _env_float("IBKR_GLOBAL_BURST", max(1.0, _GLOBAL_RPS))
_SNAPSHOT_RPS = _env_float("IBKR_SNAPSHOT_RPS", 8.0)
_ORDERS_RPS = _env_float("IBKR_ORDERS_RPS", 0.2)
_TRADES_RPS = _env_float("IBKR_TRADES_RPS", _ORDERS_RPS)
_HISTORY_RPS = _env_float("IBKR_HISTORY_RPS", 4.0)
_HISTORY_MAX_CONCURRENCY = _env_int("IBKR_HISTORY_MAX_CONCURRENCY", 5)


class _TokenBucket:
    def __init__(self, rate: float, burst: float | None = None) -> None:
        self.rate = max(rate, 0.0)
        self.capacity = max(burst or rate, 1.0)
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        if self.rate <= 0:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.updated
                if elapsed > 0:
                    refill = elapsed * self.rate
                    self.tokens = min(self.capacity, self.tokens + refill)
                    self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                needed = (1.0 - self.tokens) / self.rate if self.rate > 0 else 0.1
            time.sleep(min(max(needed, 0.01), 0.5))


class _LimiterRegistry:
    _buckets: Dict[Tuple[str, str], _TokenBucket] = {}
    _bucket_lock = threading.Lock()
    _semaphores: Dict[Tuple[str, str], threading.Semaphore] = {}
    _semaphore_lock = threading.Lock()

    @classmethod
    def acquire(cls, key: str, category: str, rate: float, burst: float | None = None) -> None:
        if rate <= 0:
            return
        ident = (key, category)
        bucket = cls._buckets.get(ident)
        target_capacity = max(burst or rate, 1.0)
        if bucket is None or bucket.rate != rate or bucket.capacity != target_capacity:
            with cls._bucket_lock:
                bucket = cls._buckets.get(ident)
                if bucket is None or bucket.rate != rate or bucket.capacity != target_capacity:
                    bucket = _TokenBucket(rate, burst)
                    cls._buckets[ident] = bucket
        bucket.acquire()

    @classmethod
    @contextmanager
    def hold_semaphore(cls, key: str, category: str, max_concurrency: int):
        if max_concurrency <= 0:
            yield
            return
        ident = (key, category)
        sem = cls._semaphores.get(ident)
        if sem is None:
            with cls._semaphore_lock:
                sem = cls._semaphores.get(ident)
                if sem is None:
                    sem = threading.Semaphore(max_concurrency)
                    cls._semaphores[ident] = sem
        sem.acquire()
        try:
            yield
        finally:
            sem.release()


_LIMIT_CONFIG: Dict[str, Dict[str, float]] = {
    "snapshot": {"rate": _SNAPSHOT_RPS, "burst": max(1.0, _SNAPSHOT_RPS)},
    "orders": {"rate": _ORDERS_RPS, "burst": 1.0},
    "trades": {"rate": _TRADES_RPS, "burst": 1.0},
    "history": {"rate": _HISTORY_RPS, "burst": max(1.0, _HISTORY_RPS)},
}


__all__ = [
    "_GLOBAL_RPS",
    "_GLOBAL_BURST",
    "_HISTORY_MAX_CONCURRENCY",
    "_LIMIT_CONFIG",
    "_LimiterRegistry",
]
