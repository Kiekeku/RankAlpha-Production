from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from apps.ingestion.src.symbol_worker import SymbolIngestionWorker


class _DummyCounter:
    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self) -> None:
        return None


class _ExpectedMissingCounter:
    def __init__(self) -> None:
        self.count = 0

    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self) -> None:
        self.count += 1


class _DummyLogger:
    def __init__(self) -> None:
        self.info_logs: list[str] = []
        self.warn_logs: list[str] = []

    def info(self, msg: str, *args) -> None:  # type: ignore[no-untyped-def]
        self.info_logs.append(msg % args if args else msg)

    def warning(self, msg: str, *args) -> None:  # type: ignore[no-untyped-def]
        self.warn_logs.append(msg % args if args else msg)


class _DummyYFinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def download(self, *_args, **_kwargs) -> pd.DataFrame:  # type: ignore[no-untyped-def]
        return self._frame


def _build_worker(*, logger: _DummyLogger, expected_counter: _ExpectedMissingCounter):
    settings = SimpleNamespace(
        ingestion_history_days=10,
        ingestion_yfinance_enabled=True,
        ingestion_yfinance_timeout_seconds=0.2,
        ingestion_yfinance_max_retries=2,
        ingestion_yfinance_retry_backoff_seconds=0.01,
    )
    return SymbolIngestionWorker(
        settings,
        price_store=SimpleNamespace(),
        broker_client=SimpleNamespace(),
        db_factory=lambda: None,
        span=None,
        logger=logger,
        download_failures=_DummyCounter(),
        expected_missing_counter=expected_counter,
    )


def test_download_prices_retries_timeout_then_succeeds(monkeypatch):
    logger = _DummyLogger()
    expected_counter = _ExpectedMissingCounter()
    worker = _build_worker(logger=logger, expected_counter=expected_counter)
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-01-02"]))
    monkeypatch.setitem(sys.modules, "yfinance", _DummyYFinance(frame))

    attempts = {"count": 0}
    sleep_calls: list[tuple[int, float]] = []

    def _exec_with_timeout(fn, *, timeout_seconds):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("boom")
        return fn()

    monkeypatch.setattr(worker, "_execute_with_timeout", _exec_with_timeout)
    monkeypatch.setattr(
        worker,
        "_sleep_before_retry",
        lambda attempt_no, base_seconds: sleep_calls.append((attempt_no, base_seconds)),
    )

    df, missing = worker._download_prices("AAPL", start_date="2025-01-01")

    assert missing is None
    assert df is not None and not df.empty
    assert attempts["count"] == 2
    assert sleep_calls == [(1, 0.01)]
    assert any("timeout" in msg for msg in logger.warn_logs)


def test_download_prices_exhausts_retries_on_timeouts(monkeypatch):
    logger = _DummyLogger()
    expected_counter = _ExpectedMissingCounter()
    worker = _build_worker(logger=logger, expected_counter=expected_counter)
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-01-02"]))
    monkeypatch.setitem(sys.modules, "yfinance", _DummyYFinance(frame))

    worker._settings.ingestion_yfinance_max_retries = 1
    sleep_calls: list[tuple[int, float]] = []

    def _always_timeout(_fn, *, timeout_seconds):  # type: ignore[no-untyped-def]
        raise TimeoutError(f"timed out in {timeout_seconds}")

    monkeypatch.setattr(worker, "_execute_with_timeout", _always_timeout)
    monkeypatch.setattr(
        worker,
        "_sleep_before_retry",
        lambda attempt_no, base_seconds: sleep_calls.append((attempt_no, base_seconds)),
    )

    df, missing = worker._download_prices("AAPL")

    assert df is None
    assert missing is None
    assert sleep_calls == [(1, 0.01)]
    assert any("exhausted retries" in msg for msg in logger.warn_logs)


def test_download_prices_expected_missing_exception_does_not_retry(monkeypatch):
    logger = _DummyLogger()
    expected_counter = _ExpectedMissingCounter()
    worker = _build_worker(logger=logger, expected_counter=expected_counter)
    frame = pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-01-02"]))
    monkeypatch.setitem(sys.modules, "yfinance", _DummyYFinance(frame))

    attempts = {"count": 0}
    sleep_calls: list[tuple[int, float]] = []

    def _delisted(_fn, *, timeout_seconds):  # type: ignore[no-untyped-def]
        attempts["count"] += 1
        raise RuntimeError(f"possibly delisted timeout={timeout_seconds}")

    monkeypatch.setattr(worker, "_execute_with_timeout", _delisted)
    monkeypatch.setattr(
        worker,
        "_sleep_before_retry",
        lambda attempt_no, base_seconds: sleep_calls.append((attempt_no, base_seconds)),
    )

    df, missing = worker._download_prices("DELISTED")

    assert df is None
    assert missing == "not_found"
    assert attempts["count"] == 1
    assert sleep_calls == []
    assert expected_counter.count == 1


def test_execute_with_timeout_does_not_block_after_timeout():
    logger = _DummyLogger()
    expected_counter = _ExpectedMissingCounter()
    worker = _build_worker(logger=logger, expected_counter=expected_counter)

    def _slow_call() -> pd.DataFrame:
        time.sleep(0.5)
        return pd.DataFrame({"Close": [1.0]}, index=pd.to_datetime(["2026-01-02"]))

    started = time.perf_counter()
    with pytest.raises(TimeoutError):
        worker._execute_with_timeout(_slow_call, timeout_seconds=0.05)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.35
