from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    DimScoreType,
    DimStock,
    FactScoreHistory,
)

from ..database import get_db
from ..utils.company import CompanyNameSanitizerMixin, clean_company_name


class SignalScore(CompanyNameSanitizerMixin, BaseModel):
    symbol: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    score_type: str
    score: float
    rank: Optional[int] = None
    date: date
    percentile: Optional[float] = None


class SignalsLeaderboard(BaseModel):
    signals: List[SignalScore]
    total_count: int
    page: int
    page_size: int
    as_of_date: date


class SignalComparison(BaseModel):
    symbol: str
    signals: Dict[str, float]
    average_score: float
    recommendation: str


router = APIRouter(tags=["signals"], prefix="/api/v1/signals")


@router.get("/leaderboard", response_model=SignalsLeaderboard)
def get_signals_leaderboard(
    db: Session = Depends(get_db),
    signal_type: str = Query("momentum raw score", description="Type of signal/score"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=500),
    sector: Optional[str] = None,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    date_str: Optional[str] = None,
):
    """
    Get signals leaderboard with pagination and filtering.
    """
    # Parse date or use latest
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        # Get latest date
        latest_date_result = db.execute(
            select(func.max(DimDate.full_date)).join(
                FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key
            )
        ).scalar()

        if not latest_date_result:
            raise HTTPException(status_code=404, detail="No data available")

        target_date = latest_date_result

    # Get score type
    score_type = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == signal_type)
    ).scalar_one_or_none()

    if not score_type:
        # Get available score types
        available_types = (
            db.execute(select(DimScoreType.score_type_name).distinct()).scalars().all()
        )

        raise HTTPException(
            status_code=404,
            detail=f"Signal type '{signal_type}' not found. Available types: {', '.join(available_types)}",
        )

    # Build base query for the full (unfiltered) population on date + signal type.
    base_query = (
        select(
            DimStock.symbol.label("symbol"),
            DimStock.company_name.label("company_name"),
            DimStock.sector.label("sector"),
            FactScoreHistory.score.label("score"),
            DimDate.full_date.label("full_date"),
        )
        .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .where(
            and_(
                FactScoreHistory.score_type_key == score_type.score_type_key,
                DimDate.full_date == target_date,
                DimStock.is_active.is_(True),
            )
        )
    )

    # Percentiles should remain globally comparable even when filters apply.
    global_count_query = select(func.count()).select_from(base_query.subquery())
    global_total_count = int(db.execute(global_count_query).scalar() or 0)

    ranked_query = base_query.add_columns(
        func.rank().over(order_by=desc(FactScoreHistory.score)).label("global_rank")
    ).subquery()

    query = select(
        ranked_query.c.symbol,
        ranked_query.c.company_name,
        ranked_query.c.sector,
        ranked_query.c.score,
        ranked_query.c.full_date,
        ranked_query.c.global_rank,
    )

    # Apply filters for returned leaderboard rows/pagination.
    if sector:
        query = query.where(ranked_query.c.sector == sector)

    if min_score is not None:
        query = query.where(ranked_query.c.score >= min_score)

    if max_score is not None:
        query = query.where(ranked_query.c.score <= max_score)

    # Get total count before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total_count = int(db.execute(count_query).scalar() or 0)

    paged_query = query.order_by(desc(ranked_query.c.score)).offset(skip).limit(limit)

    results = db.execute(paged_query).all()

    signals = []
    for i, (symbol, company_name, sector_name, score, date_val, global_rank) in enumerate(results):
        percentile = None
        if global_total_count > 0 and global_rank is not None:
            percentile = 100.0 * (1.0 - ((float(global_rank) - 1.0) / float(global_total_count)))

        signals.append(
            SignalScore(
                symbol=symbol,
                company_name=company_name,
                sector=sector_name,
                score_type=signal_type,
                score=float(score),
                rank=skip + i + 1,
                date=date_val,
                percentile=percentile,
            )
        )

    return SignalsLeaderboard(
        signals=signals,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        as_of_date=target_date,
    )


