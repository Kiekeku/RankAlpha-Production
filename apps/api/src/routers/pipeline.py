from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimDate,
    FactAiStockAnalysis,
    FactFinFundamental,
    FactNewsArticles,
    FactNewsSentiment,
    FactScoreHistory,
    FactScreenerRank,
    FactSecurityPrice,
    FactTechnicalIndicator,
)

from ..database import get_db
from ..settings import Settings as APISettings


class PipelineStatus(BaseModel):
    component: str
    status: str  # healthy, warning, error
    last_run: Optional[datetime] = None
    records_processed: Optional[int] = None
    message: str
    data_freshness: Optional[Dict[str, Any]] = None
    latest_date: Optional[date] = None
    gap_bdays: Optional[int] = None
    price_latest_date: Optional[date] = None  # ingestion-only convenience
    screener_latest_date: Optional[date] = None
    screener_last_run: Optional[datetime] = None


class DataFreshness(BaseModel):
    table: str
    latest_date: date
    days_behind: int
    status: str  # current, stale, critical


class PipelineHealth(BaseModel):
    overall_status: str
    components: List[PipelineStatus]
    data_freshness: List[DataFreshness]
    last_check: datetime
    thresholds: Optional[Dict[str, int]] = None


router = APIRouter(tags=["pipeline"], prefix="/api/v1/pipeline")

try:
    MARKET_TZ = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    MARKET_TZ = None


def _market_today() -> date:
    """Return today's date in the market timezone (US/Eastern)."""
    if MARKET_TZ is None:
        return date.today()
    return datetime.now(tz=MARKET_TZ).date()


def _ref_trading_date(db: Session, cap_date: Optional[date] = None) -> date:
    """Return the most recent trading day <= cap_date (or today) from DimDate.

    Falls back to today if the calendar is empty (defensive).
    """
    market_today = cap_date or _market_today()
    ref = db.execute(
        select(func.max(DimDate.full_date)).where(
            and_(DimDate.full_date <= market_today, _trading_day_filter())
        )
    ).scalar()
    return ref or market_today


def _trading_day_filter():
    # Guard against stale dim_date flags by always excluding weekends.
    return and_(DimDate.is_trading_day.is_(True), DimDate.day_of_week.between(1, 5))


def _as_market_date(ts: Optional[datetime]) -> Optional[date]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if MARKET_TZ is None:
        return ts.date()
    return ts.astimezone(MARKET_TZ).date()


def _health_reference_day(db: Session, ingestion_last_run: Optional[datetime]) -> date:
    market_today = _market_today()
    last_run_date = _as_market_date(ingestion_last_run)
    cap_date = market_today
    if last_run_date and last_run_date < market_today:
        cap_date = market_today - timedelta(days=1)
    return _ref_trading_date(db, cap_date=cap_date)


def _business_days_gap(db: Session, a: Optional[date], b: Optional[date]) -> int:
    """Count trading days (Mon–Fri, guarded by DimDate flags) from a (exclusive) to b (inclusive).
    Returns 0 if a is None or a >= b, or if calendar lookup fails.
    """
    if not a or not b or a >= b:
        return 0
    return (
        db.execute(
            select(func.count())
            .select_from(DimDate)
            .where(
                and_(
                    _trading_day_filter(),
                    DimDate.full_date > a,
                    DimDate.full_date <= b,
                )
            )
        ).scalar()
        or 0
    )


