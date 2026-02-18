from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    FactNowcastPillarSnapshot,
    VwNowcastSnapshotLatest,
    VwNowcastSnapshotSeriesWithDeltas,
)

from ..database import get_db

router = APIRouter(tags=["nowcast"], prefix="/api/v1/nowcast")

DEFAULT_MODEL_VERSION = "nowcast_v2"

TIER_WEIGHTS: Dict[int, float] = {1: 0.50, 2: 0.30, 3: 0.20}

PILLAR_TITLES: Dict[str, str] = {
    "liquidity": "Liquidity",
    "vol_tail": "Vol / Tail",
    "funding": "Funding Stress",
    "credit": "Credit Stress",
    "rates_usd": "Rates & USD",
    "breadth": "Market Breadth",
    "flows": "Money Flow",
}


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


@router.get("/latest")
def get_nowcast_latest(
    db: Session = Depends(get_db),
    model_version: str = Query(
        DEFAULT_MODEL_VERSION, description="Nowcast model version (default nowcast_v2)"
    ),
    trail_days: int = Query(60, ge=1, le=260, description="Number of daily map points to return"),
):
    latest = db.execute(
        select(VwNowcastSnapshotLatest).where(
            VwNowcastSnapshotLatest.model_version == model_version
        )
    ).scalar_one_or_none()
    if not latest:
        return {"status": "empty"}

    pillars = (
        db.execute(
            select(FactNowcastPillarSnapshot)
            .where(
                FactNowcastPillarSnapshot.model_version == model_version,
                FactNowcastPillarSnapshot.date_key == latest.date_key,
            )
            .order_by(
                FactNowcastPillarSnapshot.tier.asc(), FactNowcastPillarSnapshot.pillar_key.asc()
            )
        )
        .scalars()
        .all()
    )

    data_date_keys = {p.data_date_key for p in pillars if p.data_date_key is not None}
    data_dates: Dict[int, Any] = {}
    if data_date_keys:
        data_dates = {
            int(k): v
            for k, v in db.execute(
                select(DimDate.date_key, DimDate.full_date).where(
                    DimDate.date_key.in_(data_date_keys)
                )
            ).all()
        }

    pillar_payload: List[Dict[str, Any]] = []
    for p in pillars:
        pillar_payload.append(
            {
                "pillar_key": p.pillar_key,
                "title": PILLAR_TITLES.get(p.pillar_key, p.pillar_key),
                "tier": int(p.tier),
                "score": _to_float(p.score),
                "data_as_of_date": (
                    data_dates.get(int(p.data_date_key)).isoformat()
                    if p.data_date_key is not None and int(p.data_date_key) in data_dates
                    else None
                ),
                "details": p.details or {},
            }
        )

    # Trail for the 2D map visualization (and optional sparklines).
    trail_rows = (
        db.execute(
            select(VwNowcastSnapshotSeriesWithDeltas)
            .where(
                VwNowcastSnapshotSeriesWithDeltas.model_version == model_version,
                VwNowcastSnapshotSeriesWithDeltas.date_key <= latest.date_key,
            )
            .order_by(desc(VwNowcastSnapshotSeriesWithDeltas.date_key))
            .limit(trail_days)
        )
        .scalars()
        .all()
    )
    trail_rows = list(reversed(trail_rows))
    map_trail = [
        {
            "as_of_date": r.as_of_date.isoformat() if r.as_of_date else None,
            "liquidity_ease": _to_float(r.map_liquidity_ease),
            "stress_score": _to_float(r.map_stress_score),
            "overall_risk_off": _to_float(r.overall_risk_off_score),
        }
        for r in trail_rows
        if r is not None
    ]

    # Drivers + alerts (computed from pillars, matching the frontend mental model).
    scored_pillars = [p for p in pillar_payload if isinstance(p.get("score"), (int, float))]
    tier_counts: Dict[int, int] = {1: 0, 2: 0, 3: 0}
    for p in scored_pillars:
        tier_counts[int(p["tier"])] = tier_counts.get(int(p["tier"]), 0) + 1

    available_tiers = [t for t, n in tier_counts.items() if n > 0]
    tier_weight_sum = sum(TIER_WEIGHTS.get(t, 0.0) for t in available_tiers) or 1.0

    drivers = []
    for p in scored_pillars:
        tier = int(p["tier"])
        n = tier_counts.get(tier, 0) or 1
        tier_weight = TIER_WEIGHTS.get(tier, 0.0) / tier_weight_sum
        w = tier_weight / n
        impact = w * (float(p["score"]) - 50.0)
        drivers.append({**p, "weight": w, "impact": impact})
    drivers = sorted(drivers, key=lambda x: abs(float(x["impact"])), reverse=True)[:3]

    alerts = []
    for p in scored_pillars:
        score = float(p["score"])
        if score >= 75:
            alerts.append({**p, "severity": "risk_off"})
        elif score <= 25:
            alerts.append({**p, "severity": "risk_on"})

    return {
        "model_version": latest.model_version,
        "as_of_date": latest.as_of_date.isoformat() if latest.as_of_date else None,
        "overall_risk_off_score": _to_float(latest.overall_risk_off_score),
        "nowcast_label": latest.nowcast_label,
        "confidence": _to_float(latest.confidence),
        "coverage": _to_float(latest.coverage),
        "delta_1d": _to_float(latest.delta_1d),
        "delta_5d": _to_float(latest.delta_5d),
        "label_1d_ago": latest.label_1d_ago,
        "label_5d_ago": latest.label_5d_ago,
        "cross_asset_stress_score": _to_float(latest.cross_asset_stress_score),
        "cross_asset_label": latest.cross_asset_label,
        "booster_applied": bool(latest.booster_applied)
        if latest.booster_applied is not None
        else False,
        "booster_amount": _to_float(latest.booster_amount),
        "spx_tlt_corr60": _to_float(latest.spx_tlt_corr60),
        "spx_ret20": _to_float(latest.spx_ret20),
        "tlt_ret20": _to_float(latest.tlt_ret20),
        "pillars": pillar_payload,
        "drivers": drivers,
        "alerts": alerts,
        "map_trail": map_trail,
    }
