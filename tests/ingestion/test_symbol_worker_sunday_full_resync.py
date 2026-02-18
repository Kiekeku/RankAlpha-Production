from __future__ import annotations

import logging

import pandas as pd
import pytest

from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.symbol_worker import SymbolIngestionWorker


class _DummyCounter:
    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self) -> None:
        return None


class _DummyCursor:
    rowcount = 0

    def execute(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
        return None

    def fetchone(self):  # type: ignore[no-untyped-def]
        # Resolve a fake stock_key so the worker reaches PriceSyncService.
        return (123,)

    def fetchall(self):  # type: ignore[no-untyped-def]
        return []

    def close(self) -> None:
        return None


class _DummyConn:
    def cursor(self) -> _DummyCursor:
        return _DummyCursor()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class _DummyBroker:
    def fetch_prev_close(self, _symbol: str):  # type: ignore[no-untyped-def]
        return None, None


class _Settings:
    def __init__(self, price_dir: str) -> None:
        self.ingestion_price_dir = price_dir
        self.ingestion_history_days = 50


def test_symbol_worker_forces_full_resync_on_sunday_et(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    logger = logging.getLogger("tests.ingestion.symbol_worker.sunday_full_resync")
    settings = _Settings(str(tmp_path))
    store = PriceStore(settings, logger)
    store.prepare()

    # Sunday ET run: expected prior trading day is Friday.
    fixed_now = pd.Timestamp("2025-01-05 10:00", tz="America/New_York")
    monkeypatch.setattr(
        "apps.ingestion.src.symbol_worker.pd.Timestamp.now",
        lambda *args, **kwargs: fixed_now,
    )

    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.0, 2.0, 3.0],
            "Low": [1.0, 2.0, 3.0],
            "Close": [1.0, 2.0, 3.0],
            "Adj Close": [1.0, 2.0, 3.0],
            "Volume": [100.0, 100.0, 100.0],
        },
        index=idx,
    )
    store.save("AAPL", df)
    original_load = store.load
    load_calls = {"count": 0}

    def _load_spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        load_calls["count"] += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(store, "load", _load_spy)

    # Avoid tech upserts; we only care about force_full passed to PriceSyncService.
    from apps.common.src import technicals as common_technicals

    monkeypatch.setattr(common_technicals, "compute_technicals", lambda *_a, **_k: {})

    calls: list[bool] = []

    class _DummyPriceSyncService:
        def __init__(self, *_a, **_k) -> None:
            return None

        def sync(self, *_a, force_full: bool = False, **_k) -> None:  # type: ignore[no-untyped-def]
            calls.append(bool(force_full))

    monkeypatch.setattr(
        "apps.ingestion.src.symbol_worker.PriceSyncService", _DummyPriceSyncService
    )

    worker = SymbolIngestionWorker(
        settings,
        store,
        _DummyBroker(),
        db_factory=_DummyConn,
        span=None,
        logger=logger,
        download_failures=_DummyCounter(),
    )

    out = worker.run("AAPL")
    assert out.last_trade_date == idx[-1].date()
    assert calls == [True]
    assert load_calls["count"] == 1
