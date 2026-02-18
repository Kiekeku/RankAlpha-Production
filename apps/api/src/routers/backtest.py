from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    DimScoreType,
    DimStock,
    FactScoreHistory,
)

from ..database import get_db
from ..settings import Settings


class BacktestRequest(BaseModel):
    strategy_name: str = Field("momentum_top_n", description="Strategy type")
    signal_type: str = Field("LINREG_200", description="Signal to use for ranking")
    top_n: int = Field(10, ge=1, le=100, description="Number of top stocks to hold")
    rebalance_frequency: str = Field("monthly", pattern="^(daily|weekly|monthly|quarterly)$")
    start_date: str = Field(..., description="Start date (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="End date (YYYY-MM-DD)")
    initial_capital: float = Field(100000, gt=0)
    exclude_sectors: Optional[List[str]] = None
    min_score: Optional[float] = Field(None, description="Minimum score threshold")


class BacktestResult(BaseModel):
    strategy_name: str
    parameters: Dict[str, Any]
    performance: Dict[str, float]
    equity_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    holdings: List[Dict[str, Any]]


class QuickBacktestResult(BaseModel):
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    avg_win: float
    avg_loss: float
    trades_count: int


router = APIRouter(tags=["backtest"], prefix="/api/v1/backtest")


def _parse_yyyy_mm_dd(value: str, *, field_name: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format. Use YYYY-MM-DD",
        ) from exc


def _add_months(value: date, months: int) -> date:
    """Add months while clamping to month-end when needed (e.g. Jan 31 -> Feb 28)."""
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _estimate_rebalance_points(start: date, end: date, frequency: str) -> int:
    if end < start:
        return 0
    delta_days = (end - start).days
    if frequency == "daily":
        return delta_days + 1
    if frequency == "weekly":
        return delta_days // 7 + 1
    # Monthly/quarterly: use a safe upper bound in month units
    month_span = (end.year - start.year) * 12 + (end.month - start.month)
    if frequency == "monthly":
        return month_span + 2
    # quarterly
    return month_span // 3 + 2


def calculate_performance_metrics(
    equity_curve: List[float], trades: List[Dict]
) -> Dict[str, float]:
    """
    Calculate performance metrics from equity curve and trades.
    """
    if len(equity_curve) < 2:
        return {
            "total_return": 0,
            "annualized_return": 0,
            "sharpe_ratio": 0,
            "max_drawdown": 0,
            "volatility": 0,
        }

    returns = np.diff(equity_curve) / equity_curve[:-1]

    # Total return
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]

    # Annualized return (assuming daily data)
    days = len(equity_curve)
    years = days / 252
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # Sharpe ratio (assuming 0 risk-free rate)
    if len(returns) > 0 and np.std(returns) > 0:
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252)
    else:
        sharpe_ratio = 0

    # Max drawdown
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

    # Volatility
    volatility = np.std(returns) * np.sqrt(252) if len(returns) > 0 else 0

    return {
        "total_return": float(total_return * 100),
        "annualized_return": float(annualized_return * 100),
        "sharpe_ratio": float(sharpe_ratio),
        "max_drawdown": float(max_drawdown * 100),
        "volatility": float(volatility * 100),
    }


