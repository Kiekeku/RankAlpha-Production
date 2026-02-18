import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd

from apps.scorer.src.services.vol_risk_premium import VolRiskPremiumService


def _build_service(**overrides):
    defaults = dict(
        scoring_vrp_trading_days=5,
        scoring_vrp_lookback_days=5,
        scoring_vrp_vrp_low_pct=0.20,
        scoring_vrp_vrp_high_pct=0.80,
        scoring_vrp_vix_low_pct=0.33,
        scoring_vrp_vix_high_pct=0.66,
        scoring_vix_ffill_limit=1,
    )
    defaults.update(overrides)
    settings = SimpleNamespace(**defaults)
    logger = logging.getLogger("test")
    return VolRiskPremiumService("postgresql://user:pass@localhost/db", logger, settings)


def test_compute_vrp_basic():
    svc = _build_service()

    dates = pd.date_range("2023-01-01", periods=25, freq="B")
    # SPX grows 1% per day with stable intraday range ratios
    spx_open = 100 * (1.01) ** np.arange(len(dates))
    spx_close = spx_open * 1.005   # close 0.5% above open
    spx_high = spx_open * 1.01     # intraday high +1%
    spx_low  = spx_open * 0.99     # intraday low -1%
    vix = np.full(len(dates), 20.0)  # flat VIX

    df = pd.DataFrame(
        {
            "date_key": range(1, len(dates) + 1),
            "spx_open": spx_open,
            "spx_high": spx_high,
            "spx_low": spx_low,
            "spx_close": spx_close,
            "vix_close": vix,
        },
        index=dates,
    )

    ts = svc.compute_vrp(df)

    # First tradable VRP value appears after window=5
    assert not ts.empty
    # Pick last row for stable window
    last = ts.iloc[-1]

    log_ho = np.log(spx_high[0] / spx_open[0])
    log_hc = np.log(spx_high[0] / spx_close[0])
    log_lo = np.log(spx_low[0] / spx_open[0])
    log_lc = np.log(spx_low[0] / spx_close[0])
    expected_rs = log_ho * log_hc + log_lo * log_lc
    expected_rv = expected_rs * svc.trading_days
    expected_iv = (0.20**2) * (30.0 / 365.0)

    assert abs(last.rv_30d_var - expected_rv) < 1e-6
    assert abs(last.iv_30d_var - expected_iv) < 1e-6
    assert abs(last.vrp_30d - (expected_iv - expected_rv)) < 1e-6


def test_compute_vrp_close_to_close_fallback():
    svc = _build_service(scoring_vrp_trading_days=5, scoring_vrp_lookback_days=10)

    dates = pd.date_range("2023-03-01", periods=25, freq="B")
    spx_close = 100 * (1.01) ** np.arange(len(dates))
    vix = np.full(len(dates), 20.0)

    df = pd.DataFrame(
        {
            "date_key": range(1, len(dates) + 1),
            "spx_open": np.nan,
            "spx_high": np.nan,
            "spx_low": np.nan,
            "spx_close": spx_close,
            "vix_close": vix,
        },
        index=dates,
    )

    ts = svc.compute_vrp(df)
    assert not ts.empty

    # Expected realized variance: rolling sum of squared log returns
    log_ret = np.log(pd.Series(spx_close, index=dates) / pd.Series(spx_close, index=dates).shift(1))
    expected_rv_last = (log_ret**2).rolling(svc.trading_days).sum().dropna().iloc[-1]
    expected_iv = (0.20**2) * (30.0 / 365.0)

    last = ts.iloc[-1]
    assert abs(last.rv_30d_var - expected_rv_last) < 1e-6
    assert abs(last.iv_30d_var - expected_iv) < 1e-6
    assert abs(last.vrp_30d - (expected_iv - expected_rv_last)) < 1e-6


def test_classify_regime_mapping():
    svc = _build_service(scoring_vrp_lookback_days=5)

    dates = pd.date_range("2023-02-01", periods=10, freq="B")
    close = np.linspace(100, 110, len(dates))
    df = pd.DataFrame(
        {
            "date_key": range(1, len(dates) + 1),
            "spx_open": close * 0.995,
            "spx_high": close * 1.01,
            "spx_low": close * 0.99,
            "spx_close": close,
            "vix_close": [25, 24, 23, 30, 35, 40, 18, 17, 16, 15],
        },
        index=dates,
    )
    ts = svc.classify_regime(svc.compute_vrp(df))

    # After lookback, classifications should be present (last few rows)
    subset = ts.dropna(subset=["vrp_regime"]).tail(1).iloc[0]
    assert subset.vrp_regime in {
        "crisis / panic",
        "stressed but hedged",
        "carry / complacency",
        "calm but fragile",
        "neutral",
    }
