from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import VwBreadthSignal, VwMacroSeries

from ..database import get_db

router = APIRouter(tags=["breadth"], prefix="/api/v1/breadth")

MACRO_CONTEXT_SERIES_CODES = {"#NYAZWBT", "#NYSEADVR"}

UNIVERSE_SERIES: Dict[str, Dict[str, str]] = {
    "NYSE": {
        "hindenburg_raw": "US_NYA_HINDENBURG_OMEN_RAW",
        "hindenburg_confirmed": "US_NYA_HINDENBURG_OMEN_CONFIRMED",
        "hlli": "US_NYSE_HLLI",
        "zweig_breadth_thrust": "#NYAZWBT",
        "ad_ratio": "#NYSEADVR",
        "persistent_new_lows": "US_NYSE_PERSISTENT_NEW_LOWS_FLAG",
        "trin_stress": "US_NYSE_TRIN_STRESS_FLAG",
    },
    "SPX": {
        "net_new_highs": "US_SPX_NET_NEW_HIGHS",
        "whaley": "US_SPX_WHALEY_ADT5",
        "whaley_bull": "US_SPX_WHALEY_ADT5_BULL_FLAG",
        "whaley_capitulation": "US_SPX_WHALEY_ADT5_CAPITULATION_FLAG",  # gitleaks:allow
        "bam_up": "US_SPX_BAM10_UP_FLAG",
        "bam_down": "US_SPX_BAM10_DOWN_FLAG",
        "mcclellan_thrust": "US_SPX_MCCLELLAN_THRUST_FLAG",
        "mcclellan_sum_breakdown": "US_SPX_MCCLELLAN_SUM_BREAKDOWN_FLAG",
        "persistent_new_lows": "US_SPX_PERSISTENT_NEW_LOWS_FLAG",
        "pct_above_200d_thrust": "US_SPX_PCT_ABOVE_200D_THRUST_FLAG",
        "pct_below_200d_collapse": "US_SPX_PCT_BELOW_200D_COLLAPSE_FLAG",
        "trin_stress": "US_SPX_TRIN_STRESS_FLAG",
        "ad_bearish_divergence": "US_SPX_AD_BEARISH_DIVERGENCE_FLAG",
        "thrust_score": "US_SPX_BREADTH_THRUST_SCORE",
        "frag_score": "US_SPX_BREADTH_FRAG_SCORE",
        "net_score": "US_SPX_BREADTH_NET_SCORE",
        "regime_state": "US_SPX_BREADTH_REGIME_STATE",
        "target_exposure": "US_SPX_BREADTH_TARGET_EXPOSURE",
    },
    "NDX": {
        "net_new_highs": "US_NDX_NET_NEW_HIGHS",
        "whaley": "US_NDX_WHALEY_ADT5",
        "whaley_bull": "US_NDX_WHALEY_ADT5_BULL_FLAG",
        "whaley_capitulation": "US_NDX_WHALEY_ADT5_CAPITULATION_FLAG",  # gitleaks:allow
        "bam_up": "US_NDX_BAM10_UP_FLAG",
        "bam_down": "US_NDX_BAM10_DOWN_FLAG",
        "mcclellan_thrust": "US_NDX_MCCLELLAN_THRUST_FLAG",
        "mcclellan_sum_breakdown": "US_NDX_MCCLELLAN_SUM_BREAKDOWN_FLAG",
        "persistent_new_lows": "US_NDX_PERSISTENT_NEW_LOWS_FLAG",
        "pct_above_200d_thrust": "US_NDX_PCT_ABOVE_200D_THRUST_FLAG",
        "pct_below_200d_collapse": "US_NDX_PCT_BELOW_200D_COLLAPSE_FLAG",
        "trin_stress": "US_NDX_TRIN_STRESS_FLAG",
        "ad_bearish_divergence": "US_NDX_AD_BEARISH_DIVERGENCE_FLAG",
        "thrust_score": "US_NDX_BREADTH_THRUST_SCORE",
        "frag_score": "US_NDX_BREADTH_FRAG_SCORE",
        "net_score": "US_NDX_BREADTH_NET_SCORE",
        "regime_state": "US_NDX_BREADTH_REGIME_STATE",
        "target_exposure": "US_NDX_BREADTH_TARGET_EXPOSURE",
    },
}

# Flat indicator lookup used by /series
INDICATOR_TO_SERIES: Dict[str, Dict[str, str]] = {
    indicator: {
        u: series for u, mapping in UNIVERSE_SERIES.items() if (series := mapping.get(indicator))
    }
    for indicator in {
        "hindenburg_raw",
        "hindenburg_confirmed",
        "hlli",
        "zweig_breadth_thrust",
        "ad_ratio",
        "net_new_highs",
        "whaley",
        "whaley_bull",
        "whaley_capitulation",
        "bam_up",
        "bam_down",
        "mcclellan_thrust",
        "mcclellan_sum_breakdown",
        "persistent_new_lows",
        "pct_above_200d_thrust",
        "pct_below_200d_collapse",
        "trin_stress",
        "ad_bearish_divergence",
        "thrust_score",
        "frag_score",
        "net_score",
        "regime_state",
        "target_exposure",
        "regime_label",
    }
}

# Map regime_label to the underlying regime_state series to avoid 404s
INDICATOR_TO_SERIES["regime_label"] = {
    u: mapping["regime_state"]
    for u, mapping in UNIVERSE_SERIES.items()
    if "regime_state" in mapping
}


