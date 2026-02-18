from __future__ import annotations

from datetime import date
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimAssetType,
    DimDate,
    DimScoreType,
    DimStock,
    FactScoreHistory,
)

from ..database import get_db

router = APIRouter(tags=["money_flow"], prefix="/api/v1/money-flow")


# Simple sector -> SPDR ETF map (best-effort; used for labeling)
_SECTOR_TO_ETF = {
    "ENERGY": "XLE",
    "MATERIALS": "XLB",
    "CAPITAL GOODS": "XLI",
    "COMMERCIAL & PROFESSIONAL SERVICES": "XLI",
    "TRANSPORTATION": "XLI",
    "INDUSTRIALS": "XLI",
    "SOFTWARE & SERVICES": "XLK",
    "TECHNOLOGY HARDWARE & EQUIPMENT": "XLK",
    "SEMICONDUCTORS & SEMICONDUCTOR EQUIPMENT": "XLK",
    "INFORMATION TECHNOLOGY": "XLK",
    "MEDIA & ENTERTAINMENT": "XLC",
    "TELECOMMUNICATION SERVICES": "XLC",
    "COMMUNICATION SERVICES": "XLC",
    "CONSUMER SERVICES": "XLY",
    "CONSUMER DISCRETIONARY DISTRIBUTION & RETAIL": "XLY",
    "CONSUMER DURABLES & APPAREL": "XLY",
    "AUTOMOBILES & COMPONENTS": "XLY",
    "CONSUMER DISCRETIONARY": "XLY",
    "FOOD BEVERAGE & TOBACCO": "XLP",
    "HOUSEHOLD & PERSONAL PRODUCTS": "XLP",
    "CONSUMER STAPLES DISTRIBUTION & RETAIL": "XLP",
    "CONSUMER STAPLES": "XLP",
    "BANKS": "XLF",
    "INSURANCE": "XLF",
    "FINANCIAL SERVICES": "XLF",
    "FINANCIALS": "XLF",
    "HEALTH CARE EQUIPMENT & SERVICES": "XLV",
    "PHARMACEUTICALS, BIOTECHNOLOGY & LIFE SCIENCES": "XLV",
    "HEALTH CARE": "XLV",
    "EQUITY REAL ESTATE INVESTMENT TRUSTS (REITS)": "XLRE",
    "REAL ESTATE MANAGEMENT & DEVELOPMENT": "XLRE",
    "REAL ESTATE": "XLRE",
    "UTILITIES": "XLU",
}


def _sector_etf_label(sector: Optional[str]) -> Optional[str]:
    if sector is None:
        return None
    key = sector.strip().upper()
    if not key:
        return None
    # direct match
    if key in _SECTOR_TO_ETF:
        return _SECTOR_TO_ETF[key]
    # fuzzy buckets
    if "REAL ESTATE" in key:
        return "XLRE"
    if "HEALTH" in key:
        return "XLV"
    if "TECH" in key or "SOFTWARE" in key or "SEMICON" in key or "HARDWARE" in key:
        return "XLK"
    if "FINANC" in key or "BANK" in key or "INSURANCE" in key:
        return "XLF"
    if "ENERG" in key:
        return "XLE"
    if "MATERIAL" in key or "METAL" in key or "CHEM" in key:
        return "XLB"
    if "INDUSTRIAL" in key or "CAPITAL GOODS" in key or "TRANSPORT" in key:
        return "XLI"
    if "UTILIT" in key:
        return "XLU"
    if (
        "CONSUMER STAPLES" in key
        or "FOOD" in key
        or "BEVERAGE" in key
        or "PERSONAL PRODUCTS" in key
    ):
        return "XLP"
    if "CONSUMER" in key or "RETAIL" in key or "APPAREL" in key or "AUTOMOBILE" in key:
        return "XLY"
    if "MEDIA" in key or "TELE" in key or "COMMUNICATION" in key:
        return "XLC"
    return None


def _latest_mf_date(db: Session, score_type_key: int) -> Optional[date]:
    return db.execute(
        select(func.max(DimDate.full_date))
        .join(FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key)
        .where(FactScoreHistory.score_type_key == score_type_key)
    ).scalar()


