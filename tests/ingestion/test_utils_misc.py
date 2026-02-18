from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from apps.ingestion.src import utils


def test_normalize_parquet_columns_flattens_multiindex_and_dedupes():
    cols = pd.MultiIndex.from_tuples(
        [
            ("Adj Close", ""),
            ("Adj Close", ""),
            ("Foo", "Bar"),
            ("", ""),
        ]
    )
    df = pd.DataFrame([[1, 2, 3, 4]], columns=cols)
    out = utils.normalize_parquet_columns(df)
    assert list(out.columns) == ["Adj Close", "Adj Close__1", "Foo_Bar", "col"]


def test_to_naive_ts_and_index_strip_timezone():
    ts = pd.Timestamp("2025-01-01", tz="UTC")
    out = utils.to_naive_ts(ts)
    assert out.tz is None

    idx = pd.DatetimeIndex([ts])
    out_idx = utils.to_naive_index(idx)
    assert getattr(out_idx, "tz", None) is None


def test_round4_handles_nan_and_rounds():
    assert utils.round4(1.23456) == 1.2346
    assert utils.round4(None) is None
    assert utils.round4(float("nan")) is None


def test_history_days_reads_setting_or_default():
    s_ok = SimpleNamespace(ingestion_history_days="123")
    assert utils.history_days(s_ok, default=760) == 123

    s_bad = SimpleNamespace(ingestion_history_days="not-an-int")
    assert utils.history_days(s_bad, default=760) == 760

