from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from apps.scorer.src.services.prices import PriceReader


def test_read_price_parquet_uses_date_column_from_full_read(monkeypatch):
    df_min = pd.DataFrame({"Close": [10.0, 11.0]})
    df_full = pd.DataFrame(
        {
            "Date": ["2025-01-01", "2025-01-02"],
            "Close": [10.0, 11.0],
            "Open": [9.5, 10.5],
        }
    )

    def _fake_read_parquet(path, engine="pyarrow", columns=None):  # type: ignore[no-untyped-def]
        assert path == "dummy.parquet"
        if columns is None:
            return df_full.copy()
        return df_min.copy()

    monkeypatch.setattr("apps.scorer.src.services.prices.pd.read_parquet", _fake_read_parquet)

    out = PriceReader.read_price_parquet("dummy.parquet", logger=SimpleNamespace())

    assert isinstance(out.index, pd.DatetimeIndex)
    assert list(out.index) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")]


def test_read_price_parquet_does_not_epochize_numeric_index(monkeypatch):
    df_min = pd.DataFrame({"Close": [10.0, 11.0]})
    df_full = pd.DataFrame({"Close": [10.0, 11.0]})

    def _fake_read_parquet(path, engine="pyarrow", columns=None):  # type: ignore[no-untyped-def]
        assert path == "dummy.parquet"
        if columns is None:
            return df_full.copy()
        return df_min.copy()

    monkeypatch.setattr("apps.scorer.src.services.prices.pd.read_parquet", _fake_read_parquet)

    out = PriceReader.read_price_parquet("dummy.parquet", logger=SimpleNamespace())

    assert not isinstance(out.index, pd.DatetimeIndex)
    assert list(out.index) == [0, 1]
