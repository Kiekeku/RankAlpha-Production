from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import VwRiskFreeRate

from ..database import get_db

router = APIRouter(tags=["rates"], prefix="/api/v1/rates")

SUPPORTED_TENORS = ("O/N", "1Y", "2Y", "5Y", "10Y", "20Y")
TENOR_PATTERN = r"^(?i:(" + "|".join(SUPPORTED_TENORS) + r"))$"


def _parse_tenors(raw: Optional[str]) -> List[str]:
    if not raw:
        return list(SUPPORTED_TENORS)
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    out: List[str] = []
    for p in parts:
        if p in SUPPORTED_TENORS and p not in out:
            out.append(p)
    return out


@router.get("/treasury/latest")
def treasury_latest(
    db: Session = Depends(get_db),
    tenors: Optional[str] = Query(
        None,
        description="Comma-separated tenor labels (default: 1Y,2Y,5Y,10Y,20Y)",
    ),
):
    tenor_list = _parse_tenors(tenors)
    if not tenor_list:
        return {"status": "empty"}

    tenor_list_lc = [t.lower() for t in tenor_list]
    subq = (
        select(
            VwRiskFreeRate.tenor_label,
            VwRiskFreeRate.rate_date,
            VwRiskFreeRate.rate_pct,
            func.row_number()
            .over(
                partition_by=func.lower(VwRiskFreeRate.tenor_label),
                order_by=desc(VwRiskFreeRate.rate_date),
            )
            .label("rn"),
        )
        .where(func.lower(VwRiskFreeRate.tenor_label).in_(tenor_list_lc))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.tenor_label, subq.c.rate_date, subq.c.rate_pct).where(subq.c.rn == 1)
    ).all()
    if not rows:
        return {"status": "empty"}

    by_tenor = {str(r.tenor_label).upper(): r for r in rows if r.tenor_label}
    payload: Dict[str, Dict[str, object]] = {}
    ref_date: Optional[date] = None
    for tenor in tenor_list:
        match = by_tenor.get(tenor.upper())
        payload[tenor] = {
            "as_of_date": match.rate_date if match else None,
            "rate_pct": float(match.rate_pct) if (match and match.rate_pct is not None) else None,
        }
        d = payload[tenor]["as_of_date"]
        if isinstance(d, date) and (ref_date is None or d > ref_date):
            ref_date = d

    y2 = payload.get("2Y", {}).get("rate_pct")
    y10 = payload.get("10Y", {}).get("rate_pct")
    slope_2s10s = None
    if isinstance(y2, (int, float)) and isinstance(y10, (int, float)):
        slope_2s10s = float(y10) - float(y2)

    return {
        "as_of_date": ref_date,
        "rates": payload,
        "curve": {
            "slope_2s10s_pct": slope_2s10s,
            "slope_2s10s_bp": (slope_2s10s * 100.0) if slope_2s10s is not None else None,
        },
    }


@router.get("/treasury/series")
def treasury_series(
    db: Session = Depends(get_db),
    tenor: str = Query(..., pattern=TENOR_PATTERN),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    tenor_norm = tenor.strip().upper()
    q = select(VwRiskFreeRate).where(func.lower(VwRiskFreeRate.tenor_label) == tenor_norm.lower())
    if start_date:
        q = q.where(VwRiskFreeRate.rate_date >= start_date)
    if end_date:
        q = q.where(VwRiskFreeRate.rate_date <= end_date)

    order_col = (
        asc(VwRiskFreeRate.rate_date) if sort_order == "asc" else desc(VwRiskFreeRate.rate_date)
    )
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).scalars().all()

    items = [
        {
            "as_of_date": r.rate_date,
            "rate_pct": float(r.rate_pct) if r.rate_pct is not None else None,
        }
        for r in rows
    ]
    return {
        "tenor": tenor_norm,
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
