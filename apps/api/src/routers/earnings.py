from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import DimDate, DimStock, FactStockNextEarnings, VwFinFundamentals

from ..database import get_db

router = APIRouter(tags=["earnings"], prefix="/api/v1/earnings")

DEFAULT_WINDOW_DAYS = 3
DEFAULT_MIN_MARKET_CAP = 2_000_000_000
DEFAULT_LIMIT = None
try:
    _MARKET_TZ = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    _MARKET_TZ = None


def _market_today() -> date:
    """Return today's date in the market timezone (US/Eastern)."""
    if _MARKET_TZ is None:
        return date.today()
    return datetime.now(tz=_MARKET_TZ).date()


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


class UpcomingEarningsItem(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    earnings_date: date
    earnings_time: Optional[str] = None
    earnings_source: Optional[str] = None
    market_cap: Optional[float] = None


class UpcomingEarningsResponse(BaseModel):
    as_of: date
    window_days: int
    min_market_cap: float
    items: List[UpcomingEarningsItem]


@router.get("/upcoming", response_model=UpcomingEarningsResponse)
def get_upcoming_earnings(
    db: Session = Depends(get_db),
    days: int = Query(
        DEFAULT_WINDOW_DAYS,
        ge=1,
        le=30,
        description="Trading days to include (starting today when applicable)",
    ),
    min_market_cap: float = Query(
        DEFAULT_MIN_MARKET_CAP,
        ge=0,
        description="Minimum market cap in USD (uses fundamentals mktcap)",
    ),
    limit: Optional[int] = Query(DEFAULT_LIMIT, ge=1, le=500, description="Max rows to return"),
):
    today = _market_today()
    trading_days = (
        db.execute(
            select(DimDate.full_date)
            .where(and_(DimDate.full_date >= today, DimDate.is_trading_day.is_(True)))
            .order_by(DimDate.full_date.asc())
            .limit(days)
        )
        .scalars()
        .all()
    )
    if trading_days:
        end_date = trading_days[-1]
    else:
        end_date = today + timedelta(days=max(days, 1) - 1)

    latest_mktcap_subq = (
        select(
            VwFinFundamentals.symbol.label("symbol"),
            VwFinFundamentals.metric_value.label("metric_value"),
            func.row_number()
            .over(
                partition_by=VwFinFundamentals.symbol,
                order_by=VwFinFundamentals.as_of_date.desc(),
            )
            .label("rn"),
        )
        .where(VwFinFundamentals.metric_code == "mktcap")
        .subquery()
    )

    market_cap_value = latest_mktcap_subq.c.metric_value * 1_000_000

    query = (
        select(
            DimStock.symbol,
            DimStock.company_name,
            FactStockNextEarnings.earnings_date,
            FactStockNextEarnings.earnings_time,
            FactStockNextEarnings.earnings_source,
            market_cap_value.label("market_cap"),
        )
        .join(
            FactStockNextEarnings,
            FactStockNextEarnings.stock_key == DimStock.stock_key,
        )
        .join(
            latest_mktcap_subq,
            func.upper(latest_mktcap_subq.c.symbol) == func.upper(DimStock.symbol),
        )
        .where(
            and_(
                DimStock.is_active.is_(True),
                FactStockNextEarnings.earnings_date >= today,
                FactStockNextEarnings.earnings_date <= end_date,
                latest_mktcap_subq.c.rn == 1,
                market_cap_value >= min_market_cap,
            )
        )
        .order_by(
            FactStockNextEarnings.earnings_date.asc(),
            market_cap_value.desc(),
        )
    )
    if limit:
        query = query.limit(limit)

    rows = db.execute(query).all()

    items = [
        UpcomingEarningsItem(
            symbol=str(symbol).upper(),
            company_name=company_name,
            earnings_date=earnings_date,
            earnings_time=earnings_time,
            earnings_source=earnings_source,
            market_cap=_to_float(market_cap),
        )
        for symbol, company_name, earnings_date, earnings_time, earnings_source, market_cap in rows
    ]

    return UpcomingEarningsResponse(
        as_of=today,
        window_days=days,
        min_market_cap=min_market_cap,
        items=items,
    )