@router.get("/sectors")
def money_flow_sectors(db: Session = Depends(get_db)) -> Dict[str, object]:
    # Resolve score type
    st = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == "money flow score")
    ).scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=404, detail="money flow score not available")

    latest_date = _latest_mf_date(db, st.score_type_key)
    if not latest_date:
        raise HTTPException(status_code=404, detail="No money flow data available")

    # Aggregate per sector, equities only, sector present
    rows = db.execute(
        select(
            DimStock.sector,
            func.count(FactScoreHistory.score).label("n"),
            func.avg(FactScoreHistory.score).label("avg_score"),
        )
        .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .join(DimAssetType, DimAssetType.asset_type_key == DimStock.asset_type_key, isouter=True)
        .where(
            and_(
                FactScoreHistory.score_type_key == st.score_type_key,
                DimDate.full_date == latest_date,
                DimStock.is_active.is_(True),
                DimStock.sector.is_not(None),
                func.trim(DimStock.sector) != "",
                func.upper(func.trim(DimStock.sector)) != "UNKNOWN",
                func.coalesce(DimAssetType.asset_type_name, "equity").ilike("equity"),
            )
        )
        .group_by(DimStock.sector)
        .order_by(func.avg(FactScoreHistory.score).desc())
    ).all()

    sectors = [
        {
            "sector": sec,
            "sector_etf": _sector_etf_label(sec),
            "avg_score": float(avg) if avg is not None else None,
            "n_stocks": int(n),
        }
        for sec, n, avg in rows
    ]

    return {"as_of_date": str(latest_date), "sectors": sectors}


@router.get("/sectors/series")
def money_flow_sectors_series(
    days: int = Query(90, ge=1, le=2000, description="Number of trailing trading days"),
    sector: Optional[str] = Query(None, description="Optional exact sector filter"),
    db: Session = Depends(get_db),
) -> Dict[str, object]:
    """
    Return sector-level money flow time series over the last N trading days.

    Computes cross-sectional averages of per-stock `money flow score` by (date, sector)
    for equities only. Intended for sector rotation / momentum analysis.
    """
    st = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == "money flow score")
    ).scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=404, detail="money flow score not available")

    latest_date = _latest_mf_date(db, st.score_type_key)
    if not latest_date:
        raise HTTPException(status_code=404, detail="No money flow data available")

    date_keys_subq = (
        select(DimDate.date_key)
        .where(DimDate.is_trading_day.is_(True), DimDate.full_date <= latest_date)
        .order_by(DimDate.full_date.desc())
        .limit(days)
        .subquery()
    )

    q = (
        select(
            DimDate.full_date.label("date"),
            DimStock.sector,
            func.count(FactScoreHistory.score).label("n_stocks"),
            func.avg(FactScoreHistory.score).label("avg_score"),
        )
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
        .join(DimAssetType, DimAssetType.asset_type_key == DimStock.asset_type_key, isouter=True)
        .where(
            and_(
                FactScoreHistory.score_type_key == st.score_type_key,
                FactScoreHistory.date_key.in_(select(date_keys_subq.c.date_key)),
                DimStock.is_active.is_(True),
                DimStock.sector.is_not(None),
                func.trim(DimStock.sector) != "",
                func.upper(func.trim(DimStock.sector)) != "UNKNOWN",
                func.coalesce(DimAssetType.asset_type_name, "equity").ilike("equity"),
            )
        )
        .group_by(DimDate.full_date, DimStock.sector)
        .order_by(DimDate.full_date.asc(), DimStock.sector.asc())
    )
    if sector:
        q = q.where(DimStock.sector == sector.strip())

    rows = db.execute(q).all()
    if not rows:
        raise HTTPException(
            status_code=404, detail="No money flow series data available for given range"
        )

    series = [
        {
            "date": str(dt),
            "sector": sec,
            "sector_etf": _sector_etf_label(sec),
            "avg_score": float(avg) if avg is not None else None,
            "n_stocks": int(n),
        }
        for dt, sec, n, avg in rows
    ]

    return {
        "as_of_date": str(latest_date),
        "trading_days": days,
        "series": series,
    }


@router.get("/sectors/{sector}")
def money_flow_sector_detail(
    sector: str,
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, object]:
    # Resolve score type
    st = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == "money flow score")
    ).scalar_one_or_none()
    if not st:
        raise HTTPException(status_code=404, detail="money flow score not available")

    latest_date = _latest_mf_date(db, st.score_type_key)
    if not latest_date:
        raise HTTPException(status_code=404, detail="No money flow data available")

    target_sector = sector.strip()
    rows = db.execute(
        select(
            DimStock.symbol,
            DimStock.company_name,
            DimStock.sector,
            FactScoreHistory.score,
        )
        .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .join(DimAssetType, DimAssetType.asset_type_key == DimStock.asset_type_key, isouter=True)
        .where(
            and_(
                FactScoreHistory.score_type_key == st.score_type_key,
                DimDate.full_date == latest_date,
                DimStock.is_active.is_(True),
                func.coalesce(DimAssetType.asset_type_name, "equity").ilike("equity"),
                DimStock.sector == target_sector,
            )
        )
        .order_by(desc(FactScoreHistory.score))
        .limit(limit)
    ).all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No money flow data for sector '{sector}'")

    return {
        "sector": target_sector,
        "sector_etf": _sector_etf_label(target_sector),
        "as_of_date": str(latest_date),
        "stocks": [
            {
                "symbol": sym,
                "company_name": name,
                "sector": sec,
                "score": float(score),
            }
            for sym, name, sec, score in rows
        ],
    }
