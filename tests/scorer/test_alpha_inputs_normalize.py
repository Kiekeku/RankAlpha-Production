from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from apps.scorer.src.services.alpha_inputs import AlphaInputs


def test_normalize_series_handles_empty_and_all_missing():
    svc = AlphaInputs(engine=None)

    empty = pd.Series([], dtype=float)
    out = svc._normalize_series(empty)
    assert out.empty

    all_missing = pd.Series([None, "x", np.nan], dtype=object)
    out2 = svc._normalize_series(all_missing)
    assert out2.tolist() == [None, None, None]


def test_normalize_series_constant_returns_midpoint_50():
    svc = AlphaInputs(engine=None)
    values = pd.Series([5.0, 5.0, 5.0], index=["a", "b", "c"])
    out = svc._normalize_series(values)
    assert out.tolist() == [50.0, 50.0, 50.0]


def test_normalize_series_scales_and_clips():
    svc = AlphaInputs(engine=None)
    values = pd.Series([0.0, 10.0, 100.0, 1000.0, None], index=list("abcde"))
    out = svc._normalize_series(values)

    assert pd.isna(out.loc["e"])
    for k in ["a", "b", "c", "d"]:
        assert 0.0 <= float(out.loc[k]) <= 100.0
    # Monotone with value (ignoring the None)
    assert float(out.loc["a"]) <= float(out.loc["b"]) <= float(out.loc["c"]) <= float(out.loc["d"])
