from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from apps.scorer.src.services.valuation import ValuationService


def test_attach_pe_synth_uses_market_cap_implied_price_and_eps():
    as_of = pd.Timestamp(datetime(2025, 1, 2, tzinfo=timezone.utc)).tz_convert(None)
    df = pd.DataFrame(
        [
            # A: uses epsactual
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "sharesoutstanding", "metric_value": 10_000_000.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "epsactual", "metric_value": 2.0, "as_of": as_of},
            # B: epsactual missing -> fall back to aepsnorm
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 200.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "sharesoutstanding", "metric_value": 20_000_000.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "aepsnorm", "metric_value": 4.0, "as_of": as_of},
            # C: shares=0 -> inf -> should not emit
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 50.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "sharesoutstanding", "metric_value": 0.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "epsactual", "metric_value": 1.0, "as_of": as_of},
        ]
    )

    out = ValuationService._attach_pe(df, global_as_of_key=20250102, global_as_of_ts=as_of)
    synth = out[out["metric_code"] == "pe_synth"].copy()

    assert set(synth["symbol"]) == {"A", "B"}
    assert set(synth["date_key"]) == {20250102}

    # A: price = (100mm * 1e6) / 10mm = 10; PE=10/2=5
    a_val = float(synth.loc[synth["symbol"] == "A", "metric_value"].iloc[0])
    assert abs(a_val - 5.0) < 1e-12

    # B: price = (200mm * 1e6) / 20mm = 10; PE=10/4=2.5
    b_val = float(synth.loc[synth["symbol"] == "B", "metric_value"].iloc[0])
    assert abs(b_val - 2.5) < 1e-12


def test_attach_pfcf_synth_prefers_per_share_then_total_then_annual():
    as_of = pd.Timestamp(datetime(2025, 1, 2, tzinfo=timezone.utc)).tz_convert(None)
    df = pd.DataFrame(
        [
            # A: uses ttmfcfshr
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "sharesoutstanding", "metric_value": 10_000_000.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmfcfshr", "metric_value": 1.0, "as_of": as_of},
            # B: no per-share -> uses total ttmfcf (millions)
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmfcf", "metric_value": 20.0, "as_of": as_of},
            # C: ttmfcf missing -> uses annual a1fcf (millions)
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "a1fcf", "metric_value": 50.0, "as_of": as_of},
            # D: insufficient inputs -> no emit
            {"date_key": 20250102, "symbol": "D", "sector": "Tech", "peer_group": "Tech", "metric_code": "mktcap", "metric_value": 100.0, "as_of": as_of},
        ]
    )

    out = ValuationService._attach_pfcf(df, global_as_of_key=20250102, global_as_of_ts=as_of)
    synth = out[out["metric_code"] == "pfcf_synth"].copy()

    assert set(synth["symbol"]) == {"A", "B", "C"}
    assert set(synth["date_key"]) == {20250102}

    # A: price = (100mm * 1e6) / 10mm = 10; PFCF=10/1=10
    a_val = float(synth.loc[synth["symbol"] == "A", "metric_value"].iloc[0])
    assert abs(a_val - 10.0) < 1e-12

    # B: PFCF = 100 / 20 = 5
    b_val = float(synth.loc[synth["symbol"] == "B", "metric_value"].iloc[0])
    assert abs(b_val - 5.0) < 1e-12

    # C: PFCF = 100 / 50 = 2
    c_val = float(synth.loc[synth["symbol"] == "C", "metric_value"].iloc[0])
    assert abs(c_val - 2.0) < 1e-12


def test_value_scoring_ranks_higher_yield_as_cheaper_and_shrinks_low_coverage():
    as_of = pd.Timestamp(datetime(2025, 1, 2, tzinfo=timezone.utc)).tz_convert(None)
    df = pd.DataFrame(
        [
            # Price/Sales (lower is cheaper)
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmpr2rev", "metric_value": 2.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "B", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmpr2rev", "metric_value": 10.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "ttmpr2rev", "metric_value": 4.0, "as_of": as_of},
            # P/E (lower is cheaper) available for A and C; missing for B to force partial coverage
            {"date_key": 20250102, "symbol": "A", "sector": "Tech", "peer_group": "Tech", "metric_code": "peexclxor", "metric_value": 5.0, "as_of": as_of},
            {"date_key": 20250102, "symbol": "C", "sector": "Tech", "peer_group": "Tech", "metric_code": "peexclxor", "metric_value": 15.0, "as_of": as_of},
        ]
    )

    metric_groups_default = {
        "ps": {"codes": ["ttmpr2rev"], "weight": 0.50},
        "pe": {"codes": ["peexclxor"], "weight": 0.50},
    }
    sector_overrides: dict[str, dict[str, dict]] = {}

    out = ValuationService._compute_value_scores_from_frame(
        df,
        metric_groups_default=metric_groups_default,
        sector_overrides=sector_overrides,
        direct_yield_codes=set(),
        statement_metric_codes=set(),
        sector_weight=1.0,
        market_weight=0.0,
        min_sector_size=1,
        recency_calendar_days=3650,
        statement_recency_calendar_days=3650,
        winsorize=False,
        winsor_lo=0.0,
        winsor_hi=1.0,
        coverage_shrink=True,
        coverage_shrink_center=50.0,
        coverage_shrink_power=1.0,
    )

    assert out["A"]["value_score_raw"] > out["C"]["value_score_raw"] > out["B"]["value_score_raw"]
    assert out["A"]["coverage"] == 1.0
    assert abs(float(out["A"]["value_score"]) - float(out["A"]["value_score_raw"])) < 1e-12

    # B only has one of two buckets -> coverage 0.5; score shrinks toward 50.
    assert out["B"]["coverage"] == 0.5
    expected_b = 50.0 * 0.5 + float(out["B"]["value_score_raw"]) * 0.5
    assert abs(float(out["B"]["value_score"]) - expected_b) < 1e-12