@router.post("/quick", response_model=QuickBacktestResult)
def run_quick_backtest(request: BacktestRequest, db: Session = Depends(get_db)):
    """
    Run a quick backtest with simplified logic for rapid results.
    Returns in < 5 seconds.
    """
    # Parse dates
    start_date = _parse_yyyy_mm_dd(request.start_date, field_name="start_date")
    end_date = (
        _parse_yyyy_mm_dd(request.end_date, field_name="end_date")
        if request.end_date
        else date.today()
    )
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="end_date must be >= start_date")

    settings = Settings()
    max_range_days = int(settings.backtest_max_range_days or 0)
    if max_range_days > 0 and (end_date - start_date).days > max_range_days:
        raise HTTPException(status_code=400, detail=f"Date range too large; max {max_range_days}d")
    max_points = int(settings.backtest_max_rebalance_points or 0)
    est_points = _estimate_rebalance_points(start_date, end_date, request.rebalance_frequency)
    if max_points > 0 and est_points > max_points:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rebalance points for this range; max {max_points}",
        )

    # Get score type
    score_type = db.execute(
        select(DimScoreType).where(DimScoreType.score_type_name == request.signal_type)
    ).scalar_one_or_none()

    if not score_type:
        raise HTTPException(status_code=404, detail=f"Signal type {request.signal_type} not found")

    # Get rebalance dates based on frequency
    rebalance_dates = []
    current_date = start_date

    while current_date <= end_date:
        rebalance_dates.append(current_date)
        if max_points > 0 and len(rebalance_dates) > max_points:
            raise HTTPException(
                status_code=400,
                detail=f"Too many rebalance points for this range; max {max_points}",
            )

        if request.rebalance_frequency == "daily":
            current_date += timedelta(days=1)
        elif request.rebalance_frequency == "weekly":
            current_date += timedelta(weeks=1)
        elif request.rebalance_frequency == "monthly":
            current_date = _add_months(current_date, 1)
        else:  # quarterly
            current_date = _add_months(current_date, 3)

    # Simplified backtest logic
    portfolio_value = request.initial_capital
    trades = []
    current_holdings = {}
    equity_curve = [portfolio_value]

    for i, rebalance_date in enumerate(rebalance_dates[:-1]):
        # Get top N stocks by score on rebalance date
        date_key_result = db.execute(
            select(DimDate.date_key).where(DimDate.full_date == rebalance_date)
        ).scalar()

        if not date_key_result:
            continue

        # Build query for top stocks
        query = (
            select(DimStock.symbol, DimStock.stock_key, FactScoreHistory.score)
            .join(DimStock, DimStock.stock_key == FactScoreHistory.stock_key)
            .where(
                and_(
                    FactScoreHistory.date_key == date_key_result,
                    FactScoreHistory.score_type_key == score_type.score_type_key,
                    DimStock.is_active.is_(True),
                )
            )
        )

        # Apply filters
        if request.exclude_sectors:
            query = query.where(~DimStock.sector.in_(request.exclude_sectors))

        if request.min_score is not None:
            query = query.where(FactScoreHistory.score >= request.min_score)

        # Get top N
        query = query.order_by(desc(FactScoreHistory.score)).limit(request.top_n)
        top_stocks = db.execute(query).all()

        if not top_stocks:
            continue

        # Simulate rebalancing
        new_holdings = {symbol: 1.0 / len(top_stocks) for symbol, _, _ in top_stocks}

        # Record trades
        for symbol in current_holdings:
            if symbol not in new_holdings:
                trades.append(
                    {
                        "date": str(rebalance_date),
                        "symbol": symbol,
                        "action": "SELL",
                        "weight": current_holdings[symbol],
                    }
                )

        for symbol in new_holdings:
            if symbol not in current_holdings:
                trades.append(
                    {
                        "date": str(rebalance_date),
                        "symbol": symbol,
                        "action": "BUY",
                        "weight": new_holdings[symbol],
                    }
                )

        current_holdings = new_holdings

        # Simulate returns (simplified - random for demonstration)
        # In production, would use actual price data
        period_return = np.random.normal(0.001, 0.02)  # Daily return assumption
        portfolio_value *= 1 + period_return
        equity_curve.append(portfolio_value)

    # Calculate win/loss statistics
    win_rate = 0.55  # Placeholder - would calculate from actual P&L
    avg_win = 0.08  # Placeholder
    avg_loss = -0.05  # Placeholder

    # Calculate metrics
    metrics = calculate_performance_metrics(equity_curve, trades)

    return QuickBacktestResult(
        total_return=metrics["total_return"],
        annualized_return=metrics["annualized_return"],
        sharpe_ratio=metrics["sharpe_ratio"],
        max_drawdown=metrics["max_drawdown"],
        win_rate=win_rate * 100,
        avg_win=avg_win * 100,
        avg_loss=avg_loss * 100,
        trades_count=len(trades),
    )


