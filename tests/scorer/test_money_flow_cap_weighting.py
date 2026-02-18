import sys
from pathlib import Path

import numpy as np
import pandas as pd

# add scorer src to path
ROOT = Path(__file__).resolve().parents[2]
SCORER_SRC = ROOT / "apps" / "scorer" / "src"
sys.path.insert(0, str(SCORER_SRC))

from services.money_flow import MoneyFlowCalculator


def test_weighted_zscore_matches_unweighted_for_uniform_weights():
    x = pd.Series([1.0, 2.0, 3.0], index=["a", "b", "c"])
    w = pd.Series([1.0, 1.0, 1.0], index=x.index)
    z_w = MoneyFlowCalculator.weighted_zscore(x, w, clip=10.0)
    z = MoneyFlowCalculator.zscore(x, clip=10.0)
    assert np.allclose(z_w.values, z.values, atol=1e-12, rtol=0)


def test_weighted_rank_pct_shifts_percentiles_with_large_weight():
    # Large weight at the lowest value should push that observation toward the median
    x = pd.Series([0.0, 1.0, 2.0], index=["big", "small1", "small2"])
    w = pd.Series([100.0, 1.0, 1.0], index=x.index)
    p = MoneyFlowCalculator.weighted_rank_pct(x, w)
    # Mid-rank convention: p(lowest) ~= 0.5*100 / 102
    assert abs(float(p.loc["big"]) - (50.0 / 102.0)) < 1e-12
    assert float(p.loc["small1"]) > 0.9
    assert float(p.loc["small2"]) > float(p.loc["small1"])


def test_weighted_rank_pct_ties_use_group_midrank():
    x = pd.Series([0.0, 0.0, 1.0], index=["a", "b", "c"])
    w = pd.Series([2.0, 1.0, 1.0], index=x.index)
    p = MoneyFlowCalculator.weighted_rank_pct(x, w)
    # Tie group at 0.0 has weight 3.0, total weight 4.0 => p = (0 + 0.5*3)/4 = 0.375
    assert abs(float(p.loc["a"]) - 0.375) < 1e-12
    assert abs(float(p.loc["b"]) - 0.375) < 1e-12
    assert abs(float(p.loc["c"]) - 0.875) < 1e-12

