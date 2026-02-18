from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import VwHyStress, VwHyStressLatest

from ..database import get_db

router = APIRouter(tags=["risk"], prefix="/api/v1/hy-stress")


DEFAULT_BENCHMARK = "%CCCHYS"
HIGH_RISK_THRESHOLD = 1.5
LOW_RISK_THRESHOLD = -1.0


def _label_from_z(z: Optional[float]) -> str:
    if z is None:
        return "not enough data"
    if z > HIGH_RISK_THRESHOLD:
        return "risk_off"
    if z < LOW_RISK_THRESHOLD:
        return "risk_on"
    return "neutral"


@router.get("/latest")
def get_hy_stress_latest(
    db: Session = Depends(get_db),
    benchmark_name: Optional[str] = Query(
        DEFAULT_BENCHMARK, description="Filter by benchmark name (default %CCCHYS)"
    ),
):
    q = select(VwHyStressLatest)
    if benchmark_name:
        q = q.where(VwHyStressLatest.benchmark_name == benchmark_name)
    q = q.order_by(desc(VwHyStressLatest.as_of_date)).limit(1)
    row = db.execute(q).scalars().first()
    if not row:
        return {"status": "empty"}
    z_val = float(row.hy_stress_z) if row.hy_stress_z is not None else None
    regime = _label_from_z(z_val)
    return {
        "as_of_date": row.as_of_date,
        "benchmark_name": row.benchmark_name,
        "hy_stress_raw": float(row.hy_stress_raw) if row.hy_stress_raw is not None else None,
        "hy_stress_ma": float(row.hy_stress_ma) if row.hy_stress_ma is not None else None,
        "hy_stress_z": z_val,
        "label": regime,
        "regime": regime,
    }


@router.get("/series")
def get_hy_stress_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    benchmark_name: Optional[str] = Query(
        DEFAULT_BENCHMARK, description="Filter by benchmark name (default %CCCHYS)"
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    filters = []
    if benchmark_name:
        filters.append(VwHyStress.benchmark_name == benchmark_name)
    if start_date:
        filters.append(VwHyStress.as_of_date >= start_date)
    if end_date:
        filters.append(VwHyStress.as_of_date <= end_date)

    order_col = asc(VwHyStress.as_of_date) if sort_order == "asc" else desc(VwHyStress.as_of_date)

    base = select(VwHyStress).where(and_(*filters)) if filters else select(VwHyStress)
    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = db.execute(base.order_by(order_col).offset(skip).limit(limit)).scalars().all()
    items = [
        {
            "as_of_date": r.as_of_date,
            "benchmark_name": r.benchmark_name,
            "hy_stress_raw": float(r.hy_stress_raw) if r.hy_stress_raw is not None else None,
            "hy_stress_ma": float(r.hy_stress_ma) if r.hy_stress_ma is not None else None,
            "hy_stress_z": (z := float(r.hy_stress_z) if r.hy_stress_z is not None else None),
            "label": (regime := _label_from_z(z)),
            "regime": regime,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