@router.post("/full", response_model=BacktestResult)
async def run_full_backtest(
    request: BacktestRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Run a comprehensive backtest with detailed results.
    This is a more thorough simulation that may take longer.
    """
    # For now, return a simplified version
    # In production, this would queue a background task

    quick_result = run_quick_backtest(request, db)

    # Generate sample equity curve
    days = 252  # One year of trading days
    equity_curve = []
    current_value = request.initial_capital

    for i in range(days):
        daily_return = np.random.normal(0.0005, 0.015)
        current_value *= 1 + daily_return
        equity_curve.append(
            {
                "date": str(date.today() - timedelta(days=days - i)),
                "value": round(current_value, 2),
                "return": round(daily_return * 100, 2),
            }
        )

    # Sample trades
    sample_trades = [
        {
            "date": str(date.today() - timedelta(days=200)),
            "symbol": "AAPL",
            "action": "BUY",
            "shares": 100,
            "price": 150.00,
            "value": 15000,
        },
        {
            "date": str(date.today() - timedelta(days=150)),
            "symbol": "MSFT",
            "action": "BUY",
            "shares": 50,
            "price": 300.00,
            "value": 15000,
        },
        {
            "date": str(date.today() - timedelta(days=100)),
            "symbol": "AAPL",
            "action": "SELL",
            "shares": 100,
            "price": 165.00,
            "value": 16500,
            "pnl": 1500,
        },
    ]

    # Current holdings
    current_holdings = [
        {
            "symbol": "MSFT",
            "shares": 50,
            "cost_basis": 300,
            "current_price": 320,
            "value": 16000,
            "pnl": 1000,
        },
        {
            "symbol": "GOOGL",
            "shares": 20,
            "cost_basis": 2500,
            "current_price": 2600,
            "value": 52000,
            "pnl": 2000,
        },
        {
            "symbol": "AMZN",
            "shares": 30,
            "cost_basis": 3300,
            "current_price": 3400,
            "value": 102000,
            "pnl": 3000,
        },
    ]

    return BacktestResult(
        strategy_name=request.strategy_name,
        parameters={
            "signal_type": request.signal_type,
            "top_n": request.top_n,
            "rebalance_frequency": request.rebalance_frequency,
            "start_date": request.start_date,
            "end_date": request.end_date or str(date.today()),
            "initial_capital": request.initial_capital,
        },
        performance={
            "total_return": quick_result.total_return,
            "annualized_return": quick_result.annualized_return,
            "sharpe_ratio": quick_result.sharpe_ratio,
            "max_drawdown": quick_result.max_drawdown,
            "win_rate": quick_result.win_rate,
            "trades_count": quick_result.trades_count,
        },
        equity_curve=equity_curve[-30:],  # Last 30 days for brevity
        trades=sample_trades,
        holdings=current_holdings,
    )


@router.get("/strategies")
def get_available_strategies():
    """
    Get list of available backtest strategies.
    """
    return {
        "strategies": [
            {
                "name": "momentum_top_n",
                "description": "Buy top N stocks by momentum score, rebalance periodically",
                "parameters": ["signal_type", "top_n", "rebalance_frequency", "min_score"],
            },
            {
                "name": "mean_reversion",
                "description": "Buy oversold stocks, sell overbought",
                "parameters": ["signal_type", "oversold_threshold", "overbought_threshold"],
            },
            {
                "name": "sector_rotation",
                "description": "Rotate between sectors based on momentum",
                "parameters": ["rebalance_frequency", "sectors_to_hold"],
            },
            {
                "name": "value_momentum",
                "description": "Combine value and momentum signals",
                "parameters": ["value_weight", "momentum_weight", "top_n"],
            },
        ]
    }
