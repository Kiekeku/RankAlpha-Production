from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd

from apps.scorer.src.services.vix_term_structure import VixTermStructureService


def test_build_term_structure_and_classify_regime():
    settings = SimpleNamespace(
        scoring_vix_window_days=3,
        scoring_vix_calm_pct=0.30,
        scoring_vix_stress_pct=0.70,
        scoring_vix_panic_pct=0.90,
        scoring_vix_ffill_limit=0,
    )
    svc = VixTermStructureService("sqlite://", logging.getLogger("tests.vix"), settings)

    idx = pd.date_range("2025-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "date_key": [20250101, 20250102, 20250103, 20250104, 20250105],
            # Tenors (defaults in contango)
            "VIX1D": [18, 19, 20, 9, 35],
            "VIX9D": [19, 20, 21, 10, 36],
            "VIX": [20, 21, 22, 10.5, 40],  # vix_1m (day4 strict contango vs 9d)
            "VIX3M": [21, 22, 23, 11.5, 30],  # day5 backwardation (1m > 3m)
            "VIX6M": [22, 23, 24, 12.5, 31],
            "VIX1Y": [23, 24, 25, 13.5, 32],
        },
        index=idx,
    )

    ts = svc.build_term_structure(df)
    assert "curve_slope" in ts.columns
    assert float(ts.loc[idx[0], "curve_slope"]) == float(23 - 18)
    assert bool(ts.loc[idx[0], "is_contango_full"]) is True

    out = svc.classify_regime(ts)
    # With window=3, day4 is first "ready" day.
    assert out.loc[idx[3], "regime"] == "calm"
    assert out.loc[idx[4], "regime"] == "panic"
    assert int(out.loc[idx[4], "risk_flag"]) == 1
