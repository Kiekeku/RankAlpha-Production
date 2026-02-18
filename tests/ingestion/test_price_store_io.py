from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest
from apps.ingestion.src.price_store import PriceStore


def test_price_store_load_returns_none_when_missing(tmp_path):
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=10)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()
    assert store.load("AAPL") is None


def test_price_store_load_returns_none_on_read_error(tmp_path, monkeypatch):
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=10)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()

    # Create a placeholder path so load() attempts to read.
    (tmp_path / "AAPL.parquet").write_bytes(b"not-a-parquet")

    def _boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr("apps.ingestion.src.price_store.pd.read_parquet", _boom)
    assert store.load("AAPL") is None


def test_price_store_save_trims_history_days_and_loads_back(tmp_path):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=3)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()

    idx = pd.date_range("2025-01-01", periods=10, freq="D")
    df = pd.DataFrame(
        {
            "Open": range(10),
            "High": range(10),
            "Low": range(10),
            "Close": range(10),
            "Adj Close": range(10),
            "Volume": [100] * 10,
        },
        index=idx,
    )
    store.save("AAPL", df)
    out = store.load("AAPL")
    assert out is not None
    assert len(out.index) == 3
    assert out.index[0].date() == idx[-3].date()
    assert list(out.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def test_price_store_list_existing_uppercases_stems(tmp_path):
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=10)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()
    (tmp_path / "aapl.parquet").write_text("x", encoding="utf-8")
    (tmp_path / "msft.parquet").write_text("x", encoding="utf-8")
    assert store.list_existing() == {"AAPL", "MSFT"}


def test_price_store_load_auto_repairs_date_column_index(tmp_path):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=10)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()

    legacy = pd.DataFrame(
        {
            "Date": ["2025-01-01", "2025-01-02", "2025-01-03"],
            "Open": [1.0, 2.0, 3.0],
            "High": [1.5, 2.5, 3.5],
            "Low": [0.5, 1.5, 2.5],
            "Close": [1.2, 2.2, 3.2],
            "Adj Close": [1.2, 2.2, 3.2],
            "Volume": [100.0, 120.0, 140.0],
        }
    )
    legacy.to_parquet(tmp_path / "AAPL.parquet", engine="pyarrow")

    out = store.load("AAPL")
    assert out is not None
    assert isinstance(out.index, pd.DatetimeIndex)
    assert "Date" not in out.columns

    on_disk = pd.read_parquet(tmp_path / "AAPL.parquet", engine="pyarrow")
    assert isinstance(on_disk.index, pd.DatetimeIndex)
    assert "Date" not in on_disk.columns
    assert list(on_disk.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


def test_price_store_load_skips_auto_repair_for_canonical_files(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow", reason="pyarrow required for parquet IO")
    settings = SimpleNamespace(ingestion_price_dir=str(tmp_path), ingestion_history_days=10)
    store = PriceStore(settings, logging.getLogger("tests.ingestion.price_store"))
    store.prepare()

    idx = pd.date_range("2025-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0],
            "High": [1.5, 2.5, 3.5],
            "Low": [0.5, 1.5, 2.5],
            "Close": [1.2, 2.2, 3.2],
            "Adj Close": [1.2, 2.2, 3.2],
            "Volume": [100.0, 120.0, 140.0],
        },
        index=idx,
    )
    store.save("AAPL", df)

    called = False

    def _repair_stub(_symbol: str, _path: str):  # type: ignore[no-untyped-def]
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(store, "_repair_file", _repair_stub)
    out = store.load("AAPL")

    assert out is not None
    assert called is False
