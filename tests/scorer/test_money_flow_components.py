import pandas as pd

from apps.scorer.src.services.money_flow import MoneyFlowCalculator


def test_cmf_uses_raw_close_not_adj_close():
    # If CMF mistakenly uses Adj Close while High/Low are unadjusted, the multiplier can be
    # wildly wrong. This test forces Adj Close to be inconsistent with the High/Low range to
    # ensure CMF is computed from the raw Close column.
    # Use >5 rows so rolling CMF has enough non-null values with min_valid_frac=0.8.
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    df = pd.DataFrame(
        {
            "High": [10.0] * len(idx),
            "Low": [0.0] * len(idx),
            "Close": [10.0] * len(idx),
            "Adj Close": [0.0] * len(idx),
            "Volume": [1.0] * len(idx),
        },
        index=idx,
    )

    calc = MoneyFlowCalculator(min_valid_frac=0.8)
    comps = calc.compute_components(df)
    assert comps["cmf_5"] is not None
    assert abs(float(comps["cmf_5"]) - 1.0) < 1e-12
