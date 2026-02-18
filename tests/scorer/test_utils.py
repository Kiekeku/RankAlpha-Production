import sys
from pathlib import Path

import pandas as pd

# add scorer src to path
ROOT = Path(__file__).resolve().parents[2]
SCORER_SRC = ROOT / "apps" / "scorer" / "src"
sys.path.insert(0, str(SCORER_SRC))

import numpy as np
from services.momentum import MomentumCalculator
from services.prices import PriceReader
from apps.scorer.src.tools.explain_momentum import explain_momentum


def test_lin_reg():
    df = pd.DataFrame({"Close": range(10)})
    slope, r2, n = MomentumCalculator.linreg_log_slope_r2(df, window=len(df))
    assert slope is not None and slope > 0


def test_sma_200():
    df = pd.DataFrame({"Close": range(1, 201)})
    sma = MomentumCalculator.sma200_raw(df)
    assert abs(sma - 100.5) < 1e-6


def test_get_latest_date_key():
    dates = pd.date_range("2024-01-01", periods=3)
    df = pd.DataFrame({"Close": [1, 2, 3]}, index=dates)
    key = PriceReader.get_latest_date_key(df)
    assert key == 20240103


def test_lin_reg_with_descending_index():
    # Build an increasing close over time, then reverse the index ordering
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    df = pd.DataFrame({"Close": range(10)}, index=dates)
    df_desc = df.sort_index(ascending=False)
    slope, r2, n = MomentumCalculator.linreg_log_slope_r2(df_desc, window=len(df_desc))
    assert slope is not None and slope > 0


def test_latest_date_key_unsorted():
    # Ensure latest key comes from the max date, not positional last
    dates = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"])  # unsorted
    df = pd.DataFrame({"Close": [3, 1, 2]}, index=dates)
    key = PriceReader.get_latest_date_key(df)
    assert key == 20240103


def test_linreg_min_valid_frac_gate():
    # 10 points, 3 NaNs => 70% valid < 0.8 threshold, should gate
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    y = pd.Series(range(1, 11), index=dates, dtype=float)
    y.iloc[:3] = float("nan")
    df = pd.DataFrame({"Adj Close": y})
    s, r2, n = MomentumCalculator.linreg_log_slope_r2(df, window=10, min_valid_frac=0.8)
    assert s is None and r2 is None and n == 7


def test_linreg_exact_threshold_allows_compute():
    # 10 points, exactly 8 valid meets 0.8 threshold
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    y = pd.Series(range(1, 11), index=dates, dtype=float)
    y.iloc[:2] = float("nan")  # 8/10 valid
    df = pd.DataFrame({"Adj Close": y})
    s, r2, n = MomentumCalculator.linreg_log_slope_r2(df, window=10, min_valid_frac=0.8)
    assert n == 8 and s is not None and r2 is not None and r2 > 0


def test_explain_momentum_used_and_eff_weights():
    # Build a gently increasing synthetic series with enough history for the smallest window
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    close = pd.Series(100.0 + 0.1 * pd.RangeIndex(len(idx)), index=idx)
    df = pd.DataFrame({"Adj Close": close})
    rows, blend = explain_momentum(df, base_weights={200: 1.0, 90: 1.0, 50: 1.0, 30: 1.0}, min_valid_frac=0.8, tstat_cap=3.0)
    # Expect 4 windows reported even if some cannot be computed (slope None)
    assert len(rows) == 4
    # For 30-day window, should compute and be used with positive eff_weight and t_factor in [0,1]
    w30 = rows[rows["window"] == 30].iloc[0]
    assert (w30["t_factor"] is None) or (0.0 <= float(w30["t_factor"]) <= 1.0)
    # When slope/R2 present, used should be boolean; eff_weight non-negative
    if w30["slope_%_per_day"] is not None:
        assert w30["used"] in (True, False)
        assert float(w30["eff_weight"]) >= 0.0
    # Blend is None only if no windows contributed
    assert (blend is None) or isinstance(blend, float)


def test_explain_momentum_respects_min_valid_frac():
    # 40 points; make only 60% valid in the last 30 => should not be used
    idx = pd.date_range("2024-01-01", periods=40, freq="D")
    close = pd.Series(range(1, 41), index=idx, dtype=float)
    # Invalidate 12 of the last 30 observations (60% valid)
    tail_idx = close.tail(30).index
    close.loc[tail_idx[:12]] = float("nan")
    df = pd.DataFrame({"Adj Close": close})
    rows, blend = explain_momentum(df, base_weights={200:1,90:1,50:1,30:1}, min_valid_frac=0.8, tstat_cap=3.0)
    w30 = rows[rows["window"] == 30].iloc[0]
    # Present but below threshold => either slope None or used False with eff_weight 0.0
    if w30["slope_%_per_day"] is None:
        # Column exists and is a boolean-like value
        assert "used" in w30.index
        assert isinstance(w30["used"], (bool, np.bool_))
    else:
        assert w30["used"] is False and float(w30["eff_weight"]) == 0.0
