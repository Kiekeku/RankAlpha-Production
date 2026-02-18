from __future__ import annotations

import numpy as np
import pandas as pd

from apps.scorer.src import weights


def _make_panel(date: pd.Timestamp, symbols: list[str], values: list[float]) -> pd.Series:
    idx = pd.MultiIndex.from_product([[date], symbols], names=["as_of_date", "symbol"])
    return pd.Series(values, index=idx, dtype=float)


def test_ewma_mean_std_handles_empty_and_constant():
    m, s = weights._ewma_mean_std(pd.Series([], dtype=float))
    assert m == 0.0 and s == 1.0

    m2, s2 = weights._ewma_mean_std(pd.Series([1.0, 1.0, 1.0], dtype=float))
    assert abs(m2 - 1.0) < 1e-12
    assert s2 == 1.0  # std fallback when too small


def test_daily_ic_computes_spearman_with_sufficient_coverage():
    dt = pd.Timestamp("2025-01-01")
    symbols = [f"S{i:02d}" for i in range(20)]
    ret = list(range(20))
    m_exp = list(range(20))
    v_exp = list(reversed(range(20)))

    fwd_ret = _make_panel(dt, symbols, ret)
    series = {"M": _make_panel(dt, symbols, m_exp), "V": _make_panel(dt, symbols, v_exp)}

    ic = weights._daily_ic(series, fwd_ret)
    assert abs(float(ic["M"].iloc[0]) - 1.0) < 1e-12
    assert abs(float(ic["V"].iloc[0]) + 1.0) < 1e-12


def test_daily_ic_returns_nan_when_coverage_is_insufficient():
    dt = pd.Timestamp("2025-01-01")
    symbols = [f"S{i:02d}" for i in range(19)]  # below 20 threshold
    fwd_ret = _make_panel(dt, symbols, list(range(19)))
    series = {"M": _make_panel(dt, symbols, list(range(19)))}
    ic = weights._daily_ic(series, fwd_ret)
    assert np.isnan(float(ic["M"].iloc[0]))


def test_factor_returns_matches_rank_demean_definition():
    dt = pd.Timestamp("2025-01-01")
    symbols = ["A", "B", "C"]
    exposures = {"M": _make_panel(dt, symbols, [1.0, 2.0, 3.0])}
    next_ret = _make_panel(dt, symbols, [0.1, 0.0, -0.1])

    fr = weights._factor_returns(exposures, next_ret)
    # rank pct => [1/3, 2/3, 1]; demean => [-1/3, 0, 1/3]
    expected = (-1.0 / 3.0) * 0.1 + (1.0 / 3.0) * (-0.1)
    assert abs(float(fr["M"].iloc[0]) - expected) < 1e-12


def test_cross_sectional_zscore_panel_preserves_two_level_index_and_normalizes():
    d1 = pd.Timestamp("2025-01-01")
    d2 = pd.Timestamp("2025-01-02")
    symbols = ["A", "B", "C"]
    s = pd.concat(
        [
            _make_panel(d1, symbols, [1.0, 2.0, 3.0]),
            _make_panel(d2, symbols, [10.0, 11.0, 12.0]),
        ]
    )
    z = weights._cross_sectional_zscore_panel(s)
    assert z.index.nlevels == 2
    assert list(z.index.names) == ["as_of_date", "symbol"]

    for dt in (d1, d2):
        g = z.xs(dt, level=0)
        assert abs(float(g.mean())) < 1e-12
        assert abs(float(g.std(ddof=0)) - 1.0) < 1e-12


def test_select_train_start_date_uses_trading_day_offset(monkeypatch):
    end = pd.Timestamp("2025-01-10")
    window_days = 3

    def fake_read_sql_query(sql, engine, parse_dates=None):
        # Ensure we offset by (window_days-1) trading days (inclusive window).
        assert f"OFFSET {window_days - 1}" in str(sql)
        return pd.DataFrame({"full_date": [pd.Timestamp("2025-01-08")]})

    monkeypatch.setattr(weights.pd, "read_sql_query", fake_read_sql_query)
    start = weights._select_train_start_date(engine=object(), train_end_date=end, window_days=window_days)
    assert start == pd.Timestamp("2025-01-08")