@router.get("/latest")
def get_breadth_latest(db: Session = Depends(get_db)):
    # Collect all series_codes we care about
    all_series = {code for m in UNIVERSE_SERIES.values() for code in m.values()}
    macro_codes = {c for c in all_series if c in MACRO_CONTEXT_SERIES_CODES}
    breadth_codes = all_series - macro_codes

    latest_map: Dict[str, tuple[date | None, float | None]] = {}
    if breadth_codes:
        subq = (
            select(
                VwBreadthSignal.series_code,
                VwBreadthSignal.as_of_date,
                VwBreadthSignal.value,
                func.row_number()
                .over(
                    partition_by=VwBreadthSignal.series_code,
                    order_by=desc(VwBreadthSignal.as_of_date),
                )
                .label("rn"),
            )
            .where(VwBreadthSignal.series_code.in_(breadth_codes))
            .subquery()
        )
        rows = db.execute(
            select(subq.c.series_code, subq.c.as_of_date, subq.c.value).where(subq.c.rn == 1)
        ).all()
        latest_map.update(
            {
                r.series_code: (r.as_of_date, float(r.value) if r.value is not None else None)
                for r in rows
            }
        )

    if macro_codes:
        subq2 = (
            select(
                VwMacroSeries.series_code,
                VwMacroSeries.as_of_date,
                VwMacroSeries.value,
                func.row_number()
                .over(
                    partition_by=VwMacroSeries.series_code, order_by=desc(VwMacroSeries.as_of_date)
                )
                .label("rn"),
            )
            .where(VwMacroSeries.series_code.in_(macro_codes))
            .subquery()
        )
        rows2 = db.execute(
            select(subq2.c.series_code, subq2.c.as_of_date, subq2.c.value).where(subq2.c.rn == 1)
        ).all()
        latest_map.update(
            {
                r.series_code: (r.as_of_date, float(r.value) if r.value is not None else None)
                for r in rows2
            }
        )

    def pick(series_code: str):
        return latest_map.get(series_code, (None, None))[1]

    def pick_date(series_code: str):
        return latest_map.get(series_code, (None, None))[0]

    def state_label(val: Optional[float]) -> Optional[str]:
        if val is None:
            return None
        if val <= -0.5:
            return "risk_off"
        if val >= 0.5:
            return "risk_on"
        return "neutral"

    # Build payload per universe
    resp: Dict[str, dict] = {}
    ref_date: Optional[date] = None
    for uni, mapping in UNIVERSE_SERIES.items():
        uni_payload = {}
        for logical, series_code in mapping.items():
            uni_payload[logical] = pick(series_code)
            if logical == "regime_state":
                uni_payload["regime_label"] = state_label(uni_payload[logical])
            if ref_date is None:
                ref_date = pick_date(series_code) or ref_date
        resp[uni.lower()] = uni_payload

    return {
        "as_of_date": ref_date,
        **resp,
    }


@router.get("/series")
def get_breadth_series(
    db: Session = Depends(get_db),
    universe: str = Query(..., pattern="^(SPX|NDX|NYSE)$"),
    indicator: str = Query(
        ...,
        pattern="^(hindenburg_raw|hindenburg_confirmed|hlli|zweig_breadth_thrust|ad_ratio|net_new_highs|whaley|whaley_bull|whaley_capitulation|bam_up|bam_down|mcclellan_thrust|mcclellan_sum_breakdown|persistent_new_lows|pct_above_200d_thrust|pct_below_200d_collapse|trin_stress|ad_bearish_divergence|thrust_score|frag_score|net_score|regime_state|regime_label|target_exposure)$",
    ),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    series_lookup = INDICATOR_TO_SERIES.get(indicator, {})
    series_code = series_lookup.get(universe)
    if not series_code:
        raise HTTPException(
            status_code=404,
            detail=f"Indicator '{indicator}' not available for universe '{universe}'",
        )

    if series_code in MACRO_CONTEXT_SERIES_CODES:
        q = select(VwMacroSeries).where(VwMacroSeries.series_code == series_code)
        if start_date:
            q = q.where(VwMacroSeries.as_of_date >= start_date)
        if end_date:
            q = q.where(VwMacroSeries.as_of_date <= end_date)
        order_col = (
            VwMacroSeries.as_of_date.asc()
            if sort_order == "asc"
            else VwMacroSeries.as_of_date.desc()
        )
        total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
        rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()
        items = [
            {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
            for r in rows
        ]
        return {
            "items": items,
            "total_count": int(total or 0),
            "page": (skip // limit) + 1,
            "page_size": limit,
        }

    q = select(VwBreadthSignal).where(VwBreadthSignal.series_code == series_code)
    if start_date:
        q = q.where(VwBreadthSignal.as_of_date >= start_date)
    if end_date:
        q = q.where(VwBreadthSignal.as_of_date <= end_date)
    order_col = (
        VwBreadthSignal.as_of_date.asc()
        if sort_order == "asc"
        else VwBreadthSignal.as_of_date.desc()
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()
    if indicator == "regime_label" or indicator == "regime_state":
        # Build from regime_state and derive labels
        base_rows = rows
        items = []
        for r in base_rows:
            val = float(r.value) if r.value is not None else None
            label = None
            if val is not None:
                if val <= -0.5:
                    label = "risk_off"
                elif val >= 0.5:
                    label = "risk_on"
                else:
                    label = "neutral"
            items.append({"as_of_date": r.as_of_date, "value": val, "label": label})
    else:
        items = [
            {"as_of_date": r.as_of_date, "value": float(r.value) if r.value is not None else None}
            for r in rows
        ]
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
