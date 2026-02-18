from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimBenchmark, DimDate, FactBenchmarkPrice

from ..database import get_db

router = APIRouter(tags=["macro"], prefix="/api/v1/benchmarks")


def _canonical_names(name: str) -> list[str]:
    """Return a small set of canonicalized benchmark names (handles optional '$' prefix)."""
    raw = (name or "").strip()
    if not raw:
        return []
    base = raw[1:] if raw.startswith("$") else raw
    candidates = {raw, base, f"${base}"}
    return [c for c in candidates if c]


@router.get("/latest")
def get_benchmark_latest(
    db: Session = Depends(get_db),
    benchmark_name: str = Query(..., description="Benchmark name (e.g., $MOVE, $SKEW)"),
):
    names = _canonical_names(benchmark_name)
    if not names:
        return {"status": "empty"}

    stmt = (
        select(
            DimDate.full_date.label("as_of_date"),
            DimBenchmark.benchmark_name,
            DimBenchmark.currency_code,
            DimBenchmark.description,
            FactBenchmarkPrice.close_px,
            FactBenchmarkPrice.total_return_factor,
        )
        .select_from(FactBenchmarkPrice)
        .join(DimDate, DimDate.date_key == FactBenchmarkPrice.date_key)
        .join(DimBenchmark, DimBenchmark.benchmark_key == FactBenchmarkPrice.benchmark_key)
        .where(DimBenchmark.benchmark_name.in_(names))
        .order_by(desc(DimDate.full_date))
        .limit(1)
    )
    row = db.execute(stmt).first()
    if not row:
        return {"status": "empty"}

    return {
        "as_of_date": row.as_of_date,
        "benchmark_name": row.benchmark_name,
        "currency_code": row.currency_code,
        "description": row.description,
        "close_px": float(row.close_px) if row.close_px is not None else None,
        "total_return_factor": float(row.total_return_factor)
        if row.total_return_factor is not None
        else None,
    }


@router.get("/series")
def get_benchmark_series(
    db: Session = Depends(get_db),
    benchmark_name: str = Query(..., description="Benchmark name (e.g., $MOVE, $SKEW)"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(1000, ge=1, le=5000),
    skip: int = Query(0, ge=0),
):
    names = _canonical_names(benchmark_name)
    if not names:
        return {"items": [], "total_count": 0, "page": 1, "page_size": limit}

    q = (
        select(
            DimDate.full_date.label("as_of_date"),
            DimBenchmark.benchmark_name,
            FactBenchmarkPrice.close_px,
            FactBenchmarkPrice.total_return_factor,
        )
        .select_from(FactBenchmarkPrice)
        .join(DimDate, DimDate.date_key == FactBenchmarkPrice.date_key)
        .join(DimBenchmark, DimBenchmark.benchmark_key == FactBenchmarkPrice.benchmark_key)
        .where(DimBenchmark.benchmark_name.in_(names))
    )
    if start_date:
        q = q.where(DimDate.full_date >= start_date)
    if end_date:
        q = q.where(DimDate.full_date <= end_date)

    order_col = asc(DimDate.full_date) if sort_order == "asc" else desc(DimDate.full_date)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(order_col).offset(skip).limit(limit)).all()
    items = [
        {
            "as_of_date": r.as_of_date,
            "benchmark_name": r.benchmark_name,
            "close_px": float(r.close_px) if r.close_px is not None else None,
            "total_return_factor": float(r.total_return_factor)
            if r.total_return_factor is not None
            else None,
        }
        for r in rows
    ]
    return {
        "items": items,
        "total_count": int(total or 0),
        "page": (skip // limit) + 1,
        "page_size": limit,
    }
