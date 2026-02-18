from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import MvRankRegimeDaily

from ..database import get_db

router = APIRouter(tags=["signals"], prefix="/api/v1/signals")


@router.get("/rank-regime")
def get_rank_regime_latest(db: Session = Depends(get_db)):
    row = (
        db.execute(select(MvRankRegimeDaily).order_by(desc(MvRankRegimeDaily.as_of_date)).limit(1))
        .scalars()
        .first()
    )
    if not row:
        return {"status": "empty"}
    return {
        "as_of_date": row.as_of_date,
        "universe_size": int(row.universe_size or 0),
        "momentum_breadth": float(row.momentum_breadth or 0.0),
        "value_breadth": float(row.value_breadth or 0.0),
        "breadth_spread": float(row.breadth_spread or 0.0),
        "val_to_mom_raw": float(row.val_to_mom_raw or 0.0),
        "mom_to_val_raw": float(row.mom_to_val_raw or 0.0),
        "top_bucket_turnover": float(row.top_bucket_turnover or 0.0),
        "val_to_mom_norm": float(row.val_to_mom_norm or 0.0),
        "mom_to_val_norm": float(row.mom_to_val_norm or 0.0),
        "fri_z": float(row.fri_z or 0.0),
        "fri_log": float(row.fri_log or 0.0),
        "tenure_m_median_days": float(row.tenure_m_median_days or 0.0)
        if row.tenure_m_median_days is not None
        else None,
        "tenure_v_median_days": float(row.tenure_v_median_days or 0.0)
        if row.tenure_v_median_days is not None
        else None,
        "hazard_m": float(row.hazard_m or 0.0),
        "hazard_v": float(row.hazard_v or 0.0),
        "factor_skew_mean": float(row.factor_skew_mean or 0.0),
        "dispersion_m_std": float(row.dispersion_m_std or 0.0)
        if row.dispersion_m_std is not None
        else None,
        "dispersion_v_std": float(row.dispersion_v_std or 0.0)
        if row.dispersion_v_std is not None
        else None,
        "regime_label": row.regime_label,
        "regime_confidence": float(row.regime_confidence or 0.0)
        if row.regime_confidence is not None
        else None,
    }


@router.get("/rank-regime/history")
def get_rank_regime_history(
    db: Session = Depends(get_db),
    days: int = Query(252, ge=30, le=1000),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
):
    q = select(MvRankRegimeDaily)
    if start_date or end_date:
        if start_date:
            q = q.where(MvRankRegimeDaily.as_of_date >= start_date)
        if end_date:
            q = q.where(MvRankRegimeDaily.as_of_date <= end_date)
    else:
        # default last N days ending at latest
        latest = db.execute(select(func.max(MvRankRegimeDaily.as_of_date))).scalar_one_or_none()
        if latest is not None:
            start = latest - timedelta(days=days)
            q = q.where(MvRankRegimeDaily.as_of_date >= start)
    order_col = (
        asc(MvRankRegimeDaily.as_of_date)
        if sort_order == "asc"
        else desc(MvRankRegimeDaily.as_of_date)
    )
    rows = db.execute(q.order_by(order_col)).scalars().all()
    items: List[dict] = []
    for r in rows:
        items.append(
            {
                "as_of_date": r.as_of_date,
                "universe_size": int(r.universe_size or 0),
                "momentum_breadth": float(r.momentum_breadth or 0.0),
                "value_breadth": float(r.value_breadth or 0.0),
                "breadth_spread": float(r.breadth_spread or 0.0),
                "val_to_mom_raw": float(r.val_to_mom_raw or 0.0),
                "mom_to_val_raw": float(r.mom_to_val_raw or 0.0),
                "top_bucket_turnover": float(r.top_bucket_turnover or 0.0),
                "val_to_mom_norm": float(r.val_to_mom_norm or 0.0),
                "mom_to_val_norm": float(r.mom_to_val_norm or 0.0),
                "fri_z": float(r.fri_z or 0.0),
                "fri_log": float(r.fri_log or 0.0),
                "tenure_m_median_days": float(r.tenure_m_median_days or 0.0)
                if r.tenure_m_median_days is not None
                else None,
                "tenure_v_median_days": float(r.tenure_v_median_days or 0.0)
                if r.tenure_v_median_days is not None
                else None,
                "hazard_m": float(r.hazard_m or 0.0),
                "hazard_v": float(r.hazard_v or 0.0),
                "factor_skew_mean": float(r.factor_skew_mean or 0.0),
                "dispersion_m_std": float(r.dispersion_m_std or 0.0)
                if r.dispersion_m_std is not None
                else None,
                "dispersion_v_std": float(r.dispersion_v_std or 0.0)
                if r.dispersion_v_std is not None
                else None,
                "regime_label": r.regime_label,
                "regime_confidence": float(r.regime_confidence or 0.0)
                if r.regime_confidence is not None
                else None,
            }
        )
    return {"items": items, "total_count": len(items)}
