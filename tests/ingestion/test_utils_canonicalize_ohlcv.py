from __future__ import annotations

from datetime import datetime

import pandas as pd
from apps.ingestion.src import utils


def test_normalize_parquet_columns_flattens_multiindex_and_uniquifies():
    cols = pd.MultiIndex.from_tuples(
        [
            ("Open", ""),
            ("Open", "dup"),
            ("Close", None),
        ]
    )
    df = pd.DataFrame([[1, 2, 3]], columns=cols)

    out = utils.normalize_parquet_columns(df)
    assert list(out.columns) == ["Open", "Open__1", "Close"]


def test_canonicalize_ohlcv_makes_datetime_index_unique_sorted_and_tz_naive():
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2025-01-02 16:00", tz="America/New_York"),
            pd.Timestamp("2025-01-01 16:00", tz="America/New_York"),
            pd.Timestamp("2025-01-02 16:00", tz="America/New_York"),
        ]
    )
    df = pd.DataFrame({"Close": [1, 2, 3]}, index=idx)

    out = utils.canonicalize_ohlcv(df)
    assert isinstance(out.index, pd.DatetimeIndex)
    assert out.index.tz is None
    assert list(out.index) == [
        pd.Timestamp("2025-01-01 16:00"),
        pd.Timestamp("2025-01-02 16:00"),
    ]
    assert list(out.columns) == list(utils.CANON_OHLCV_ORDER)
    assert out["Close"].dtype == float


def test_canonicalize_ohlcv_sets_adj_close_when_missing_or_empty():
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    df = pd.DataFrame({"Close": [10.0, 11.0]}, index=idx)
    out = utils.canonicalize_ohlcv(df)
    assert out["Adj Close"].tolist() == [10.0, 11.0]


def test_canonicalize_ohlcv_prefers_date_column_over_range_index():
    df = pd.DataFrame(
        {
            "Date": ["2025-01-01", "2025-01-02"],
            "Close": [10.0, 11.0],
        }
    )
    out = utils.canonicalize_ohlcv(df)
    assert list(out.index) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")]


def test_canonicalize_ohlcv_does_not_epochize_numeric_index_without_date_column():
    df = pd.DataFrame({"Close": [10.0, 11.0, 12.0]})
    out = utils.canonicalize_ohlcv(df)
    assert not isinstance(out.index, pd.DatetimeIndex)
    assert list(out.index) == [0, 1, 2]


def test_canonicalize_ohlcv_accepts_pandas_index_column_name():
    # pyarrow tail-reads may return the pandas index column name as a regular column
    # when pandas metadata is missing or ignored.
    df = pd.DataFrame(
        {
            "__index_level_0__": ["2025-01-01", "2025-01-02"],
            "Close": [10.0, 11.0],
        }
    )
    out = utils.canonicalize_ohlcv(df)
    assert list(out.index) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-02")]
    assert out["Adj Close"].tolist() == [10.0, 11.0]


def test_canonicalize_ohlcv_maps_unadjusted_close_semantics():
    idx = pd.date_range("2025-01-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            "Close": [10.0, 11.0],
            "Adj Close": [1.0, 2.0],
            "Unadjusted Close": [10.0, 11.0],
        },
        index=idx,
    )
    out = utils.canonicalize_ohlcv(df)
    assert out["Adj Close"].tolist() == [10.0, 11.0]


def test_to_naive_ts_and_round4():
    ts = pd.Timestamp("2025-01-01 12:00", tz="America/New_York")
    out = utils.to_naive_ts(ts)
    assert out.tz is None

    out2 = utils.to_naive_ts(datetime(2025, 1, 1, 12, 0))
    assert isinstance(out2, pd.Timestamp)

    assert utils.round4(1.23456) == 1.2346
    assert utils.round4(None) is None
    assert utils.round4(float("nan")) is None
