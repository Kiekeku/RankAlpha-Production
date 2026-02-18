from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    FactRegimeEffectiveWeight,
    FactRegimeSeries,
    FactStyleZUs,
    VwRegimeSeries,
)

from ..database import get_db
from ..utils.coerce import coerce_float

router = APIRouter(tags=["screener"], prefix="/api/v1/screener")


def _has_regime_signal(row) -> bool:
    fields = ("risk_on_core", "risk_off_core", "regime_raw", "ema10", "ema50")
    for field in fields:
        val = getattr(row, field, 0.0)
        if abs(coerce_float(val, 0.0)) > 1e-6:
            return True
    return False


def _coverage_summary(rows: List[VwRegimeSeries]):
    total = len(rows)
    valid = sum(1 for row in rows if _has_regime_signal(row))
    warning = None
    if total == 0:
        warning = "No regime history is available for the requested window."
    elif valid == 0:
        warning = "Regime inputs are unavailable because screener signals are missing for every requested day."
    elif (valid / total) < 0.15:
        warning = f"Regime inputs are sparse ({valid} of {total} days contain screener signals)."
    return valid, total, warning


@router.get("/regime/latest")
def get_regime_latest(db: Session = Depends(get_db)):
    q = select(VwRegimeSeries).order_by(desc(VwRegimeSeries.as_of_date)).limit(1)
    row = db.execute(q).scalars().first()
    if not row:
        return {"status": "empty"}
    # fetch effective weights for this date if available
    weights_items = []
    try:
        if row.date_key:
            wq = (
                select(FactRegimeEffectiveWeight)
                .where(FactRegimeEffectiveWeight.date_key == row.date_key)
                .order_by(asc(FactRegimeEffectiveWeight.canonical_name))
            )
            wrows = db.execute(wq).scalars().all()
            weights_items = [
                {
                    "canonical_name": wr.canonical_name,
                    "effective_weight": float(wr.effective_weight or 0.0),
                    "base_weight": float(wr.base_weight or 0.0)
                    if wr.base_weight is not None
                    else None,
                    "g_factor": float(wr.g_factor or 0.0) if wr.g_factor is not None else None,
                }
                for wr in wrows
            ]
    except Exception:
        weights_items = []
    has_signal = _has_regime_signal(row)
    coverage_warning = (
        None if has_signal else "Regime inputs are unavailable for this date (risk cores are zero)."
    )
    return {
        "as_of_date": row.as_of_date,
        "risk_on_core": float(row.risk_on_core or 0.0),
        "risk_off_core": float(row.risk_off_core or 0.0),
        "regime_raw": float(row.regime_raw or 0.0),
        "ema10": float(row.ema10 or 0.0),
        "ema50": float(row.ema50 or 0.0),
        "regime_label": row.regime_label,
        "regime_index": float(row.regime_index or 0.0),
        "participation": float(row.participation or 0.0) if row.participation is not None else None,
        "effective_weights": weights_items,
        "has_signal": has_signal,
        "coverage_warning": coverage_warning,
    }


@router.get("/regime/series")
def get_regime_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    filters = []
    if start_date:
        filters.append(VwRegimeSeries.as_of_date >= start_date)
    if end_date:
        filters.append(VwRegimeSeries.as_of_date <= end_date)
    order_col = (
        asc(VwRegimeSeries.as_of_date) if sort_order == "asc" else desc(VwRegimeSeries.as_of_date)
    )

    base = select(VwRegimeSeries).where(and_(*filters)) if filters else select(VwRegimeSeries)
    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = db.execute(base.order_by(order_col).offset(skip).limit(limit)).scalars().all()
    valid_points, total_points, coverage_warning = _coverage_summary(rows)
    items = []
    for r in rows:
        row_has_signal = _has_regime_signal(r)
        items.append(
            {
                "as_of_date": r.as_of_date,
                "risk_on_core": float(r.risk_on_core or 0.0),
                "risk_off_core": float(r.risk_off_core or 0.0),
                "regime_raw": float(r.regime_raw or 0.0),
                "ema10": float(r.ema10 or 0.0),
                "ema50": float(r.ema50 or 0.0),
                "regime_label": r.regime_label,
                "regime_index": float(r.regime_index or 0.0),
                "participation": float(r.participation or 0.0)
                if r.participation is not None
                else None,
                "has_signal": row_has_signal,
                "coverage_warning": None
                if row_has_signal
                else "Regime inputs are unavailable for this date (risk cores are zero).",
            }
        )
    coverage = {
        "valid_points": valid_points,
        "total_points": total_points,
        "has_signal": valid_points > 0,
        "warning": coverage_warning,
    }
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
        "coverage": coverage,
    }


@router.get("/regime/styles")
def get_regime_styles(
    db: Session = Depends(get_db),
    as_of: Optional[date] = Query(None, description="Defaults to latest available date"),
):
    # Determine date_key
    if as_of:
        dk_stmt = select(DimDate.date_key).where(DimDate.full_date == as_of)
    else:
        dk_stmt = select(func.max(FactRegimeSeries.date_key))
    dk = db.execute(dk_stmt).scalar_one_or_none()
    if dk is None:
        return {"as_of_date": as_of, "items": []}

    q = (
        select(FactStyleZUs.style_name, FactStyleZUs.z_value, DimDate.full_date)
        .select_from(FactStyleZUs)
        .join(DimDate, DimDate.date_key == FactStyleZUs.date_key)
        .where(FactStyleZUs.date_key == dk)
        .order_by(asc(FactStyleZUs.style_name))
    )
    rows = db.execute(q).all()
    items = [{"style": r[0], "z": float(r[1] or 0.0)} for r in rows]
    asof_date = rows[0][2] if rows else (as_of if as_of else None)
    return {"as_of_date": asof_date, "items": items}
