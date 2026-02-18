import pandas as pd
import numpy as np


def test_blend_momentum_series_modes():
    from apps.scorer.src.main import _blend_momentum_series

    idx = pd.Index(["A", "B"])  # symbols
    raw = pd.Series([10.0, 30.0], index=idx)
    resid = pd.Series([50.0, 70.0], index=idx)

    class S:
        scoring_momentum_composite_mode = "blend"
        scoring_momentum_residual_weight = 0.7
        scoring_momentum_raw_weight = 0.3

    comp, mode, w_resid, w_raw = _blend_momentum_series(raw, resid, S())
    assert mode == "blend" and abs(w_resid - 0.7) < 1e-9 and abs(w_raw - 0.3) < 1e-9
    expected = resid * 0.7 + raw * 0.3
    assert comp.equals(expected)

    # residual-only mode
    S.scoring_momentum_composite_mode = "residual"
    comp2, mode2, _, _ = _blend_momentum_series(raw, resid, S())
    assert mode2 == "residual" and comp2.equals(resid)

    # raw-only mode
    S.scoring_momentum_composite_mode = "raw"
    comp3, mode3, _, _ = _blend_momentum_series(raw, resid, S())
    assert mode3 == "raw" and comp3.equals(raw)


def test_blend_momentum_series_weight_fallback():
    from apps.scorer.src.main import _blend_momentum_series

    idx = pd.Index(["A", "B"])  # symbols
    raw = pd.Series([10.0, 30.0], index=idx)
    resid = pd.Series([50.0, 70.0], index=idx)

    class S:
        scoring_momentum_composite_mode = "blend"
        scoring_momentum_residual_weight = 0.0
        scoring_momentum_raw_weight = 0.0

    comp, mode, w_resid, w_raw = _blend_momentum_series(raw, resid, S())
    # Should fall back to 0.7/0.3 when weights sum <= 0
    assert mode == "blend" and abs(w_resid - 0.7) < 1e-9 and abs(w_raw - 0.3) < 1e-9
    expected = resid * 0.7 + raw * 0.3
    assert comp.equals(expected)