def check_data_freshness(
    db: Session, table_name: str, date_column: str, fact_table: Any, ref_day: Optional[date] = None
) -> DataFreshness:
    """
    Check data freshness for a specific table.
    """
    # Get latest trading date present in the table
    latest_date_result = db.execute(
        select(func.max(DimDate.full_date))
        .join(fact_table, getattr(fact_table, date_column) == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()

    if not latest_date_result:
        return DataFreshness(
            table=table_name, latest_date=_market_today(), days_behind=999, status="critical"
        )
    # Compare to the reference trading day (<= today) using business days gap
    ref_day = ref_day or _ref_trading_date(db)
    days_behind = _business_days_gap(db, latest_date_result, ref_day)

    if days_behind <= 1:
        status = "current"
    elif days_behind <= 5:
        status = "stale"
    else:
        status = "critical"

    return DataFreshness(
        table=table_name, latest_date=latest_date_result, days_behind=days_behind, status=status
    )


@router.get("/health", response_model=PipelineHealth)
def get_pipeline_health(db: Session = Depends(get_db)):
    """
    Get overall pipeline health status and data freshness.
    """
    components: List[PipelineStatus] = []

    # ---------- Ingestion component (derive from prices + technicals) ----------
    ing_last_ts_px = db.execute(select(func.max(FactSecurityPrice.load_ts))).scalar()
    ing_last_ts_ti = db.execute(select(func.max(FactTechnicalIndicator.load_ts))).scalar()
    ingestion_last_run = max(
        [t for t in [ing_last_ts_px, ing_last_ts_ti] if t is not None], default=None
    )
    ref_day = _health_reference_day(db, ingestion_last_run)

    screener_last_run = db.execute(select(func.max(FactScreenerRank.load_ts))).scalar()

    latest_ing_date_px = db.execute(
        select(func.max(DimDate.full_date))
        .join(FactSecurityPrice, FactSecurityPrice.date_key == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()
    latest_ing_date_ti = db.execute(
        select(func.max(DimDate.full_date))
        .join(FactTechnicalIndicator, FactTechnicalIndicator.date_key == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()
    latest_ing_date = max(
        [d for d in [latest_ing_date_px, latest_ing_date_ti] if d is not None], default=None
    )
    latest_screener_date = db.execute(
        select(func.max(DimDate.full_date))
        .join(FactScreenerRank, FactScreenerRank.date_key == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()

    ing_gap = _business_days_gap(db, latest_ing_date, ref_day) if latest_ing_date else 999

    if latest_ing_date is None:
        ingestion_status = "error"
        ingestion_message = "No price/technical data present"
        ingestion_records = 0
    else:
        settings = APISettings()
        ing_healthy = int(settings.pipeline_ingestion_healthy_max_bdays or 1)
        ing_warning = int(settings.pipeline_ingestion_warning_max_bdays or 3)
        if ing_gap <= ing_healthy:
            ingestion_status = "healthy"
        elif ing_gap <= ing_warning:
            ingestion_status = "warning"
        else:
            ingestion_status = "error"
        # Records processed on the latest trading day (distinct stocks)
        count_px = (
            db.execute(
                select(func.count(func.distinct(FactSecurityPrice.stock_key)))
                .join(DimDate, DimDate.date_key == FactSecurityPrice.date_key)
                .where(DimDate.full_date == latest_ing_date)
            ).scalar()
            or 0
        )
        count_ti = (
            db.execute(
                select(func.count(func.distinct(FactTechnicalIndicator.stock_key)))
                .join(DimDate, DimDate.date_key == FactTechnicalIndicator.date_key)
                .where(DimDate.full_date == latest_ing_date)
            ).scalar()
            or 0
        )
        ingestion_records = max(count_px, count_ti)
        ingestion_message = f"Latest {latest_ing_date}: {ingestion_records} symbols updated"

    components.append(
        PipelineStatus(
            component="ingestion",
            status=ingestion_status,
            last_run=ingestion_last_run,
            records_processed=ingestion_records,
            message=ingestion_message,
            latest_date=latest_ing_date,
            gap_bdays=ing_gap,
            price_latest_date=latest_ing_date_px,
            screener_latest_date=latest_screener_date,
            screener_last_run=screener_last_run,
        )
    )

    # ---------- Scorer component (derive from score history) ----------
    scorer_last_run = db.execute(select(func.max(FactScoreHistory.load_ts))).scalar()
    latest_score_date = db.execute(
        select(func.max(DimDate.full_date))
        .join(FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()
    score_gap = _business_days_gap(db, latest_score_date, ref_day) if latest_score_date else 999
    scorer_records = 0
    if latest_score_date:
        scorer_records = (
            db.execute(
                select(func.count(func.distinct(FactScoreHistory.stock_key)))
                .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
                .where(DimDate.full_date == latest_score_date)
            ).scalar()
            or 0
        )
    if latest_score_date is None:
        scorer_status = "warning"
        scorer_message = "No recent scores detected"
    else:
        settings = APISettings()
        sc_healthy = int(settings.pipeline_scorer_healthy_max_bdays or 1)
        if score_gap <= sc_healthy:
            scorer_status = "healthy"
        else:
            scorer_status = "warning"
        scorer_message = f"Latest {latest_score_date}: {scorer_records} symbols scored"

    components.append(
        PipelineStatus(
            component="scorer",
            status=scorer_status,
            last_run=scorer_last_run,
            records_processed=scorer_records,
            message=scorer_message,
            latest_date=latest_score_date,
            gap_bdays=score_gap,
        )
    )

    # ---------- Sentiment component (AI analysis) ----------
    sentiment_last_run = db.execute(select(func.max(FactAiStockAnalysis.load_ts))).scalar()
    latest_ai_date = db.execute(
        select(func.max(DimDate.full_date))
        .join(FactAiStockAnalysis, FactAiStockAnalysis.date_key == DimDate.date_key)
        .where(_trading_day_filter())
    ).scalar()
    ai_gap = _business_days_gap(db, latest_ai_date, ref_day) if latest_ai_date else 999
    sentiment_records = 0
    if latest_ai_date:
        sentiment_records = (
            db.execute(
                select(func.count(FactAiStockAnalysis.analysis_id))
                .join(DimDate, DimDate.date_key == FactAiStockAnalysis.date_key)
                .where(DimDate.full_date == latest_ai_date)
            ).scalar()
            or 0
        )
    if latest_ai_date is None:
        sentiment_status = "warning"
        sentiment_message = "No recent AI analyses detected"
    else:
        settings = APISettings()
        max_ok = int(settings.pipeline_sentiment_healthy_max_bdays or 7)
        if ai_gap <= max_ok:
            sentiment_status = "healthy"
        else:
            sentiment_status = "warning"
        sentiment_message = f"Latest {latest_ai_date}: {sentiment_records} analyses"

    components.append(
        PipelineStatus(
            component="sentiment",
            status=sentiment_status,
            last_run=sentiment_last_run,
            records_processed=sentiment_records,
            message=sentiment_message,
            latest_date=latest_ai_date,
            gap_bdays=ai_gap,
        )
    )

    # Check data freshness for key tables
    freshness_checks = [
        check_data_freshness(
            db, "fact_security_price", "date_key", FactSecurityPrice, ref_day=ref_day
        ),
        check_data_freshness(
            db,
            "fact_technical_indicator",
            "date_key",
            FactTechnicalIndicator,
            ref_day=ref_day,
        ),
        check_data_freshness(
            db, "fact_score_history", "date_key", FactScoreHistory, ref_day=ref_day
        ),
        check_data_freshness(
            db, "fact_news_articles", "article_date", FactNewsArticles, ref_day=ref_day
        ),
        check_data_freshness(
            db, "fact_screener_rank", "date_key", FactScreenerRank, ref_day=ref_day
        ),
    ]

    # Determine overall status
    all_statuses = [c.status for c in components]
    if any(s == "error" for s in all_statuses):
        overall_status = "error"
    elif any(s == "warning" for s in all_statuses):
        overall_status = "warning"
    else:
        overall_status = "healthy"

    settings = APISettings()
    return PipelineHealth(
        overall_status=overall_status,
        components=components,
        data_freshness=freshness_checks,
        last_check=datetime.now(),
        thresholds={
            "ingestion_healthy_max_bdays": int(settings.pipeline_ingestion_healthy_max_bdays or 1),
            "ingestion_warning_max_bdays": int(settings.pipeline_ingestion_warning_max_bdays or 3),
            "scorer_healthy_max_bdays": int(settings.pipeline_scorer_healthy_max_bdays or 1),
            "sentiment_healthy_max_bdays": int(settings.pipeline_sentiment_healthy_max_bdays or 7),
        },
    )


@router.get("/status/{component}")
def get_component_status(component: str, db: Session = Depends(get_db)):
    """
    Get detailed status for a specific pipeline component.
    """
    valid_components = ["ingestion", "scorer", "sentiment", "fundamental"]

    if component not in valid_components:
        raise HTTPException(
            status_code=404,
            detail=f"Component '{component}' not found. Valid components: {', '.join(valid_components)}",
        )

    if component == "ingestion":
        # Get recent ingestion runs
        recent_runs = db.execute(
            select(
                DimDate.full_date,
                func.count(FactScoreHistory.fact_id).label("records"),
                func.min(FactScoreHistory.load_ts).label("start_time"),
                func.max(FactScoreHistory.load_ts).label("end_time"),
            )
            .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
            .where(DimDate.full_date >= date.today() - timedelta(days=7))
            .group_by(DimDate.full_date)
            .order_by(desc(DimDate.full_date))
        ).all()

        return {
            "component": component,
            "recent_runs": [
                {
                    "date": str(run_date),
                    "records_processed": records,
                    "start_time": start_time.isoformat() if start_time else None,
                    "end_time": end_time.isoformat() if end_time else None,
                    "duration_seconds": (end_time - start_time).total_seconds()
                    if start_time and end_time
                    else None,
                }
                for run_date, records, start_time, end_time in recent_runs
            ],
        }

    elif component == "scorer":
        # Get scoring statistics
        score_stats = db.execute(
            select(
                func.count(func.distinct(FactScoreHistory.stock_key)).label("unique_stocks"),
                func.count(func.distinct(FactScoreHistory.score_type_key)).label("score_types"),
                func.count(FactScoreHistory.fact_id).label("total_scores"),
            )
            .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
            .where(DimDate.full_date >= date.today() - timedelta(days=1))
        ).first()

        return {
            "component": component,
            "statistics": {
                "unique_stocks": score_stats.unique_stocks if score_stats else 0,
                "score_types": score_stats.score_types if score_stats else 0,
                "total_scores": score_stats.total_scores if score_stats else 0,
            },
        }

    elif component == "sentiment":
        # Get sentiment analysis statistics
        sentiment_stats = db.execute(
            select(
                func.count(FactNewsSentiment.article_id).label("analyzed_articles"),
                func.avg(FactNewsSentiment.sentiment_score).label("avg_sentiment"),
            )
            .join(FactNewsArticles, FactNewsArticles.article_id == FactNewsSentiment.article_id)
            .join(DimDate, DimDate.date_key == FactNewsArticles.article_date)
            .where(DimDate.full_date >= date.today() - timedelta(days=7))
        ).first()

        return {
            "component": component,
            "statistics": {
                "analyzed_articles_7d": sentiment_stats.analyzed_articles if sentiment_stats else 0,
                "average_sentiment": float(sentiment_stats.avg_sentiment)
                if sentiment_stats and sentiment_stats.avg_sentiment
                else 0,
            },
        }

    else:  # fundamental
        # Get fundamental data statistics
        fundamental_stats = db.execute(
            select(
                func.count(func.distinct(FactFinFundamental.stock_key)).label("stocks_with_data"),
                func.count(func.distinct(FactFinFundamental.metric_key)).label("unique_metrics"),
                func.max(FactFinFundamental.load_ts).label("last_update"),
            )
        ).first()

        return {
            "component": component,
            "statistics": {
                "stocks_with_fundamentals": fundamental_stats.stocks_with_data
                if fundamental_stats
                else 0,
                "unique_metrics": fundamental_stats.unique_metrics if fundamental_stats else 0,
                "last_update": fundamental_stats.last_update.isoformat()
                if fundamental_stats and fundamental_stats.last_update
                else None,
            },
        }


@router.get("/airflow-status")
def get_airflow_status():
    """
    Get Airflow status and provide link to UI.
    Note: In production, this would integrate with Airflow API.
    """
    return {
        "airflow_ui_url": "http://localhost:8080",
        "credentials": {"username": "rankalpha", "password": "rankalpha"},
        "message": "Access Airflow UI for detailed DAG status and logs",
        "dags": [
            {
                "dag_id": "data_pipeline",
                "description": "Main data ingestion and scoring pipeline",
                "schedule": "0 2 * * *",  # Daily at 2 AM
                "status": "running",
            },
            {
                "dag_id": "sentiment_analysis",
                "description": "News sentiment analysis pipeline",
                "schedule": "0 */6 * * *",  # Every 6 hours
                "status": "paused",
            },
        ],
    }


@router.get("/data-quality")
def check_data_quality(db: Session = Depends(get_db)):
    """
    Check for data quality issues.
    """
    issues: list[dict[str, object]] = []

    # Check for missing dates in score history
    missing_dates = (
        db.execute(
            select(DimDate.full_date)
            .outerjoin(FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key)
            .where(
                and_(
                    _trading_day_filter(),
                    DimDate.full_date >= date.today() - timedelta(days=30),
                    DimDate.full_date < date.today(),
                    FactScoreHistory.fact_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    if missing_dates:
        issues.append(
            {
                "type": "missing_data",
                "severity": "warning",
                "description": f"Missing score data for {len(missing_dates)} trading days",
                "dates": [str(d) for d in missing_dates[:5]],  # Show first 5
            }
        )

    # Check for duplicate entries
    duplicates = db.execute(
        select(
            FactScoreHistory.stock_key,
            FactScoreHistory.date_key,
            FactScoreHistory.score_type_key,
            func.count(FactScoreHistory.fact_id).label("count"),
        )
        .group_by(
            FactScoreHistory.stock_key, FactScoreHistory.date_key, FactScoreHistory.score_type_key
        )
        .having(func.count(FactScoreHistory.fact_id) > 1)
    ).all()

    if duplicates:
        issues.append(
            {
                "type": "duplicate_data",
                "severity": "error",
                "description": f"Found {len(duplicates)} duplicate score entries",
                "count": len(duplicates),
            }
        )

    # Check for anomalous scores
    anomalous_scores = db.execute(
        select(func.count(FactScoreHistory.fact_id)).where(
            or_(FactScoreHistory.score < 0, FactScoreHistory.score > 100)
        )
    ).scalar()

    if anomalous_scores:
        issues.append(
            {
                "type": "anomalous_values",
                "severity": "warning",
                "description": f"Found {anomalous_scores} scores outside valid range (0-100)",
                "count": anomalous_scores,
            }
        )

    return {
        "status": "error"
        if any(i["severity"] == "error" for i in issues)
        else "warning"
        if issues
        else "healthy",
        "issues": issues,
        "checked_at": datetime.now().isoformat(),
    }
