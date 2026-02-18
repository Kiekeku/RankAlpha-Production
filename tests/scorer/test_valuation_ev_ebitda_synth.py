from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from apps.scorer.src.services.valuation import ValuationService


def test_attach_ev_ebitda_synth_prefers_interim_net_debt_then_annual():
    as_of = pd.Timestamp(datetime(2025, 1, 2, tzinfo=timezone.utc)).tz_convert(None)
    df = pd.DataFrame(
        [
            # A: has interim net debt
            {"date_key": 20241231, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "netdebt_i", "metric_value": 10.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "netdebt_a", "metric_value": 11.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmebitd", "metric_value": 20.0, "as_of": as_of},
            # B: interim missing -> use annual
            {"date_key": 20241231, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 200.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "netdebt_i", "metric_value": np.nan, "as_of": as_of},
            {"date_key": 20241231, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "netdebt_a", "metric_value": 50.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmebitd", "metric_value": 25.0, "as_of": as_of},
            # C: invalid (ebitda=0 -> inf) -> should not emit
            {"date_key": 20241231, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 10.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "netdebt_a", "metric_value": 0.0, "as_of": as_of},
            {"date_key": 20241231, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmebitd", "metric_value": 0.0, "as_of": as_of},
        ]
    )

    out = ValuationService._attach_ev_ebitda(df, global_as_of_key=20250102, global_as_of_ts=as_of)
    synth = out[out["metric_code"] == "ev2ebitda_synth"].copy()
    assert set(synth["symbol"]) == {"A", "B"}
    assert set(synth["date_key"]) == {20250102}

    # A: (100 + 10) / 20 = 5.5
    a_val = float(synth.loc[synth["symbol"] == "A", "metric_value"].iloc[0])
    assert abs(a_val - 5.5) < 1e-12
    # B: (200 + 50) / 25 = 10
    b_val = float(synth.loc[synth["symbol"] == "B", "metric_value"].iloc[0])
    assert abs(b_val - 10.0) < 1e-12