@router.get("/compare", response_model=List[SignalComparison])
def compare_signals(
    db: Session = Depends(get_db),
    symbols: str = Query(..., description="Comma-separated list of symbols"),
    signal_types: Optional[str] = Query(None, description="Comma-separated signal types"),
):
    """
    Compare multiple signals across stocks.
    """
    symbol_list = [(s or "").strip().upper() for s in symbols.split(",")]
    symbol_order = list(dict.fromkeys([s for s in symbol_list if s]))
    if not symbol_order:
        return []

    if signal_types:
        signal_type_list = list(
            dict.fromkeys([(s or "").strip() for s in signal_types.split(",") if s.strip()])
        )
    else:
        # Default signal types include momentum raw/residual
        signal_type_list = [
            "momentum raw score",
            "momentum residual score",
            "LINREG_200",
            "LINREG_90",
            "LINREG_50",
            "LINREG_30",
            "SMA_200",
        ]

    # Get latest date
    latest_date_result = db.execute(
        select(func.max(DimDate.full_date)).join(
            FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key
        )
    ).scalar()

    if not latest_date_result:
        raise HTTPException(status_code=404, detail="No data available")

    stocks = db.execute(
        select(DimStock.symbol, DimStock.stock_key).where(
            func.upper(DimStock.symbol).in_(symbol_order)
        )
    ).all()
    stock_key_by_symbol: dict[str, int] = {
        str(symbol): int(stock_key) for symbol, stock_key in stocks
    }
    ordered_symbols = [s for s in symbol_order if s in stock_key_by_symbol]
    if not ordered_symbols:
        return []

    score_types = db.execute(
        select(DimScoreType.score_type_name, DimScoreType.score_type_key).where(
            DimScoreType.score_type_name.in_(signal_type_list)
        )
    ).all()
    score_type_name_by_key: dict[int, str] = {
        int(score_type_key): str(score_type_name) for score_type_name, score_type_key in score_types
    }
    if not score_type_name_by_key:
        return []

    symbol_by_stock_key = {v: k for k, v in stock_key_by_symbol.items()}
    score_rows = db.execute(
        select(FactScoreHistory.stock_key, FactScoreHistory.score_type_key, FactScoreHistory.score)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .where(
            and_(
                FactScoreHistory.stock_key.in_(list(symbol_by_stock_key.keys())),
                FactScoreHistory.score_type_key.in_(list(score_type_name_by_key.keys())),
                DimDate.full_date == latest_date_result,
            )
        )
    ).all()

    signals_by_symbol: dict[str, dict[str, float]] = {symbol: {} for symbol in ordered_symbols}
    for stock_key, score_type_key, score in score_rows:
        if score is None:
            continue
        symbol = symbol_by_stock_key.get(int(stock_key))
        signal_name = score_type_name_by_key.get(int(score_type_key))
        if symbol is None or signal_name is None:
            continue
        signals_by_symbol[symbol][signal_name] = float(score)

    comparisons = []
    for symbol in ordered_symbols:
        signals_dict = signals_by_symbol.get(symbol, {})

        if signals_dict:
            avg_score = sum(signals_dict.values()) / len(signals_dict)

            # Simple recommendation logic
            if avg_score >= 70:
                recommendation = "Strong Buy"
            elif avg_score >= 55:
                recommendation = "Buy"
            elif avg_score >= 45:
                recommendation = "Hold"
            elif avg_score >= 30:
                recommendation = "Sell"
            else:
                recommendation = "Strong Sell"

            comparisons.append(
                SignalComparison(
                    symbol=symbol,
                    signals=signals_dict,
                    average_score=avg_score,
                    recommendation=recommendation,
                )
            )

    return comparisons


@router.get("/historical/{symbol}")
def get_signal_history(
    symbol: str,
    db: Session = Depends(get_db),
    signal_type: str = Query("LINREG_200"),
    days: int = Query(90, ge=1, le=365),
):
    """
    Get historical signal data for a specific stock.
    """
    stock = db.execute(
        select(DimStock).where(
            func.upper(DimStock.symbol) == symbol.upper(), DimStock.is_active.is_(True)
        )
    ).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    score_type = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == signal_type)
    ).scalar_one_or_none()

    if not score_type:
        raise HTTPException(status_code=404, detail=f"Signal type {signal_type} not found")

    # Get historical data
    history = db.execute(
        select(DimDate.full_date, FactScoreHistory.score)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .where(
            and_(
                FactScoreHistory.stock_key == stock.stock_key,
                FactScoreHistory.score_type_key == score_type.score_type_key,
                DimDate.full_date >= datetime.now().date() - timedelta(days=days),
            )
        )
        .order_by(DimDate.full_date)
    ).all()

    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "history": [{"date": str(date), "score": float(score)} for date, score in history],
    }


@router.get("/universe")
def get_signal_universe(db: Session = Depends(get_db), date_str: Optional[str] = None):
    """
    Get the current universe of stocks with signals.
    """
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        # Get latest date
        latest_date_result = db.execute(
            select(func.max(DimDate.full_date)).join(
                FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key
            )
        ).scalar()

        if not latest_date_result:
            raise HTTPException(status_code=404, detail="No data available")

        target_date = latest_date_result

    # Get unique stocks with scores on target date
    stocks_with_scores = db.execute(
        select(
            DimStock.symbol,
            DimStock.company_name,
            DimStock.sector,
            func.count(FactScoreHistory.score_type_key).label("signal_count"),
        )
        .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .where(and_(DimDate.full_date == target_date, DimStock.is_active.is_(True)))
        .group_by(DimStock.symbol, DimStock.company_name, DimStock.sector)
        .order_by(DimStock.symbol)
    ).all()

    # Get sector breakdown
    sector_breakdown = db.execute(
        select(DimStock.sector, func.count(func.distinct(DimStock.stock_key)).label("count"))
        .join(FactScoreHistory, FactScoreHistory.stock_key == DimStock.stock_key)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .where(and_(DimDate.full_date == target_date, DimStock.is_active.is_(True)))
        .group_by(DimStock.sector)
    ).all()

    return {
        "as_of_date": str(target_date),
        "total_stocks": len(stocks_with_scores),
        "stocks": [
            {
                "symbol": symbol,
                "company_name": clean_company_name(company_name),
                "sector": sector,
                "signal_count": signal_count,
            }
            for symbol, company_name, sector, signal_count in stocks_with_scores
        ],
        "sector_breakdown": {sector: count for sector, count in sector_breakdown},
    }
