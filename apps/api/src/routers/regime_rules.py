from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, asc, desc, exists, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, FactRegimeRules, FactScreenerRank

from ..database import get_db

router = APIRouter(tags=["screener"], prefix="/api/v1/screener")


def _base_query():
    return select(
        DimDate.full_date.label("as_of_date"),
        FactRegimeRules.date_key,
        FactRegimeRules.mb,
        FactRegimeRules.bb,
        FactRegimeRules.mri,
        FactRegimeRules.db,
        FactRegimeRules.tt,
        FactRegimeRules.mrp,
        FactRegimeRules.rop,
        FactRegimeRules.dt,
        FactRegimeRules.ps,
        FactRegimeRules.tb,
        FactRegimeRules.rs,
        FactRegimeRules.rs_smooth,
        FactRegimeRules.label,
        FactRegimeRules.tags,
        FactRegimeRules.config_version,
    ).join(DimDate, DimDate.date_key == FactRegimeRules.date_key)


def _max_screener_rank_date_key(db: Session) -> int | None:
    return db.execute(select(func.max(FactScreenerRank.date_key))).scalar_one_or_none()


@router.get("/regime-rules/latest")
def get_regime_rules_latest(db: Session = Depends(get_db)):
    max_rank_dk = _max_screener_rank_date_key(db)
    stmt = _base_query()
    if max_rank_dk is not None:
        stmt = stmt.where(FactRegimeRules.date_key <= max_rank_dk)
    # Exclude days where screener ranks are missing (prevents placeholder-zero rows).
    stmt = stmt.where(
        exists(select(1).where(FactScreenerRank.date_key == FactRegimeRules.date_key))
    )
    stmt = stmt.order_by(desc(FactRegimeRules.date_key)).limit(1)
    row = db.execute(stmt).mappings().first()
    if not row:
        return {"status": "empty"}
    return {
        "as_of_date": row["as_of_date"],
        "label": row["label"],
        "tags": row["tags"] or [],
        "config_version": row["config_version"],
        "rs": float(row["rs"] or 0.0),
        "rs_smooth": float(row["rs_smooth"] or 0.0),
        "tt": float(row["tt"] or 0.0),
        "mrp": float(row["mrp"] or 0.0),
        "rop": float(row["rop"] or 0.0),
        "dt": float(row["dt"] or 0.0),
        "mb": float(row["mb"] or 0.0),
        "bb": float(row["bb"] or 0.0),
        "mri": float(row["mri"] or 0.0),
        "db": float(row["db"] or 0.0),
        "ps": float(row["ps"] or 0.0),
        "tb": float(row["tb"] or 0.0),
    }


@router.get("/regime-rules/series")
def get_regime_rules_series(
    db: Session = Depends(get_db),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    skip: int = Query(0, ge=0),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
):
    filters = []
    max_rank_dk = _max_screener_rank_date_key(db)
    if max_rank_dk is not None:
        filters.append(FactRegimeRules.date_key <= max_rank_dk)
    filters.append(exists(select(1).where(FactScreenerRank.date_key == FactRegimeRules.date_key)))
    if start_date:
        filters.append(DimDate.full_date >= start_date)
    if end_date:
        filters.append(DimDate.full_date <= end_date)

    stmt = _base_query()
    if filters:
        stmt = stmt.where(and_(*filters))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar_one()

    order_col = asc(DimDate.full_date) if sort_order == "asc" else desc(DimDate.full_date)
    rows = db.execute(stmt.order_by(order_col).offset(skip).limit(limit)).mappings().all()
    items: List[dict] = []
    for row in rows:
        items.append(
            {
                "as_of_date": row["as_of_date"],
                "label": row["label"],
                "tags": row["tags"] or [],
                "config_version": row["config_version"],
                "rs": float(row["rs"] or 0.0),
                "rs_smooth": float(row["rs_smooth"] or 0.0),
                "tt": float(row["tt"] or 0.0),
                "mrp": float(row["mrp"] or 0.0),
                "rop": float(row["rop"] or 0.0),
                "dt": float(row["dt"] or 0.0),
                "mb": float(row["mb"] or 0.0),
                "bb": float(row["bb"] or 0.0),
                "mri": float(row["mri"] or 0.0),
                "db": float(row["db"] or 0.0),
                "ps": float(row["ps"] or 0.0),
                "tb": float(row["tb"] or 0.0),
            }
        )

    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
