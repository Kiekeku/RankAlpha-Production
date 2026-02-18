from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    VwRegimeMarketStructure,
)

from ..database import get_db

router = APIRouter(tags=["regime"], prefix="/api/v1/market-structure")


@router.get("/latest")
def get_market_structure_latest(db: Session = Depends(get_db)):
    q = select(VwRegimeMarketStructure).order_by(desc(VwRegimeMarketStructure.as_of_date)).limit(1)
    row = db.execute(q).scalars().first()
    if not row:
        return {"status": "empty"}
    return {
        "as_of_date": row.as_of_date,
        "trend_raw": float(row.trend_raw or 0.0),
        "rv20_ann": float(row.rv20_ann or 0.0),
        "corr_pca1_share": float(row.corr_pca1_share or 0.0),
        "disp_cs_mad": float(row.disp_cs_mad or 0.0),
        "trend_z": float(row.trend_z or 0.0),
        "rv20_z": float(row.rv20_z or 0.0),
        "corr_z": float(row.corr_z or 0.0),
        "disp_z": float(row.disp_z or 0.0),
        "label": row.label,
    }


@router.get("/series")
def get_market_structure_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    filters = []
    if start_date:
        filters.append(VwRegimeMarketStructure.as_of_date >= start_date)
    if end_date:
        filters.append(VwRegimeMarketStructure.as_of_date <= end_date)
    order_col = (
        asc(VwRegimeMarketStructure.as_of_date)
        if sort_order == "asc"
        else desc(VwRegimeMarketStructure.as_of_date)
    )

    base = (
        select(VwRegimeMarketStructure).where(and_(*filters))
        if filters
        else select(VwRegimeMarketStructure)
    )
    count_stmt = select(func.count()).select_from(base.subquery())
    total = db.execute(count_stmt).scalar_one()

    rows = db.execute(base.order_by(order_col).offset(skip).limit(limit)).scalars().all()
    items = [
        {
            "as_of_date": r.as_of_date,
            "trend_raw": float(r.trend_raw or 0.0),
            "rv20_ann": float(r.rv20_ann or 0.0),
            "corr_pca1_share": float(r.corr_pca1_share or 0.0),
            "disp_cs_mad": float(r.disp_cs_mad or 0.0),
            "trend_z": float(r.trend_z or 0.0),
            "rv20_z": float(r.rv20_z or 0.0),
            "corr_z": float(r.corr_z or 0.0),
            "disp_z": float(r.disp_z or 0.0),
            "label": r.label,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
