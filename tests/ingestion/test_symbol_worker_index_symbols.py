import logging

import pandas as pd
import pytest

from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.symbol_worker import SymbolIngestionWorker


class _DummyCounter:
    def __init__(self) -> None:
        self.count = 0

    def labels(self, **_kwargs):  # type: ignore[no-untyped-def]
        return self

    def inc(self) -> None:
        self.count += 1


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
    def fetch_prev_close(self, _symbol: str):  # type: ignore[no-untyped-def]
        raise AssertionError("broker prev-close should not be called for index-prefixed symbols")


class _Settings:
    def __init__(self, price_dir: str) -> None:
        self.ingestion_price_dir = price_dir
        self.ingestion_history_days = 50


@pytest.mark.parametrize("symbol", ["$SPX", "%SPX", "#SPX"])
def test_symbol_worker_skips_yfinance_for_index_symbol_when_parquet_missing(
    tmp_path, monkeypatch, symbol
):
    settings = _Settings(str(tmp_path))
    logger = logging.getLogger("tests.ingestion.symbol_worker")
    price_store = PriceStore(settings, logger)
    price_store.prepare()

    worker = SymbolIngestionWorker(
        settings,
        price_store,
        _DummyBroker(),
        db_factory=_DummyConn,
        span=None,
        logger=logger,
        download_failures=_DummyCounter(),
    )

    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("yfinance should not be called for index-prefixed symbols")

    monkeypatch.setattr(worker, "_download_prices", _boom)

    out = worker.run(symbol)
    assert out.symbol == symbol
    assert out.last_trade_date is None


@pytest.mark.parametrize("symbol", ["$SPX", "%SPX", "#SPX"])
def test_symbol_worker_skips_yfinance_for_index_symbol_when_parquet_exists(
    tmp_path, monkeypatch, symbol
):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    settings = _Settings(str(tmp_path))
    logger = logging.getLogger("tests.ingestion.symbol_worker")
    price_store = PriceStore(settings, logger)
    price_store.prepare()

    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "Open": [1, 2, 3, 4, 5],
            "High": [1, 2, 3, 4, 5],
            "Low": [1, 2, 3, 4, 5],
            "Close": [1, 2, 3, 4, 5],
            "Adj Close": [1, 2, 3, 4, 5],
            "Volume": [100, 100, 100, 100, 100],
        },
        index=idx,
    )
    price_store.save(symbol, df)

    worker = SymbolIngestionWorker(
        settings,
        price_store,
        _DummyBroker(),
        db_factory=_DummyConn,
        span=None,
        logger=logger,
        download_failures=_DummyCounter(),
    )

    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("yfinance should not be called for index-prefixed symbols")

    monkeypatch.setattr(worker, "_download_prices", _boom)
    save_calls = {"count": 0}

    def _save_spy(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        save_calls["count"] += 1
        raise AssertionError(
            "price_store.save should not be called for unchanged index-prefixed symbols"
        )

    monkeypatch.setattr(price_store, "save", _save_spy)

    out = worker.run(symbol)
    assert out.symbol == symbol
    assert out.last_trade_date == idx[-1].date()
    assert save_calls["count"] == 0
