from __future__ import annotations

import logging
from datetime import datetime

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
        return None

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
    def __init__(self, ts: pd.Timestamp, px: float) -> None:
        self._ts = ts
        self._px = px
        self.calls: list[str] = []

    def fetch_prev_close(self, symbol: str):  # type: ignore[no-untyped-def]
        self.calls.append(symbol)
        return self._ts, self._px


class _Settings:
    def __init__(self, price_dir: str) -> None:
        self.ingestion_price_dir = price_dir
        self.ingestion_history_days = 50


def test_symbol_worker_appends_broker_prev_close_when_missing_trade_date(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    logger = logging.getLogger("tests.ingestion.symbol_worker")
    settings = _Settings(str(tmp_path))
    store = PriceStore(settings, logger)
    store.prepare()

    # Freeze "now" so end_bound is deterministic (2025-01-03 ET midnight).
    fixed_now = pd.Timestamp("2025-01-03 10:00", tz="America/New_York")
    monkeypatch.setattr(
        "apps.ingestion.src.symbol_worker.pd.Timestamp.now",
        lambda *args, **kwargs: fixed_now,
    )

    existing_idx = pd.date_range("2025-01-01", periods=1, freq="D")
    existing = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [1.0],
            "Low": [1.0],
            "Close": [1.0],
            "Adj Close": [1.0],
            "Volume": [100.0],
        },
        index=existing_idx,
    )
    store.save("AAPL", existing)

    broker_ts = pd.Timestamp(datetime(2025, 1, 2, 16, 0))
    broker = _DummyBroker(broker_ts, 10.0)

    worker = SymbolIngestionWorker(
        settings,
        store,
        broker,
        db_factory=_DummyConn,
        span=None,
        logger=logger,
        download_failures=_DummyCounter(),
    )
    monkeypatch.setattr(worker, "_download_prices", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("download should not be called")))

    out = worker.run("AAPL")
    assert out.last_trade_date == broker_ts.date()

    pdf = store.load("AAPL")
    assert pdf is not None
    assert pdf.index[-1] == broker_ts
    assert float(pdf.loc[broker_ts, "Adj Close"]) == 10.0

