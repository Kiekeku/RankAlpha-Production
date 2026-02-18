from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    DimStock,
    FactTechnicalIndicator,
    VwLatestTechnicals,
)

from ..database import get_db
from ..utils.company import clean_company_name

router = APIRouter(tags=["technicals"], prefix="/api/v1/technicals")


@router.get("/latest")
def latest_snapshot(symbol: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.execute(
        select(VwLatestTechnicals)
        .join(DimStock, DimStock.symbol == VwLatestTechnicals.symbol)
        .where(VwLatestTechnicals.symbol == symbol.upper(), DimStock.is_active.is_(True))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="No latest technicals found for symbol")
    return _snap_to_dict(row)


@router.get("/series")
def series(
    symbol: str,
    indicators: Optional[str] = Query(
        None, description="Comma-separated indicator codes (e.g., SMA20,RSI14)"
    ),
    days: int = Query(120, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    codes: Optional[List[str]] = None
    if indicators:
        codes = [c.strip().upper() for c in indicators.split(",") if c.strip()]

    # Resolve date range using DimDate
    cutoff = date.today() - timedelta(days=days)
    # Find stock_key
    stock = db.execute(
        select(DimStock).where(DimStock.symbol == symbol.upper(), DimStock.is_active.is_(True))
    ).scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="Symbol not found")

    q = (
        select(FactTechnicalIndicator, DimDate.full_date)
        .join(DimDate, DimDate.date_key == FactTechnicalIndicator.date_key)
        .where(FactTechnicalIndicator.stock_key == stock.stock_key)
        .where(DimDate.full_date >= cutoff)
    )
    if codes:
        q = q.where(FactTechnicalIndicator.indicator_code.in_(codes))
    q = q.order_by(DimDate.full_date.asc())
    rows = db.execute(q).all()

    out: Dict[str, List[Dict[str, Any]]] = {}
    for fti, full_date in rows:
        code = fti.indicator_code.upper()
        out.setdefault(code, []).append(
            {"date": str(full_date), "value": float(fti.value) if fti.value is not None else None}
        )
    return {"symbol": symbol.upper(), "series": out}


def _snap_to_dict(r: VwLatestTechnicals) -> Dict[str, Any]:
    def f(x):
        return float(x) if x is not None else None

    return {
        "as_of_date": str(r.as_of_date),
        "symbol": r.symbol,
        "company_name": clean_company_name(r.company_name),
        "sma20": f(r.sma20),
        "sma50": f(r.sma50),
        "sma200": f(r.sma200),
        "ema12": f(r.ema12),
        "ema26": f(r.ema26),
        "rsi14": f(r.rsi14),
        "atr14": f(r.atr14),
        "bb_upper": f(r.bb_upper),
        "bb_middle": f(r.bb_middle),
        "bb_lower": f(r.bb_lower),
        "macd": f(r.macd),
        "macd_signal": f(r.macd_signal),
        "macd_hist": f(r.macd_hist),
        "ret_5d": f(r.ret_5d),
        "ret_20d": f(r.ret_20d),
        "ret_60d": f(r.ret_60d),
        "ret_120d": f(r.ret_120d),
        "vol_z20": f(r.vol_z20),
        "dist_52w_high": f(r.dist_52w_high),
    }
