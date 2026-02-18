from __future__ import annotations

from tradeexec.core import rate_limits


def test_env_parsers_fallback(monkeypatch):
    monkeypatch.setenv("IBKR_GLOBAL_RPS", "not-a-float")
    monkeypatch.setenv("IBKR_HISTORY_MAX_CONCURRENCY", "not-an-int")
    assert rate_limits._env_float("IBKR_GLOBAL_RPS", 12.5) == 12.5
    assert rate_limits._env_int("IBKR_HISTORY_MAX_CONCURRENCY", 7) == 7


def test_token_bucket_does_not_sleep_when_tokens_available(monkeypatch):
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(rate_limits.time, "sleep", fake_sleep)
    bucket = rate_limits._TokenBucket(rate=10.0, burst=2.0)
    bucket.acquire()
    assert slept == []


def test_token_bucket_sleeps_until_refill(monkeypatch):
    now = 0.0
    slept: list[float] = []

    def fake_monotonic() -> float:
        return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        slept.append(seconds)
        now += float(seconds)

    monkeypatch.setattr(rate_limits.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limits.time, "sleep", fake_sleep)

    bucket = rate_limits._TokenBucket(rate=1.0, burst=1.0)
    bucket.acquire()  # consumes the only token
    bucket.acquire()  # must wait ~1s for refill
    assert slept, "expected acquire() to sleep when bucket is empty"
    assert sum(slept) >= 0.5


def test_limiter_registry_replaces_bucket_when_rate_changes(monkeypatch):
    now = 0.0

    def fake_monotonic() -> float:
        return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        now += float(seconds)

    monkeypatch.setattr(rate_limits.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(rate_limits.time, "sleep", fake_sleep)

    rate_limits._LimiterRegistry._buckets = {}
    rate_limits._LimiterRegistry._semaphores = {}

    rate_limits._LimiterRegistry.acquire("acct", "snapshot", rate=5.0, burst=5.0)
    first = rate_limits._LimiterRegistry._buckets[("acct", "snapshot")]

    rate_limits._LimiterRegistry.acquire("acct", "snapshot", rate=1.0, burst=1.0)
    second = rate_limits._LimiterRegistry._buckets[("acct", "snapshot")]

    assert first is not second


def test_limiter_registry_hold_semaphore_yields_and_releases():
    rate_limits._LimiterRegistry._buckets = {}
    rate_limits._LimiterRegistry._semaphores = {}
    with rate_limits._LimiterRegistry.hold_semaphore("acct", "history", max_concurrency=1):
        pass
