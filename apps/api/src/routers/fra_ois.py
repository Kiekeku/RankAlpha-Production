from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, FactFraOis, VwFraOisLatest

from ..database import get_db


def _label_from_z(z: Optional[float]) -> str:
    if z is None:
        return "not_enough_data"
    if z <= 0:
        return "easy"
    if z <= 1:
        return "normal"
    if z <= 2:
        return "stressed"
    return "crisis"


router = APIRouter(tags=["rates"], prefix="/api/v1/fra-ois")


@router.get("/latest")
def get_fra_ois_latest(
    db: Session = Depends(get_db),
    fra_source: Optional[str] = Query(
        "SR3", max_length=4, description="FRA source root (SR1 or SR3)"
    ),
    start_months: Optional[int] = Query(
        None, ge=0, le=36, description="FRA start in months (e.g., 3 for 3x6)"
    ),
    end_months: Optional[int] = Query(
        None, ge=0, le=60, description="FRA end in months (e.g., 6 for 3x6)"
    ),
):
    filters = []
    if fra_source:
        filters.append(VwFraOisLatest.fra_source == fra_source.upper())
    if start_months is not None:
        filters.append(VwFraOisLatest.start_months == start_months)
    if end_months is not None:
        filters.append(VwFraOisLatest.end_months == end_months)

    base = select(VwFraOisLatest).where(and_(*filters)) if filters else select(VwFraOisLatest)
    rows = (
        db.execute(base.order_by(asc(VwFraOisLatest.start_months), asc(VwFraOisLatest.end_months)))
        .scalars()
        .all()
    )
    if not rows:
        return {"status": "empty"}
    return [
        {
            "as_of_date": r.as_of_date,
            "start_months": r.start_months,
            "end_months": r.end_months,
            "fra_source": r.fra_source,
            "fra_rate": float(r.fra_rate) if r.fra_rate is not None else None,
            "ois_forward": float(r.ois_forward) if r.ois_forward is not None else None,
            "spread_bp": float(r.spread_bp) if r.spread_bp is not None else None,
            "fra_ois_z": float(r.fra_ois_z) if r.fra_ois_z is not None else None,
            "regime": _label_from_z(float(r.fra_ois_z) if r.fra_ois_z is not None else None),
        }
        for r in rows
    ]


@router.get("/series")
def get_fra_ois_series(
    db: Session = Depends(get_db),
    fra_source: Optional[str] = Query(
        "SR3", max_length=4, description="FRA source root (SR1 or SR3)"
    ),
    start_months: Optional[int] = Query(None, ge=0, le=36),
    end_months: Optional[int] = Query(None, ge=0, le=60),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(500, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    filters = []
    if fra_source:
        filters.append(FactFraOis.fra_source == fra_source.upper())
    if start_months is not None:
        filters.append(FactFraOis.start_months == start_months)
    if end_months is not None:
        filters.append(FactFraOis.end_months == end_months)
    if start_date:
        filters.append(DimDate.full_date >= start_date)
    if end_date:
        filters.append(DimDate.full_date <= end_date)

    base = (
        select(
            DimDate.full_date.label("as_of_date"),
            FactFraOis.start_months,
            FactFraOis.end_months,
            FactFraOis.fra_source,
            FactFraOis.fra_rate,
            FactFraOis.ois_forward,
            FactFraOis.spread_bp,
            FactFraOis.fra_ois_z,
        )
        .select_from(FactFraOis)
        .join(DimDate, DimDate.date_key == FactFraOis.date_key)
    )

    if filters:
        base = base.where(and_(*filters))

    order_col = asc(DimDate.full_date) if sort_order == "asc" else desc(DimDate.full_date)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = db.execute(base.order_by(order_col).offset(skip).limit(limit)).all()
    items = [
        {
            "as_of_date": r.as_of_date,
            "start_months": r.start_months,
            "end_months": r.end_months,
            "fra_source": r.fra_source,
            "fra_rate": float(r.fra_rate) if r.fra_rate is not None else None,
            "ois_forward": float(r.ois_forward) if r.ois_forward is not None else None,
            "spread_bp": float(r.spread_bp) if r.spread_bp is not None else None,
            "fra_ois_z": float(r.fra_ois_z) if r.fra_ois_z is not None else None,
            "regime": _label_from_z(float(r.fra_ois_z) if r.fra_ois_z is not None else None),
        }
        for r in rows
    ]
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
