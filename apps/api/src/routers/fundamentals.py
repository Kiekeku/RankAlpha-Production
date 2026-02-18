from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, DimFinMetric, DimSource, DimStock, FactFinFundamental

from ..database import get_db

router = APIRouter(tags=["fundamentals"], prefix="/api/v1/fundamentals")

# Standard swing-trading-friendly panel defaults (TTM + near-term deltas + size)
DEFAULT_METRIC_CODES: list[str] = [
    "mktcap",
    "beta",
    "sharesoutstanding",
    "peexclxor",
    "ttmpr2rev",
    "ttmprfcfps",
    "revchngyr",
    "epschngyr",
    "ttmgrosmgn",
    "ttmopmgn",
    "netdebt_a",
    "qcurratio",
]


@router.get("/latest")
def latest_snapshot(
    symbol: str,
    metrics: Optional[str] = Query(
        None,
        description="Comma-separated metric codes. Defaults to the stock-detail modal set.",
        examples=["mktcap,beta,peexclxor,ttmpr2rev"],
    ),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    normalized = (symbol or "").strip().upper()
    if not normalized:
        raise HTTPException(status_code=400, detail="symbol is required")

    stock = db.execute(
        select(DimStock.stock_key).where(
            DimStock.symbol == normalized, DimStock.is_active.is_(True)
        )
    ).scalar_one_or_none()
    if stock is None:
        raise HTTPException(status_code=404, detail="Symbol not found")

    requested_codes = DEFAULT_METRIC_CODES
    if metrics:
        requested_codes = [c.strip() for c in metrics.split(",") if c.strip()]
    requested_codes = [c.lower() for c in requested_codes]
    if not requested_codes:
        raise HTTPException(status_code=400, detail="No metric codes requested")

    metric_rows = (
        db.execute(
            select(DimFinMetric).where(func.lower(DimFinMetric.metric_code).in_(requested_codes))
        )
        .scalars()
        .all()
    )
    metric_by_code = {m.metric_code.lower(): m for m in metric_rows}
    metric_keys = [m.metric_key for m in metric_rows]
    if not metric_keys:
        raise HTTPException(status_code=404, detail="No matching metrics found")

    ranked = (
        select(
            FactFinFundamental.metric_key.label("metric_key"),
            FactFinFundamental.metric_value.label("metric_value"),
            FactFinFundamental.ttm_flag.label("ttm_flag"),
            FactFinFundamental.fiscal_year.label("fiscal_year"),
            FactFinFundamental.fiscal_period.label("fiscal_period"),
            DimDate.full_date.label("as_of_date"),
            FactFinFundamental.source_key.label("source_key"),
            func.row_number()
            .over(
                partition_by=FactFinFundamental.metric_key,
                order_by=desc(DimDate.full_date),
            )
            .label("rn"),
        )
        .join(DimDate, DimDate.date_key == FactFinFundamental.date_key)
        .where(
            FactFinFundamental.stock_key == stock,
            FactFinFundamental.metric_key.in_(metric_keys),
        )
    ).subquery()

    latest_rows = db.execute(
        select(
            DimFinMetric.metric_code,
            ranked.c.metric_value,
            ranked.c.ttm_flag,
            ranked.c.fiscal_year,
            ranked.c.fiscal_period,
            ranked.c.as_of_date,
            DimSource.source_name,
            DimSource.version,
        )
        .join(DimFinMetric, DimFinMetric.metric_key == ranked.c.metric_key)
        .join(DimSource, DimSource.source_key == ranked.c.source_key)
        .where(ranked.c.rn == 1)
    ).all()

    latest_by_code: dict[str, dict[str, Any]] = {}
    latest_dates: list[date] = []
    latest_sources: list[str] = []
    latest_versions: list[str] = []
    for (
        metric_code,
        metric_value,
        ttm_flag,
        fiscal_year,
        fiscal_period,
        as_of_date,
        source_name,
        source_version,
    ) in latest_rows:
        code = str(metric_code).lower()
        latest_by_code[code] = {
            "value": float(metric_value) if metric_value is not None else None,
            "ttm_flag": bool(ttm_flag) if ttm_flag is not None else None,
            "fiscal_year": int(fiscal_year) if fiscal_year is not None else None,
            "fiscal_period": str(fiscal_period) if fiscal_period is not None else None,
            "as_of_date": as_of_date,
            "source_name": str(source_name) if source_name is not None else None,
            "source_version": str(source_version) if source_version is not None else None,
        }
        if as_of_date is not None:
            latest_dates.append(as_of_date)
        if source_name:
            latest_sources.append(str(source_name))
        if source_version:
            latest_versions.append(str(source_version))

    items: List[Dict[str, Any]] = []
    for code in requested_codes:
        meta = metric_by_code.get(code)
        if not meta:
            continue
        row = latest_by_code.get(code, {})
        as_of = row.get("as_of_date")
        items.append(
            {
                "metric_code": meta.metric_code,
                "metric_name": meta.metric_name,
                "stmt_code": meta.stmt_code,
                "default_unit": meta.default_unit,
                "value": row.get("value"),
                "as_of_date": str(as_of) if as_of is not None else None,
                "fiscal_year": row.get("fiscal_year"),
                "fiscal_period": row.get("fiscal_period"),
                "ttm_flag": row.get("ttm_flag"),
                "source_name": row.get("source_name"),
                "source_version": row.get("source_version"),
            }
        )

    unique_sources = sorted({s for s in latest_sources if s})
    unique_versions = sorted({v for v in latest_versions if v})
    latest_source_name = (
        unique_sources[0] if len(unique_sources) == 1 else ("Mixed" if unique_sources else None)
    )
    latest_source_version = unique_versions[0] if len(unique_versions) == 1 else None

    return {
        "symbol": normalized,
        "latest_as_of_date": str(max(latest_dates)) if latest_dates else None,
        "latest_source_name": latest_source_name,
        "latest_source_version": latest_source_version,
        "sources": unique_sources,
        "metrics": items,
    }
