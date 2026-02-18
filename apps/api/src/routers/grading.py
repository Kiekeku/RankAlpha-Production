from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any, Dict, List, Optional, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, case, func, literal, or_, select, text
from sqlalchemy.orm import Session

from apps.api.src.security import require_operator_access
from apps.common.src.models import (
    DimDate,
    DimScoreType,
    DimSource,
    DimStock,
    DimStyle,
    FactScoreHistory,
    FactScreenerRank,
    FactStockNextEarnings,
    MvLatestGrades,
    MvSentimentProxy,
    MvUniverseEligible,
    VwAiAnalysisLatest,
    VwFinFundamentals,
    VwScoreHistory,
)

from ..cache import get_json, invalidate_prefix, make_key, set_json
from ..database import get_db
from ..services.ai_analysis.utils import preview_map_for_symbols
from ..settings import Settings
from ..utils.company import CompanyNameSanitizerMixin
from ..utils.settings_cache import make_cached_getter
from ..utils.setup_taxonomy import (
    SETUP_TAXONOMY_SLUGS,
    setup_bucket_label_expr,
    setup_style_filter_expr,
)

logger = logging.getLogger(__name__)
try:
    _MARKET_TZ = ZoneInfo("America/New_York")
except ZoneInfoNotFoundError:
    _MARKET_TZ = None


def _market_today() -> date:
    """Return today's date in the market timezone (US/Eastern)."""
    if _MARKET_TZ is None:
        return date.today()
    return datetime.now(tz=_MARKET_TZ).date()


class AiPreview(BaseModel):
    events_count: Optional[int] = None
    base_price_target: Optional[float] = None
    has_thesis: Optional[bool] = None


class StockGrade(CompanyNameSanitizerMixin, BaseModel):
    symbol: str
    company_name: Optional[str] = None
    date: date
    momentum_score: Optional[float] = Field(None, description="Momentum score (0-100)")
    value_score: Optional[float] = Field(None, description="Value score (0-100)")
    sentiment_score: Optional[float] = Field(None, description="Sentiment score (0-100)")
    overall_grade: str = Field(..., description="Letter grade A-F")
    grade_explanation: str = Field(..., description="Explanation of the grade")
    confidence: str = Field("Medium", description="High/Medium/Low confidence")


class GradeLeaderboard(BaseModel):
    stocks: List[StockGrade]
    total_count: int
    page: int
    page_size: int
    ai_preview: Optional[Dict[str, AiPreview]] = None


class PeerGrade(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    as_of_date: Optional[date] = None
    overall_grade: str


class BatchGradesOut(BaseModel):
    items: List[PeerGrade]


class SimilarPeerItem(BaseModel):
    symbol: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    market_cap: Optional[float] = None
    market_cap_diff_pct: Optional[float] = None


class SimilarPeersResponse(BaseModel):
    symbol: str
    sector: Optional[str] = None
    market_cap: Optional[float] = None
    items: List[SimilarPeerItem]


class ModelWeightsOut(BaseModel):
    as_of_date: date
    method: str
    window_days: int
    horizon_days: int
    w_momentum: float
    w_value: float
    w_sentiment: float
    lambda_rp: float
    alpha_shrink: float
    sentiment_coverage: Optional[float] = None
    source: str = "db"


class AssetDetail(CompanyNameSanitizerMixin, BaseModel):
    symbol: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    exchange: Optional[str] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    target_price: Optional[float] = None
    projected_lt_growth_rate: Optional[float] = None
    next_earnings_date: Optional[date] = None
    next_earnings_time: Optional[str] = None
    next_earnings_source: Optional[str] = None
    current_grade: StockGrade
    score_history: List[Dict[str, Any]]
    recent_news: List[Dict[str, Any]]
    ai_analysis: Optional[Dict[str, Any]] = None


class GradingRefreshResponse(BaseModel):
    """Response model for grading refresh endpoint."""

    status: str
    message: str
    latest_data_date: Optional[date] = None
    timestamp: str
    invalidated_keys: Optional[Dict[str, int]] = None
    mv_universe_eligible_refreshed: Optional[bool] = None
    mv_latest_grades_refreshed: Optional[bool] = None
    # OpenAPI example
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "success",
                "message": "Universe and grades refreshed; caches invalidated",
                "latest_data_date": "2025-10-08",
                "timestamp": "2025-10-09T14:35:12Z",
                "invalidated_keys": {
                    "grades": 124,
                    "grades_v2": 310,
                    "grade": 75,
                    "asset": 10,
                    "screener_changes": 14,
                    "screener_breadth": 7,
                    "httpcache": 120,
                },
                "mv_universe_eligible_refreshed": True,
                "mv_latest_grades_refreshed": True,
            }
        }
    )


router = APIRouter(tags=["grading"], prefix="/api/v1/grading")


_get_settings = make_cached_getter(lambda: Settings())


def _metric_sort_column_name(sort_by: str) -> Optional[str]:
    mapping = {
        "momentum": "momentum_score",
        "value": "value_score",
        "sentiment": "sentiment_score",
    }
    return mapping.get(sort_by)


def _metric_sort_order_expr(
    sort_by: str,
    sort_order: str,
    *,
    momentum_col: Any,
    value_col: Any,
    sentiment_col: Any,
) -> Any:
    metric_name = _metric_sort_column_name(sort_by)
    if metric_name is None:
        return None
    col_map = {
        "momentum_score": momentum_col,
        "value_score": value_col,
        "sentiment_score": sentiment_col,
    }
    col = col_map[metric_name]
    ordered = col.desc() if sort_order == "desc" else col.asc()
    return ordered.nullslast()


def explain_grade_from_db(
    grade: Optional[str],
    momentum_score: Optional[float],
    value_score: Optional[float],
    sentiment_score: Optional[float],
) -> str:
    """
    Build a human-readable explanation using the DB-computed grade and raw factors.
    The API never recomputes the grade; it only formats what the DB already decided.
    """
    if not grade or str(grade).upper() == "N/A":
        return "No composite grade available (requires momentum and value)."

    parts: list[str] = [f"Composite grade {grade} from latest DB weights."]
    detail_bits: list[str] = []
    if momentum_score is not None:
        detail_bits.append(f"Momentum {momentum_score:.1f}")
    if value_score is not None:
        detail_bits.append(f"Value {value_score:.1f}")
    if sentiment_score is not None:
        detail_bits.append(f"Sentiment {sentiment_score:.1f}")
    if detail_bits:
        parts.append(" / ".join(detail_bits))
    return " ".join(parts)


def calculate_letter_grade(
    momentum_score: Optional[float],
    value_score: Optional[float],
    sentiment_score: Optional[float],
) -> tuple[str, str]:
    """
    Lightweight fallback grade computation when DB grade is unavailable.
    Mirrors prior API behavior: requires momentum & value; sentiment is optional
    and reweights to avoid penalizing missing sentiment.
    """
    if momentum_score is None or value_score is None:
        return "N/A", "Insufficient data: requires momentum and value"

    weights = [0.4, 0.4]
    values = [float(momentum_score), float(value_score)]
    if sentiment_score is not None:
        weights.append(0.2)
        values.append(float(sentiment_score))
    wsum = sum(weights)
    composite = sum(v * w for v, w in zip(values, weights)) / wsum

    if composite >= 90:
        grade = "A"
        explanation = "Top decile composite across available factors (M,V; S optional)"
    elif composite >= 70:
        grade = "B"
        explanation = "Strong composite across available factors (M,V; S optional)"
    elif composite >= 45:
        grade = "C"
        explanation = "Mid-range composite across available factors (M,V; S optional)"
    elif composite >= 20:
        grade = "D"
        explanation = "Lower composite across available factors (M,V; S optional)"
    else:
        grade = "F"
        explanation = "Bottom composite across available factors (M,V; S optional)"
    return grade, explanation


@router.get("/sectors", response_model=List[str])
def list_sectors(db: Session = Depends(get_db)) -> List[str]:
    """Return distinct active sectors sorted alphabetically."""
    rows = (
        db.execute(
            select(DimStock.sector)
            .where(DimStock.is_active.is_(True), DimStock.sector.isnot(None))
            .distinct()
            .order_by(DimStock.sector.asc())
        )
        .scalars()
        .all()
    )
    return [s for s in rows if s]


@router.get("/weights", response_model=ModelWeightsOut)
def get_model_weights(
    db: Session = Depends(get_db),
    as_of: Optional[date] = Query(
        None,
        description="Return weights in force as of this date (YYYY-MM-DD). Defaults to latest.",
    ),
) -> ModelWeightsOut:
    """Expose latest model weights (hybrid IC + risk parity) or fallback defaults."""
    # Versioned path when as_of supplied
    if as_of is not None:
        try:
            r = db.execute(
                text(
                    """
                    WITH ver AS (
                      SELECT id, effective_from, window_days, horizon_days, lambda_rp, alpha_shrink, sentiment_coverage
                      FROM rankalpha.dim_model_weight_version
                      WHERE model_code = 'default' AND :as_of <@ validity
                      ORDER BY effective_from DESC
                      LIMIT 1
                    ), items AS (
                      SELECT
                        MAX(CASE WHEN i.factor_code ILIKE 'Momentum'  THEN i.weight END) AS w_momentum,
                        MAX(CASE WHEN i.factor_code ILIKE 'Value'     THEN i.weight END) AS w_value,
                        MAX(CASE WHEN i.factor_code ILIKE 'Sentiment' THEN i.weight END) AS w_sentiment
                      FROM rankalpha.dim_model_weight_item i
                      JOIN ver ON ver.id = i.version_id
                    )
                    SELECT ver.effective_from AS as_of_date,
                           'HYBRID_IC_RP' AS method,
                           ver.window_days, ver.horizon_days,
                           items.w_momentum, items.w_value, items.w_sentiment,
                           ver.lambda_rp, ver.alpha_shrink, ver.sentiment_coverage
                    FROM ver, items
                    """
                ),
                {"as_of": as_of},
            ).one_or_none()
            if r:
                return ModelWeightsOut(
                    as_of_date=r.as_of_date,
                    method=r.method,
                    window_days=int(r.window_days),
                    horizon_days=int(r.horizon_days),
                    w_momentum=float(r.w_momentum),
                    w_value=float(r.w_value),
                    w_sentiment=float(r.w_sentiment),
                    lambda_rp=float(r.lambda_rp),
                    alpha_shrink=float(r.alpha_shrink),
                    sentiment_coverage=float(r.sentiment_coverage)
                    if r.sentiment_coverage is not None
                    else None,
                    source="versioned",
                )
        except Exception:
            pass

    # If no explicit as_of was provided, prefer versioned weights in force for today
    try:
        today = date.today()
        r = db.execute(
            text(
                """
                WITH ver AS (
                  SELECT id, effective_from, window_days, horizon_days, lambda_rp, alpha_shrink, sentiment_coverage
                  FROM rankalpha.dim_model_weight_version
                  WHERE model_code = 'default' AND :as_of <@ validity
                  ORDER BY effective_from DESC
                  LIMIT 1
                ), items AS (
                  SELECT
                    MAX(CASE WHEN i.factor_code ILIKE 'Momentum'  THEN i.weight END) AS w_momentum,
                    MAX(CASE WHEN i.factor_code ILIKE 'Value'     THEN i.weight END) AS w_value,
                    MAX(CASE WHEN i.factor_code ILIKE 'Sentiment' THEN i.weight END) AS w_sentiment
                  FROM rankalpha.dim_model_weight_item i
                  JOIN ver ON ver.id = i.version_id
                )
                SELECT ver.effective_from AS as_of_date,
                       'HYBRID_IC_RP' AS method,
                       ver.window_days, ver.horizon_days,
                       items.w_momentum, items.w_value, items.w_sentiment,
                       ver.lambda_rp, ver.alpha_shrink, ver.sentiment_coverage
                FROM ver, items
                """
            ),
            {"as_of": today},
        ).one_or_none()
        if r:
            return ModelWeightsOut(
                as_of_date=r.as_of_date,
                method=r.method,
                window_days=int(r.window_days),
                horizon_days=int(r.horizon_days),
                w_momentum=float(r.w_momentum),
                w_value=float(r.w_value),
                w_sentiment=float(r.w_sentiment),
                lambda_rp=float(r.lambda_rp),
                alpha_shrink=float(r.alpha_shrink),
                sentiment_coverage=float(r.sentiment_coverage)
                if r.sentiment_coverage is not None
                else None,
                source="versioned",
            )
    except Exception:
        pass

    # Default to latest row from legacy table (backward compatibility)
    try:
        r2 = db.execute(
            text(
                """
                SELECT as_of_date, method, window_days, horizon_days,
                       w_momentum, w_value, w_sentiment,
                       lambda_rp, alpha_shrink, sentiment_coverage
                FROM rankalpha.dim_model_weight
                WHERE as_of_date <= CURRENT_DATE
                ORDER BY as_of_date DESC
                LIMIT 1
                """
            )
        ).one_or_none()
        if r2:
            return ModelWeightsOut(
                as_of_date=r2.as_of_date,
                method=r2.method,
                window_days=int(r2.window_days),
                horizon_days=int(r2.horizon_days),
                w_momentum=float(r2.w_momentum),
                w_value=float(r2.w_value),
                w_sentiment=float(r2.w_sentiment),
                lambda_rp=float(r2.lambda_rp),
                alpha_shrink=float(r2.alpha_shrink),
                sentiment_coverage=float(r2.sentiment_coverage)
                if r2.sentiment_coverage is not None
                else None,
                source="db",
            )
    except Exception:
        pass
    # Fallback default
    latest = db.execute(select(func.max(DimDate.full_date))).scalar() or date.today()
    return ModelWeightsOut(
        as_of_date=latest,
        method="DEFAULT",
        window_days=504,
        horizon_days=21,
        w_momentum=0.4,
        w_value=0.4,
        w_sentiment=0.2,
        lambda_rp=0.4,
        alpha_shrink=0.5,
        sentiment_coverage=None,
        source="default",
    )


@router.get("/grades", response_model=GradeLeaderboard)
def get_stock_grades(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
    min_grade: Optional[str] = Query(None, pattern="^[A-F]$"),
    max_grade: Optional[str] = Query(None, pattern="^[A-F]$"),
    sector: Optional[str] = None,
    sort_by: str = Query("grade", pattern="^(grade|momentum|value|sentiment|symbol)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    search: Optional[str] = Query(None, min_length=1, max_length=64),
    tracked_only: bool = Query(
        False,
        description="If true, return/count stocks with momentum and value present; sentiment optional. Ignores grade filters.",
    ),
    as_of: Optional[date] = Query(
        None, description="Return grades as of this date (YYYY-MM-DD). Defaults to latest."
    ),
    has_setup: bool = Query(
        False,
        description="If true, only include symbols with at least one setup streak across the last 2 available screener snapshots (bullish or bearish).",
    ),
    setup_styles: Optional[List[str]] = Query(
        None,
        description="Optional setup tags (e.g., momentum, breakout) requiring at least one hit in the last 3 available screener snapshots.",
    ),
    setup_bias: str = Query(
        "both",
        pattern="^(both|bullish|bearish)$",
        description="When setup_styles are provided: filter to bullish (long), bearish (short), or both.",
    ),
    setup_logic: str = Query(
        "any",
        pattern="^(any|all)$",
        description="When multiple setup_styles are provided: any (OR) or all (AND).",
    ),
):
    """Get stock grades with filtering and pagination.

    Optimized to avoid N+1 queries; grading is computed in the DB.
    """
    # Attempt cache first
    cache_settings = _get_settings()
    cache_ttl = int(cache_settings.cache_ttl_rankings or 300)
    search_normalized = (search or "").strip()
    setup_styles_cache = ",".join(
        sorted({(s or "").strip().lower() for s in (setup_styles or []) if (s or "").strip()})
    )
    # Bump cache prefix to invalidate stale keys after grading logic changes
    cache_key = make_key(
        "grades_v8",
        {
            "skip": skip,
            "limit": limit,
            "min_grade": min_grade or "",
            "max_grade": max_grade or "",
            "sector": sector or "",
            "sort_by": sort_by,
            "sort_order": sort_order,
            "search": search_normalized,
            "tracked_only": tracked_only,
            "as_of": str(as_of) if as_of is not None else "",
            "has_setup": has_setup,
            "setup_styles": setup_styles_cache,
            "setup_bias": setup_bias,
            "setup_logic": setup_logic,
        },
    )
    cached = get_json(cache_key)
    if cached is not None:
        return cached

    # If as_of is provided, use the as-of SQL function and paginate/filter in SQL.
    if as_of is not None:
        if setup_styles or has_setup:
            raise HTTPException(
                status_code=400,
                detail="setup filters are only supported for the latest snapshot (omit as_of).",
            )
        # Build SQL WHERE clauses safely with parameters
        filters = ["1=1"]
        params: Dict[str, Any] = {"as_of": as_of, "limit": limit, "offset": skip}
        if sector:
            filters.append("sector = :sector")
            params["sector"] = sector
        if tracked_only:
            filters.append("momentum_score IS NOT NULL AND value_score IS NOT NULL")
        else:
            grade_to_ord = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
            if min_grade:
                params["min_ord"] = grade_to_ord[min_grade.upper()]
                filters.append("grade_order >= :min_ord")
            if max_grade:
                params["max_ord"] = grade_to_ord[max_grade.upper()]
                filters.append("grade_order <= :max_ord")
        metric_sort_col = _metric_sort_column_name(sort_by)
        if metric_sort_col is not None:
            filters.append(f"{metric_sort_col} IS NOT NULL")
        if search:
            search_trimmed = search.strip()
            filters.append("(symbol ILIKE :q OR company_name ILIKE :q)")
            params["q"] = f"%{search_trimmed}%"
            params["q_exact"] = search_trimmed.upper()
            params["q_prefix"] = f"{search_trimmed}%"

        # Sorting mapping
        sort_map = {
            "grade": "grade_order",
            "momentum": "momentum_score",
            "value": "value_score",
            "sentiment": "sentiment_score",
            "symbol": "symbol",
        }
        order_col = sort_map.get(sort_by, "grade_order")
        order_dir = "DESC" if sort_order == "desc" else "ASC"

        order_priority: list[str] = []
        if search:
            order_priority.append("CASE WHEN upper(trim(symbol)) = :q_exact THEN 0 ELSE 1 END")
            order_priority.append("CASE WHEN symbol ILIKE :q_prefix THEN 0 ELSE 1 END")
        order_term = f"{order_col} {order_dir}"
        if metric_sort_col is not None:
            order_term = f"{order_term} NULLS LAST"
        order_clause = ", ".join(order_priority + [order_term, "symbol ASC"])
        sql_base = (
            "WITH g AS (SELECT * FROM rankalpha.fn_grades_as_of(:as_of)) "
            "SELECT as_of_date, symbol, company_name, sector, exchange, momentum_score, value_score, sentiment_score, avg_score, grade, grade_order "
            f"FROM g WHERE {' AND '.join(filters)} ORDER BY {order_clause} LIMIT :limit OFFSET :offset"
        )
        rows = db.execute(text(sql_base), params).all()
        # total count
        cnt = (
            db.execute(
                text(
                    f"WITH g AS (SELECT * FROM rankalpha.fn_grades_as_of(:as_of)) SELECT COUNT(*) FROM g WHERE {' AND '.join(filters)}"
                ),
                params,
            ).scalar()
            or 0
        )

        stocks: List[StockGrade] = []
        for r in rows:
            grade_str = str(r.grade) if r.grade is not None else "N/A"
            expl = explain_grade_from_db(
                grade_str,
                float(r.momentum_score) if r.momentum_score is not None else None,
                float(r.value_score) if r.value_score is not None else None,
                float(r.sentiment_score) if r.sentiment_score is not None else None,
            )
            stocks.append(
                StockGrade(
                    symbol=r.symbol,
                    company_name=r.company_name,
                    date=r.as_of_date,
                    momentum_score=float(r.momentum_score)
                    if r.momentum_score is not None
                    else None,
                    value_score=float(r.value_score) if r.value_score is not None else None,
                    sentiment_score=float(r.sentiment_score)
                    if r.sentiment_score is not None
                    else None,
                    overall_grade=grade_str,
                    grade_explanation=expl,
                    confidence="Medium",
                )
            )

        result = GradeLeaderboard(
            stocks=stocks,
            total_count=int(cnt),
            page=skip // limit + 1,
            page_size=limit,
            ai_preview=None,
        )
        payload = {
            "stocks": [s.model_dump() for s in result.stocks],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
            "ai_preview": {},
        }
        set_json(cache_key, payload, ttl_secs=cache_ttl)
        return payload

    # Resolve latest date + date_key once to enable partition pruning
    # Try fast path using materialized view if available
    try:
        grade_to_ord = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
        mv = MvLatestGrades
        criteria: list[Any] = []

        def _active_symbols_criterion(*, require_eligible: bool) -> Any:
            """Build the active/eligible universe restriction.

            In some deployments `mv_universe_eligible` may be temporarily empty
            (e.g., right after migrations/refresh failures). In that case, a hard
            requirement would exclude everything and make Rankings appear empty.
            """

            active = select(DimStock.symbol).where(DimStock.is_active.is_(True))
            if require_eligible:
                active = active.where(
                    DimStock.symbol.in_(
                        select(MvUniverseEligible.symbol).where(
                            MvUniverseEligible.eligible.is_(True)
                        )
                    )
                )
            return mv.symbol.in_(active)

        require_eligible_universe = True
        # Prefer restricting to the eligible universe; relax to active-only if the
        # eligibility MV is empty/broken (handled after the initial query).
        criteria.append(_active_symbols_criterion(require_eligible=True))
        # sector filter
        if sector:
            criteria.append(mv.sector == sector)
        # grade filters (skip when tracked_only to avoid excluding MV rows with N/A grade but M/V present)
        if not tracked_only:
            if min_grade and max_grade and min_grade == max_grade:
                # Exact letter (normalize) OR exact order (defensive against any mismatch)
                letter = (min_grade or "").strip().upper()
                exact_ord = grade_to_ord.get(letter)
                if exact_ord is not None:
                    criteria.append(
                        or_(
                            func.upper(func.trim(mv.grade)) == letter,
                            and_(mv.grade_order >= exact_ord, mv.grade_order <= exact_ord),
                        )
                    )
            else:
                if min_grade:
                    criteria.append(
                        mv.grade_order >= grade_to_ord[(min_grade or "").strip().upper()]
                    )
                if max_grade:
                    criteria.append(
                        mv.grade_order <= grade_to_ord[(max_grade or "").strip().upper()]
                    )
        else:
            # Tracked definition: momentum & value present; sentiment optional
            criteria.append(and_(mv.momentum_score.isnot(None), mv.value_score.isnot(None)))

        if search_normalized:
            pattern = f"%{search_normalized}%"
            criteria.append(
                or_(
                    mv.symbol.ilike(pattern),
                    mv.company_name.ilike(pattern),
                )
            )
        metric_col_name = _metric_sort_column_name(sort_by)
        if metric_col_name == "momentum_score":
            criteria.append(mv.momentum_score.isnot(None))
        elif metric_col_name == "value_score":
            criteria.append(mv.value_score.isnot(None))
        elif metric_col_name == "sentiment_score":
            criteria.append(mv.sentiment_score.isnot(None))

        bucket_label_sql = setup_bucket_label_expr(
            style_name_col=DimStyle.style_name,
            source_name_col=DimSource.source_name,
        )

        if has_setup and not setup_styles:
            last2_date_keys = (
                db.execute(
                    select(FactScreenerRank.date_key)
                    .distinct()
                    .order_by(FactScreenerRank.date_key.desc())
                    .limit(2)
                )
                .scalars()
                .all()
            )
            if len(last2_date_keys) < 2:
                criteria.append(literal(False))
            else:
                bucketed = bucket_label_sql.label("bucket_label")
                side = case(
                    (DimStyle.position_side == "short", literal("bearish")),
                    else_=literal("bullish"),
                ).label("side")
                grouped = (
                    select(DimStock.symbol)
                    .select_from(FactScreenerRank)
                    .join(DimStock, DimStock.stock_key == FactScreenerRank.stock_key)
                    .join(DimSource, DimSource.source_key == FactScreenerRank.source_key)
                    .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRank.style_key)
                    .where(
                        and_(
                            FactScreenerRank.date_key.in_(last2_date_keys),
                            DimStock.is_active.is_(True),
                        )
                    )
                    .add_columns(
                        bucketed,
                        side,
                        func.count(func.distinct(FactScreenerRank.date_key)).label("day_count"),
                    )
                    .group_by(DimStock.symbol, bucketed, side)
                    .having(
                        func.count(func.distinct(FactScreenerRank.date_key)) >= len(last2_date_keys)
                    )
                ).subquery("setup_any_streak")
                criteria.append(mv.symbol.in_(select(grouped.c.symbol).distinct()))

        setup_styles_norm = [
            (s or "").strip().lower() for s in (setup_styles or []) if (s or "").strip()
        ]
        if setup_styles_norm:
            allowed = set(SETUP_TAXONOMY_SLUGS)
            unknown = sorted(set(setup_styles_norm) - allowed)
            if unknown:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported setup_styles: {', '.join(unknown)}"
                )

            last3_date_keys = (
                db.execute(
                    select(FactScreenerRank.date_key)
                    .distinct()
                    .order_by(FactScreenerRank.date_key.desc())
                    .limit(3)
                )
                .scalars()
                .all()
            )
            if len(last3_date_keys) < 3:
                criteria.append(literal(False))
            else:
                side_filter = None
                if setup_bias == "bullish":
                    side_filter = "long"
                elif setup_bias == "bearish":
                    side_filter = "short"

                def setup_subquery(slug: str):
                    base = (
                        select(DimStock.symbol)
                        .select_from(FactScreenerRank)
                        .join(DimStock, DimStock.stock_key == FactScreenerRank.stock_key)
                        .join(DimSource, DimSource.source_key == FactScreenerRank.source_key)
                        .outerjoin(DimStyle, DimStyle.style_key == FactScreenerRank.style_key)
                        .where(
                            and_(
                                FactScreenerRank.date_key.in_(last3_date_keys),
                                DimStock.is_active.is_(True),
                            )
                        )
                    )
                    if side_filter:
                        base = base.where(DimStyle.position_side == side_filter)

                    try:
                        base = base.where(
                            setup_style_filter_expr(
                                slug=slug,
                                style_name_col=DimStyle.style_name,
                                source_name_col=DimSource.source_name,
                            )
                        )
                    except ValueError:
                        raise HTTPException(
                            status_code=400, detail=f"Unsupported setup style: {slug}"
                        )

                    return (
                        base.group_by(DimStock.symbol)
                        .having(func.count(func.distinct(FactScreenerRank.date_key)) >= 1)
                        .distinct()
                    )

                conds = [mv.symbol.in_(setup_subquery(slug)) for slug in setup_styles_norm]
                if setup_logic == "all":
                    criteria.append(and_(*conds))
                else:
                    criteria.append(or_(*conds))

        # Sorting
        order_cols: list[Any] = []
        if search_normalized:
            search_upper = search_normalized.upper()
            exact_match_first = case(
                (func.upper(func.trim(mv.symbol)) == literal(search_upper), 0),
                else_=1,
            )
            prefix_match_first = case(
                (mv.symbol.ilike(literal(f"{search_normalized}%")), 0),
                else_=1,
            )
            order_cols.extend([exact_match_first.asc(), prefix_match_first.asc()])
        if sort_by == "grade":
            # Push incomplete rows (missing M or V) after complete ones; then sort by grade
            completeness = case(
                (and_(mv.momentum_score.isnot(None), mv.value_score.isnot(None)), 0), else_=1
            )
            order_cols.extend(
                [
                    completeness.asc(),
                    mv.grade_order.desc() if sort_order == "desc" else mv.grade_order.asc(),
                    mv.symbol.asc(),
                ]
            )
        elif sort_by == "momentum":
            metric_order = _metric_sort_order_expr(
                sort_by,
                sort_order,
                momentum_col=mv.momentum_score,
                value_col=mv.value_score,
                sentiment_col=mv.sentiment_score,
            )
            order_cols.extend(
                [
                    metric_order,
                    mv.symbol.asc(),
                ]
            )
        elif sort_by == "value":
            metric_order = _metric_sort_order_expr(
                sort_by,
                sort_order,
                momentum_col=mv.momentum_score,
                value_col=mv.value_score,
                sentiment_col=mv.sentiment_score,
            )
            order_cols.extend(
                [
                    metric_order,
                    mv.symbol.asc(),
                ]
            )
        elif sort_by == "sentiment":
            metric_order = _metric_sort_order_expr(
                sort_by,
                sort_order,
                momentum_col=mv.momentum_score,
                value_col=mv.value_score,
                sentiment_col=mv.sentiment_score,
            )
            order_cols.extend(
                [
                    metric_order,
                    mv.symbol.asc(),
                ]
            )
        else:
            order_cols.append(mv.symbol.desc() if sort_order == "desc" else mv.symbol.asc())

        has_user_filters = bool(
            sector
            or search_normalized
            or min_grade
            or max_grade
            or tracked_only
            or has_setup
            or (setup_styles is not None and len(setup_styles) > 0)
        )

        def _fetch_rows() -> list[Any]:
            sub = (
                select(
                    mv.symbol,
                    mv.company_name,
                    mv.momentum_score,
                    mv.value_score,
                    mv.sentiment_score,
                    mv.avg_score,
                    mv.grade,
                    mv.grade_order,
                    mv.as_of_date,
                )
                .select_from(mv)
                .where(*criteria)
                .order_by(*order_cols)
                .offset(skip)
                .limit(limit)
            )
            return cast(list[Any], db.execute(sub).all())

        rows = _fetch_rows()

        # If eligibility is broken (no TRUE rows), retry without it.
        if not rows and require_eligible_universe:
            try:
                eligible_true_any = db.execute(
                    select(literal(1))
                    .select_from(MvUniverseEligible)
                    .where(MvUniverseEligible.eligible.is_(True))
                    .limit(1)
                ).scalar_one_or_none()
            except Exception:
                eligible_true_any = True  # keep strict default on errors
            if eligible_true_any is None:
                require_eligible_universe = False
                criteria[0] = _active_symbols_criterion(require_eligible=False)
                rows = _fetch_rows()

        if not rows and skip == 0:
            # If mv_latest_grades is empty (not refreshed), fall back to on-the-fly computation.
            mv_any = db.execute(select(literal(1)).select_from(mv).limit(1)).scalar_one_or_none()
            if mv_any is None:
                # Setup filters are only implemented against the materialized view path.
                # If the MV isn't populated yet, fail loudly rather than returning
                # misleading, unfiltered results from the fallback path.
                if has_setup or (setup_styles is not None and len(setup_styles) > 0):
                    raise HTTPException(
                        status_code=503,
                        detail="Grades materialized views are empty; setup filters are unavailable until the pipeline refreshes.",
                    )
                raise RuntimeError("mv_latest_grades is empty")

            # If the default view is empty but the MV has rows, fall back to the
            # on-the-fly path to avoid a blank Rankings page during partial refreshes.
            if not has_user_filters and not rows:
                raise RuntimeError("MV-backed rankings returned empty for default view")

        count_key = make_key(
            "grades_count_v1",
            {
                "min_grade": min_grade or "",
                "max_grade": max_grade or "",
                "sector": sector or "",
                "search": search_normalized,
                "tracked_only": tracked_only,
                "has_setup": has_setup,
                "setup_styles": setup_styles_cache,
                "setup_bias": setup_bias,
                "setup_logic": setup_logic,
                # Sorting affects count only when sentiment requires non-null values.
                "sort_by": sort_by,
                "eligible_only": require_eligible_universe,
            },
        )
        cached_count = get_json(count_key)
        if isinstance(cached_count, int):
            total_count = cached_count
        else:
            if skip == 0 and not rows:
                total_count = 0
            else:
                total_count = int(
                    db.execute(select(func.count()).select_from(mv).where(*criteria)).scalar() or 0
                )
            set_json(count_key, total_count, ttl_secs=cache_ttl)

        stocks: list[StockGrade] = []
        symbols: list[str] = []
        for r in rows:
            # Use DB grade as source of truth; compute explanation separately
            grade_str = str(r.grade) if getattr(r, "grade", None) is not None else "N/A"
            expl = explain_grade_from_db(
                grade_str,
                float(r.momentum_score) if r.momentum_score is not None else None,
                float(r.value_score) if r.value_score is not None else None,
                float(r.sentiment_score) if r.sentiment_score is not None else None,
            )
            stocks.append(
                StockGrade(
                    symbol=r.symbol,
                    company_name=r.company_name,
                    date=r.as_of_date,
                    momentum_score=float(r.momentum_score)
                    if r.momentum_score is not None
                    else None,
                    value_score=float(r.value_score) if r.value_score is not None else None,
                    sentiment_score=float(r.sentiment_score)
                    if r.sentiment_score is not None
                    else None,
                    overall_grade=grade_str,
                    grade_explanation=expl,
                    confidence="Medium" if r.momentum_score is not None else "Low",
                )
            )
            symbols.append(r.symbol)

        # Batch AI preview for these symbols
        preview_map: Dict[str, AiPreview] = {}
        if symbols:
            try:
                raw = preview_map_for_symbols(db, symbols)
                preview_map = {sym: AiPreview(**payload) for sym, payload in raw.items()}
            except Exception:
                preview_map = {}

        result = GradeLeaderboard(
            stocks=stocks,
            total_count=total_count,
            page=skip // limit + 1,
            page_size=limit,
            ai_preview=preview_map or None,
        )
        payload = {
            "stocks": [s.model_dump() for s in result.stocks],
            "total_count": result.total_count,
            "page": result.page,
            "page_size": result.page_size,
            "ai_preview": {k: v.model_dump() for k, v in (preview_map or {}).items()},
        }
        set_json(cache_key, payload, ttl_secs=cache_ttl)
        return payload
    except HTTPException:
        raise
    except Exception:
        # Fall back to on-the-fly computation
        pass

    latest = db.execute(
        select(DimDate.date_key, DimDate.full_date)
        .join(FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key)
        .order_by(DimDate.full_date.desc())
        .limit(1)
    ).one_or_none()
    if not latest:
        return GradeLeaderboard(stocks=[], total_count=0, page=1, page_size=limit)
    latest_date_key, latest_date = latest

    if not latest_date:
        return GradeLeaderboard(stocks=[], total_count=0, page=1, page_size=limit)

    # Identify momentum score_type_key to hit partitioned fact table directly (faster than view)
    linreg200 = db.execute(
        select(DimScoreType.score_type_key).where(
            DimScoreType.score_type_name == "linear regression 200"
        )
    ).scalar_one_or_none()

    # Subquery: momentum (raw slope) at latest date from fact table (partition-pruned)
    if linreg200 is not None:
        # Aggregate to one row per symbol to avoid duplicates from multiple sources
        momentum_base = (
            select(
                DimStock.symbol.label("m_symbol"),
                func.max(FactScoreHistory.score).label("momentum_raw"),
            )
            .join(FactScoreHistory, FactScoreHistory.stock_key == DimStock.stock_key)
            .where(
                and_(
                    FactScoreHistory.date_key == latest_date_key,
                    FactScoreHistory.score_type_key == linreg200,
                )
            )
            .group_by(DimStock.symbol)
        )
    else:
        # Fallback to the view if score_type lookup failed (should be rare)
        momentum_base = (
            select(
                VwScoreHistory.symbol.label("m_symbol"),
                func.max(VwScoreHistory.score).label("momentum_raw"),
            )
            .where(
                and_(
                    VwScoreHistory.score_type_name == "linear regression 200",
                    VwScoreHistory.as_of_date == latest_date,
                )
            )
            .group_by(VwScoreHistory.symbol)
        )

    momentum_sq = momentum_base.subquery()

    # Percentiles for winsorization across today's momentum distribution (deduped per symbol)
    p05 = (
        select(func.percentile_cont(0.05).within_group(momentum_sq.c.momentum_raw))
        .select_from(momentum_sq)
        .scalar_subquery()
    )
    p95 = (
        select(func.percentile_cont(0.95).within_group(momentum_sq.c.momentum_raw))
        .select_from(momentum_sq)
        .scalar_subquery()
    )

    # Subquery: AI analysis (latest per symbol via view)
    ai_sq = select(
        VwAiAnalysisLatest.symbol.label("a_symbol"),
        VwAiAnalysisLatest.value_score,
        VwAiAnalysisLatest.news_sentiment_30d,
    ).subquery()

    # Subquery: Sentiment proxy per symbol via materialized view
    sent_sq = select(
        MvSentimentProxy.symbol.label("s_symbol"),
        MvSentimentProxy.sentiment_proxy_score.label("s_score"),
    ).subquery()

    # Expressions for computed scores
    # NOTE: Momentum normalization matches prior behavior: (raw + 1) * 50
    # Normalize raw slope to 0–100 using winsorized [p05, p95] and clamp
    # If momentum view had duplicates, aggregate to one per symbol first
    m_sq = (
        select(momentum_sq.c.m_symbol, func.max(momentum_sq.c.momentum_raw).label("mom_raw"))
        .group_by(momentum_sq.c.m_symbol)
        .subquery()
    )
    momentum_score_expr = case(
        (
            m_sq.c.m_symbol.isnot(None),
            func.least(
                100.0,
                func.greatest(
                    0.0,
                    ((m_sq.c.mom_raw - p05) / func.nullif(p95 - p05, 0.0)) * 100.0,
                ),
            ),
        ),
        else_=None,
    ).label("momentum_score")

    sentiment_0_100_expr = sent_sq.c.s_score.label("sentiment_score")

    # Build main query
    base = (
        select(
            DimStock.symbol.label("symbol"),
            DimStock.company_name.label("company_name"),
            momentum_score_expr,
            ai_sq.c.value_score.label("value_score"),
            sentiment_0_100_expr,
        )
        .select_from(DimStock)
        .join(m_sq, m_sq.c.m_symbol == DimStock.symbol, isouter=True)
        .join(ai_sq, ai_sq.c.a_symbol == DimStock.symbol, isouter=True)
        .join(sent_sq, sent_sq.c.s_symbol == DimStock.symbol, isouter=True)
        .where(DimStock.is_active.is_(True))
    )

    if sector:
        base = base.where(DimStock.sector == sector)

    search_normalized_fb = (search or "").strip()
    if search_normalized_fb:
        pattern = f"%{search_normalized_fb}%"
        base = base.where(
            or_(
                DimStock.symbol.ilike(pattern),
                DimStock.company_name.ilike(pattern),
            )
        )

    # Compute average and grade in SQL
    base_sq = base.subquery()
    m = base_sq.c.momentum_score
    v = base_sq.c.value_score
    s = base_sq.c.sentiment_score
    non_null_count = (
        (case((m.isnot(None), 1), else_=0))
        + (case((v.isnot(None), 1), else_=0))
        + (case((s.isnot(None), 1), else_=0))
    ).label("score_count")
    # Require momentum and value to be present for avg_score; sentiment optional
    avg_score = case(
        (
            and_(m.isnot(None), v.isnot(None)),
            (func.coalesce(m, 0) + func.coalesce(v, 0) + func.coalesce(s, 0))
            / func.nullif(non_null_count, 0),
        ),
        else_=None,
    ).label("avg_score")

    grade_case = case(
        (avg_score >= 90, literal("A")),
        (avg_score >= 70, literal("B")),
        (avg_score >= 45, literal("C")),
        (avg_score >= 20, literal("D")),
        (avg_score.isnot(None), literal("F")),
        else_=literal("N/A"),
    ).label("grade")

    # Grade ordering helper for sorting/filtering
    grade_order = case(
        (grade_case == "A", 5),
        (grade_case == "B", 4),
        (grade_case == "C", 3),
        (grade_case == "D", 2),
        (grade_case == "F", 1),
        else_=0,
    ).label("grade_order")

    query = select(
        base_sq.c.symbol,
        base_sq.c.company_name,
        m.label("momentum_score"),
        v.label("value_score"),
        s.label("sentiment_score"),
        avg_score,
        grade_case.label("grade"),
        grade_order,
    ).select_from(base_sq)

    # Apply grade filters (map letters to grade_order)
    grade_to_ord = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
    if not tracked_only:
        # min_grade = at least this grade (A best → higher order)
        if min_grade:
            query = query.where(grade_order >= grade_to_ord[min_grade])
        # max_grade = at most this grade (worse or equal)
        if max_grade:
            query = query.where(grade_order <= grade_to_ord[max_grade])
    else:
        # Tracked definition: both momentum and value present
        query = query.where(and_(m.isnot(None), v.isnot(None)))
    metric_col_name_fb = _metric_sort_column_name(sort_by)
    if metric_col_name_fb == "momentum_score":
        query = query.where(m.isnot(None))
    elif metric_col_name_fb == "value_score":
        query = query.where(v.isnot(None))
    elif metric_col_name_fb == "sentiment_score":
        query = query.where(s.isnot(None))

    # One-shot fetch with total_count as a window function to avoid an extra round-trip
    # Build outer select with ordering applied at the top level (ORDER BY inside subqueries is not guaranteed)
    filtered = query.subquery()
    order_cols = []
    if search_normalized_fb:
        search_upper_fb = search_normalized_fb.upper()
        exact_match_first_fb = case(
            (func.upper(func.trim(filtered.c.symbol)) == literal(search_upper_fb), 0),
            else_=1,
        )
        prefix_match_first_fb = case(
            (filtered.c.symbol.ilike(literal(f"{search_normalized_fb}%")), 0),
            else_=1,
        )
        order_cols.extend([exact_match_first_fb.asc(), prefix_match_first_fb.asc()])
    if sort_by == "grade":
        # Push incomplete rows (missing M or V) after complete ones; then sort by grade
        completeness = case(
            (and_(filtered.c.momentum_score.isnot(None), filtered.c.value_score.isnot(None)), 0),
            else_=1,
        )
        order_cols.append(completeness.asc())
        order_cols.append(
            filtered.c.grade_order.desc() if sort_order == "desc" else filtered.c.grade_order.asc()
        )
    elif sort_by == "momentum":
        metric_order = _metric_sort_order_expr(
            sort_by,
            sort_order,
            momentum_col=filtered.c.momentum_score,
            value_col=filtered.c.value_score,
            sentiment_col=filtered.c.sentiment_score,
        )
        order_cols.append(metric_order)
    elif sort_by == "value":
        metric_order = _metric_sort_order_expr(
            sort_by,
            sort_order,
            momentum_col=filtered.c.momentum_score,
            value_col=filtered.c.value_score,
            sentiment_col=filtered.c.sentiment_score,
        )
        order_cols.append(metric_order)
    elif sort_by == "sentiment":
        metric_order = _metric_sort_order_expr(
            sort_by,
            sort_order,
            momentum_col=filtered.c.momentum_score,
            value_col=filtered.c.value_score,
            sentiment_col=filtered.c.sentiment_score,
        )
        order_cols.append(metric_order)
    else:
        order_cols.append(
            filtered.c.symbol.desc() if sort_order == "desc" else filtered.c.symbol.asc()
        )
    order_cols.append(filtered.c.symbol.asc())  # stable tie-breaker

    outer = (
        select(
            filtered.c.symbol,
            filtered.c.company_name,
            filtered.c.momentum_score,
            filtered.c.value_score,
            filtered.c.sentiment_score,
            filtered.c.avg_score,
            filtered.c.grade,
            filtered.c.grade_order,
            func.count().over().label("_total_count"),
        )
        .select_from(filtered)
        .order_by(*order_cols)
        .offset(skip)
        .limit(limit)
    )

    rows = db.execute(outer).all()
    total_count = int(rows[0]._total_count) if rows else 0

    stocks: list[StockGrade] = []
    symbols: list[str] = []
    for r in rows:
        # Use grade computed in SQL; build explanation via helper
        grade_str = str(r.grade) if getattr(r, "grade", None) is not None else "N/A"
        expl = explain_grade_from_db(
            grade_str,
            float(r.momentum_score) if r.momentum_score is not None else None,
            float(r.value_score) if r.value_score is not None else None,
            float(r.sentiment_score) if r.sentiment_score is not None else None,
        )
        stocks.append(
            StockGrade(
                symbol=r.symbol,
                company_name=r.company_name,
                date=latest_date,
                momentum_score=float(r.momentum_score) if r.momentum_score is not None else None,
                value_score=float(r.value_score) if r.value_score is not None else None,
                sentiment_score=float(r.sentiment_score) if r.sentiment_score is not None else None,
                overall_grade=grade_str,
                grade_explanation=expl,
                confidence="Medium" if r.momentum_score is not None else "Low",
            )
        )
        symbols.append(r.symbol)

    # Batch AI preview for these symbols
    preview_map: Dict[str, AiPreview] = {}
    if symbols:
        try:
            raw = preview_map_for_symbols(db, symbols)
            preview_map = {sym: AiPreview(**payload) for sym, payload in raw.items()}
        except Exception:
            preview_map = {}

    result = GradeLeaderboard(
        stocks=stocks,
        total_count=total_count,
        page=skip // limit + 1,
        page_size=limit,
        ai_preview=preview_map or None,
    )
    # Cache serialized payload
    payload = {
        "stocks": [s.model_dump() for s in result.stocks],
        "total_count": result.total_count,
        "page": result.page,
        "page_size": result.page_size,
        "ai_preview": {k: v.model_dump() for k, v in (preview_map or {}).items()},
    }
    set_json(cache_key, payload, ttl_secs=cache_ttl)
    return payload


@router.get("/grades/batch", response_model=BatchGradesOut)
def get_stock_grades_batch(
    symbols: List[str] = Query(..., description="Repeated symbols query param"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    norm = [s.strip().upper() for s in (symbols or []) if s and s.strip()]
    if not norm:
        raise HTTPException(status_code=400, detail="No symbols provided")
    uniq = list(dict.fromkeys(norm))[:100]

    rows = db.execute(
        select(
            MvLatestGrades.symbol,
            MvLatestGrades.company_name,
            MvLatestGrades.as_of_date,
            MvLatestGrades.grade,
        ).where(MvLatestGrades.symbol.in_(uniq))
    ).all()

    items: list[PeerGrade] = []
    for symbol, company_name, as_of_date, grade in rows:
        grade_str = str(grade) if grade is not None else "N/A"
        items.append(
            PeerGrade(
                symbol=str(symbol),
                company_name=company_name,
                as_of_date=as_of_date,
                overall_grade=grade_str,
            )
        )

    return BatchGradesOut(items=items).model_dump()


@router.get("/peers/similar", response_model=SimilarPeersResponse)
def get_similar_peers(
    symbol: str = Query(..., min_length=1, max_length=20),
    limit: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Return up to N peers in the same sector with closest market caps.
    Uses latest available fundamentals (mktcap) as the source of truth.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol is required")

    stock = db.execute(
        select(DimStock).where(DimStock.symbol == sym, DimStock.is_active.is_(True))
    ).scalar_one_or_none()
    if stock is None:
        raise HTTPException(status_code=404, detail="Symbol not found")

    sector = stock.sector
    if not sector:
        return SimilarPeersResponse(symbol=sym, sector=None, market_cap=None, items=[]).model_dump()

    # Latest market cap for target symbol (fundamentals are stored in millions).
    target_mktcap = db.execute(
        select(VwFinFundamentals.metric_value)
        .where(VwFinFundamentals.symbol == sym, VwFinFundamentals.metric_code == "mktcap")
        .order_by(VwFinFundamentals.as_of_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if target_mktcap is None:
        return SimilarPeersResponse(
            symbol=sym, sector=sector, market_cap=None, items=[]
        ).model_dump()

    target_mktcap_usd = float(target_mktcap) * 1_000_000
    if target_mktcap_usd <= 0:
        return SimilarPeersResponse(
            symbol=sym, sector=sector, market_cap=target_mktcap_usd, items=[]
        ).model_dump()

    latest_subq = (
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

    target_mktcap_mn = float(target_mktcap)
    diff_expr = func.abs(latest_subq.c.metric_value - target_mktcap_mn) / target_mktcap_mn
    rows = db.execute(
        select(
            DimStock.symbol,
            DimStock.company_name,
            DimStock.sector,
            latest_subq.c.metric_value,
            diff_expr.label("market_cap_diff_pct"),
        )
        .join(latest_subq, latest_subq.c.symbol == DimStock.symbol)
        .where(
            DimStock.is_active.is_(True),
            DimStock.sector == sector,
            DimStock.symbol != sym,
            latest_subq.c.rn == 1,
            latest_subq.c.metric_value.isnot(None),
            latest_subq.c.metric_value > 0,
        )
        .order_by(diff_expr.asc(), DimStock.symbol.asc())
        .limit(limit)
    ).all()
    items = [
        SimilarPeerItem(
            symbol=str(peer_symbol),
            company_name=company_name,
            sector=peer_sector,
            market_cap=float(metric_value) * 1_000_000 if metric_value is not None else None,
            market_cap_diff_pct=float(diff_pct) if diff_pct is not None else None,
        )
        for peer_symbol, company_name, peer_sector, metric_value, diff_pct in rows
    ]
    return SimilarPeersResponse(
        symbol=sym, sector=sector, market_cap=target_mktcap_usd, items=items
    ).model_dump()


@router.get("/grades/{symbol}", response_model=StockGrade)
def get_stock_grade(symbol: str, db: Session = Depends(get_db)):
    """
    Get grade for a specific stock.
    """
    stock = db.execute(
        select(DimStock).where(
            func.upper(DimStock.symbol) == symbol.upper(), DimStock.is_active.is_(True)
        )
    ).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Cache lookup
    cache_settings = _get_settings()
    grade_ttl = int((cache_settings.cache_ttl_stock_detail or 600))
    cache_key = make_key("grade", {"symbol": symbol.upper()})
    cached = get_json(cache_key)
    if cached is not None:
        # Return as model for reuse within API
        return StockGrade(**cached)

    # Fast path: use materialized latest-grade view to mirror listings exactly
    try:
        mv_row = db.execute(
            select(MvLatestGrades).where(MvLatestGrades.symbol == stock.symbol).limit(1)
        ).scalar_one_or_none()
        if mv_row is not None:
            grade_str = str(mv_row.grade) if getattr(mv_row, "grade", None) is not None else "N/A"
            # If DB grade is missing but M & V exist, compute a safe fallback grade locally
            if (
                (not grade_str or grade_str.upper() == "N/A")
                and mv_row.momentum_score is not None
                and mv_row.value_score is not None
            ):
                grade_str, _ = calculate_letter_grade(
                    float(mv_row.momentum_score),
                    float(mv_row.value_score),
                    float(mv_row.sentiment_score) if mv_row.sentiment_score is not None else None,
                )
            expl = explain_grade_from_db(
                grade_str,
                float(mv_row.momentum_score) if mv_row.momentum_score is not None else None,
                float(mv_row.value_score) if mv_row.value_score is not None else None,
                float(mv_row.sentiment_score) if mv_row.sentiment_score is not None else None,
            )
            result = StockGrade(
                symbol=mv_row.symbol,
                company_name=mv_row.company_name,
                date=mv_row.as_of_date,
                momentum_score=float(mv_row.momentum_score)
                if mv_row.momentum_score is not None
                else None,
                value_score=float(mv_row.value_score) if mv_row.value_score is not None else None,
                sentiment_score=float(mv_row.sentiment_score)
                if mv_row.sentiment_score is not None
                else None,
                overall_grade=grade_str,
                grade_explanation=expl,
                confidence="Medium" if mv_row.momentum_score is not None else "Low",
            )
            # Cache and return
            set_json(cache_key, result.model_dump(), ttl_secs=grade_ttl)
            return result
    except Exception:
        # Fall through to on-the-fly calculation
        pass

    # Fallback: compute on the fly
    latest_date_result = db.execute(
        select(func.max(DimDate.full_date)).join(
            FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key
        )
    ).scalar()
    if not latest_date_result:
        raise HTTPException(status_code=404, detail="No data available")

    # Get scores
    momentum_score = None
    value_score = None
    sentiment_score = None

    # Get momentum (raw slope) and winsorize to 0–100 using today's distribution
    momentum_result = db.execute(
        select(VwScoreHistory.score)
        .where(
            and_(
                VwScoreHistory.symbol == stock.symbol,
                VwScoreHistory.score_type_name == "linear regression 200",
                VwScoreHistory.as_of_date == latest_date_result,
            )
        )
        .limit(1)
    ).scalar()
    if momentum_result is not None:
        pcts = db.execute(
            select(
                func.percentile_cont(0.05).within_group(VwScoreHistory.score),
                func.percentile_cont(0.95).within_group(VwScoreHistory.score),
            ).where(
                and_(
                    VwScoreHistory.score_type_name == "linear regression 200",
                    VwScoreHistory.as_of_date == latest_date_result,
                )
            )
        ).one_or_none()
        if (
            pcts
            and pcts[0] is not None
            and pcts[1] is not None
            and float(pcts[1]) != float(pcts[0])
        ):
            p05, p95 = float(pcts[0]), float(pcts[1])
            momentum_score = max(
                0.0, min(100.0, (float(momentum_result) - p05) / (p95 - p05) * 100.0)
            )

    # Get the latest AI analysis for this symbol via view
    ai_view = db.execute(
        select(VwAiAnalysisLatest).where(VwAiAnalysisLatest.symbol == stock.symbol).limit(1)
    ).scalar_one_or_none()

    if ai_view:
        # Prefer value from AI factor scores in the view
        if ai_view.value_score is not None:
            value_score = float(ai_view.value_score)

    # Sentiment from MV (single source of truth)
    try:
        s_row = db.execute(
            select(MvSentimentProxy.sentiment_proxy_score)
            .where(MvSentimentProxy.symbol == stock.symbol)
            .limit(1)
        ).one_or_none()
        if s_row and s_row[0] is not None:
            sentiment_score = float(s_row[0])
    except Exception:
        pass

    # Default to computed grade from available factor scores; override with DB value when available
    grade, explanation = calculate_letter_grade(momentum_score, value_score, sentiment_score)
    try:
        fn_row = (
            db.execute(
                text(
                    "SELECT symbol, momentum_score, value_score, sentiment_score, grade "
                    "FROM rankalpha.fn_grades_as_of(:as_of) WHERE symbol = :symbol LIMIT 1"
                ),
                {"as_of": latest_date_result, "symbol": stock.symbol},
            )
            .mappings()
            .first()
        )
        if fn_row:
            grade = str(fn_row["grade"]) if fn_row["grade"] is not None else "N/A"
            # Prefer DB values when present
            momentum_score = (
                float(fn_row["momentum_score"])
                if fn_row["momentum_score"] is not None
                else momentum_score
            )
            value_score = (
                float(fn_row["value_score"]) if fn_row["value_score"] is not None else value_score
            )
            sentiment_score = (
                float(fn_row["sentiment_score"])
                if fn_row["sentiment_score"] is not None
                else sentiment_score
            )
            explanation = explain_grade_from_db(grade, momentum_score, value_score, sentiment_score)
    except Exception:
        # Fall back to locally computed grade if DB lookup failed
        grade, explanation = calculate_letter_grade(momentum_score, value_score, sentiment_score)

    # Add AI commentary if available
    if ai_view and getattr(ai_view, "commentary", None):
        explanation += f" AI Analysis: {ai_view.commentary}"

    grade_obj = StockGrade(
        symbol=stock.symbol,
        company_name=stock.company_name,
        date=latest_date_result,
        momentum_score=momentum_score,
        value_score=value_score,
        sentiment_score=sentiment_score,
        overall_grade=grade,
        grade_explanation=explanation,
        confidence="High" if ai_view else "Medium" if momentum_score else "Low",
    )
    # Populate cache for future calls
    set_json(cache_key, grade_obj.model_dump(), ttl_secs=grade_ttl)
    return grade_obj


@router.get("/asset/{symbol}", response_model=AssetDetail)
def get_asset_detail(
    symbol: str, db: Session = Depends(get_db), days: int = Query(90, ge=1, le=365)
):
    """
    Get detailed information for a specific asset including history.
    """
    stock = db.execute(
        select(DimStock).where(
            func.upper(DimStock.symbol) == symbol.upper(), DimStock.is_active.is_(True)
        )
    ).scalar_one_or_none()

    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    # Cache: asset detail by symbol and days
    cache_settings = _get_settings()
    asset_ttl = int((cache_settings.cache_ttl_stock_detail or 600))
    cache_key = make_key("asset", {"symbol": symbol.upper(), "days": days})
    cached = get_json(cache_key)
    if cached is not None:
        return cached

    # Get current grade (includes its own cache)
    current_grade = get_stock_grade(symbol, db)

    # Get score history
    score_history_result = db.execute(
        select(DimDate.full_date, DimScoreType.score_type_name, FactScoreHistory.score)
        .join(DimDate, DimDate.date_key == FactScoreHistory.date_key)
        .join(DimScoreType, DimScoreType.score_type_key == FactScoreHistory.score_type_key)
        .where(
            and_(
                FactScoreHistory.stock_key == stock.stock_key,
                DimDate.full_date >= datetime.now().date() - timedelta(days=days),
            )
        )
        .order_by(DimDate.full_date.desc())
    ).all()

    score_history = [
        {"date": str(date), "score_type": score_type, "score": float(score)}
        for date, score_type, score in score_history_result
    ]

    # Get AI analysis summary via the latest view (one row per symbol)
    ai_view = db.execute(
        select(VwAiAnalysisLatest).where(VwAiAnalysisLatest.symbol == stock.symbol).limit(1)
    ).scalar_one_or_none()
    # Latest sentiment proxy from MV (single source of truth)
    sentiment_proxy_score = None
    sentiment_proxy_date = None
    try:
        sp_row = db.execute(
            select(MvSentimentProxy.sentiment_proxy_score, DimDate.full_date)
            .join(DimDate, DimDate.date_key == MvSentimentProxy.px_date_key)
            .where(MvSentimentProxy.symbol == stock.symbol)
            .limit(1)
        ).one_or_none()
        if sp_row:
            try:
                sentiment_proxy_score = float(sp_row[0]) if sp_row[0] is not None else None
            except Exception:
                sentiment_proxy_score = None
            sentiment_proxy_date = sp_row[1]
    except Exception:
        pass

    recent_news = []
    if ai_view and ai_view.headline_risks:
        # Use aggregated headline_risks from the view
        recent_news = [
            {
                "headline": risk,
                "analysis_date": str(ai_view.as_of_date) if ai_view.as_of_date else None,
                "type": "headline_risk",
            }
            for risk in (ai_view.headline_risks or [])
        ]

    # Latest market cap + beta from fundamentals (source of truth)
    market_cap = None
    beta_value = None
    target_price = None
    projected_lt_growth_rate = None
    next_earnings_date = None
    next_earnings_time = None
    next_earnings_source = None
    try:
        metric_codes = ("mktcap", "beta", "targetprice", "projltgrowthrate")
        latest_subq = (
            select(
                VwFinFundamentals.metric_code.label("metric_code"),
                VwFinFundamentals.metric_value.label("metric_value"),
                func.row_number()
                .over(
                    partition_by=VwFinFundamentals.metric_code,
                    order_by=VwFinFundamentals.as_of_date.desc(),
                )
                .label("rn"),
            )
            .where(
                VwFinFundamentals.symbol == stock.symbol,
                VwFinFundamentals.metric_code.in_(metric_codes),
            )
            .subquery()
        )
        rows = db.execute(
            select(latest_subq.c.metric_code, latest_subq.c.metric_value).where(
                latest_subq.c.rn == 1
            )
        ).all()
        for code, value in rows:
            if value is None:
                continue
            if code == "mktcap":
                # Fundamentals store mktcap in millions; normalize to USD.
                market_cap = float(value) * 1_000_000
            elif code == "beta":
                beta_value = float(value)
            elif code == "targetprice":
                target_price = float(value)
            elif code == "projltgrowthrate":
                projected_lt_growth_rate = float(value)
    except Exception:
        logger.exception(
            "Failed to load fundamentals (mktcap/beta/targetprice/projltgrowthrate) for %s",
            stock.symbol,
        )

    try:
        earnings_row = db.execute(
            select(
                FactStockNextEarnings.earnings_date,
                FactStockNextEarnings.earnings_time,
                FactStockNextEarnings.earnings_source,
            ).where(FactStockNextEarnings.stock_key == stock.stock_key)
        ).one_or_none()
        if earnings_row:
            candidate_date = earnings_row[0]
            if candidate_date and candidate_date >= _market_today():
                next_earnings_date = candidate_date
                next_earnings_time = earnings_row[1]
                next_earnings_source = earnings_row[2]
    except Exception:
        logger.exception("Failed to load next earnings for %s", stock.symbol)

    # Process AI analysis data if available
    ai_analysis_data = None

    if ai_view:
        # Attempt to derive analyst_summary and always extract human-readable commentary
        analyst_summary_obj = None
        commentary_text = ai_view.commentary
        try:
            # Prefer DB-backed summary when present
            if (
                getattr(ai_view, "analyst_bull_case", None)
                or getattr(ai_view, "analyst_bear_case", None)
                or getattr(ai_view, "analyst_valuation_check", None)
            ):
                analyst_summary_obj = {
                    "bull_case": getattr(ai_view, "analyst_bull_case", None),
                    "bear_case": getattr(ai_view, "analyst_bear_case", None),
                    "valuation_check": getattr(ai_view, "analyst_valuation_check", None),
                }
            # Regardless, parse any packed commentary JSON to pull sentiment_commentary text
            if isinstance(ai_view.commentary, str):
                import json as _json

                try:
                    parsed = _json.loads(ai_view.commentary)
                    if isinstance(parsed, dict):
                        # Only use parsed analyst_summary if DB fields are absent
                        if analyst_summary_obj is None and "analyst_summary" in parsed:
                            analyst_summary_obj = parsed.get("analyst_summary")
                        sc = parsed.get("sentiment_commentary")
                        if isinstance(sc, str) and sc:
                            commentary_text = sc
                except Exception:
                    # commentary may be plain text; leave as-is
                    pass
        except Exception:
            # Non-fatal if parsing or attribute access fails
            pass

        ai_analysis_data = {
            "analysis_date": str(ai_view.as_of_date) if ai_view.as_of_date else None,
            "source_name": ai_view.source_name,
            "commentary": commentary_text,
            # Source of truth for market cap / beta is fundamentals, not AI output.
            "market_cap": market_cap
            if market_cap is not None
            else (float(ai_view.market_cap_usd) if ai_view.market_cap_usd is not None else None),
            "beta": beta_value
            if beta_value is not None
            else (float(ai_view.beta_sp500) if ai_view.beta_sp500 is not None else None),
            "news_sentiment_30d": float(ai_view.news_sentiment_30d)
            if ai_view.news_sentiment_30d is not None
            else None,
            "social_sentiment_7d": float(ai_view.social_sentiment_7d)
            if ai_view.social_sentiment_7d is not None
            else None,
            "sentiment_proxy_score": sentiment_proxy_score,
            "sentiment_proxy_date": str(sentiment_proxy_date) if sentiment_proxy_date else None,
            "revenue_cagr_3y": float(ai_view.revenue_cagr_3y_pct)
            if ai_view.revenue_cagr_3y_pct is not None
            else None,
            "rate_sensitivity": float(ai_view.rate_sensitivity_bps)
            if ai_view.rate_sensitivity_bps is not None
            else None,
            "fx_sensitivity": ai_view.fx_sensitivity,
            "commodity_exposure": ai_view.commodity_exposure,
            "options_skew_30d": float(ai_view.options_skew_30d)
            if ai_view.options_skew_30d is not None
            else None,
            "short_interest_pct": float(ai_view.short_interest_pct_float)
            if ai_view.short_interest_pct_float is not None
            else None,
            "employee_score": float(ai_view.employee_glassdoor_score)
            if ai_view.employee_glassdoor_score is not None
            else None,
            "headline_buzz": ai_view.headline_buzz_score,
            # Extra fields from the view
            "valuation": {
                "pe_forward": float(ai_view.pe_forward) if ai_view.pe_forward is not None else None,
                "ev_ebitda_forward": float(ai_view.ev_ebitda_forward)
                if ai_view.ev_ebitda_forward is not None
                else None,
                "pe_percentile_in_sector": float(ai_view.pe_percentile_in_sector)
                if ai_view.pe_percentile_in_sector is not None
                else None,
            },
            "factor_scores": {
                "value": float(ai_view.value_score) if ai_view.value_score is not None else None,
                "quality": float(ai_view.quality_score)
                if ai_view.quality_score is not None
                else None,
                "momentum": float(ai_view.momentum_score)
                if ai_view.momentum_score is not None
                else None,
                "low_vol": float(ai_view.low_vol_score)
                if ai_view.low_vol_score is not None
                else None,
            },
            "scenarios": {
                "bull": {
                    "price": float(ai_view.bull_price_target)
                    if ai_view.bull_price_target is not None
                    else None,
                    "probability_pct": float(ai_view.bull_probability_pct)
                    if ai_view.bull_probability_pct is not None
                    else None,
                },
                "base": {
                    "price": float(ai_view.base_price_target)
                    if ai_view.base_price_target is not None
                    else None,
                    "probability_pct": float(ai_view.base_probability_pct)
                    if ai_view.base_probability_pct is not None
                    else None,
                },
                "bear": {
                    "price": float(ai_view.bear_price_target)
                    if ai_view.bear_price_target is not None
                    else None,
                    "probability_pct": float(ai_view.bear_probability_pct)
                    if ai_view.bear_probability_pct is not None
                    else None,
                },
            },
            "catalysts": {
                "shortTerm": ai_view.short_catalysts if ai_view.short_catalysts is not None else [],
                "longTerm": ai_view.long_catalysts if ai_view.long_catalysts is not None else [],
            },
            "events": ai_view.events if getattr(ai_view, "events", None) is not None else [],
            "risks": {
                "macro": ai_view.macro_risks if ai_view.macro_risks is not None else [],
                "headline": ai_view.headline_risks if ai_view.headline_risks is not None else [],
                "data_gaps": ai_view.data_gaps if ai_view.data_gaps is not None else [],
            },
            "peers": ai_view.peers if ai_view.peers is not None else [],
            "analyst_summary": analyst_summary_obj,
        }

    asset_detail = AssetDetail(
        symbol=stock.symbol,
        company_name=stock.company_name,
        sector=stock.sector,
        exchange=stock.exchange,
        market_cap=market_cap,
        beta=beta_value,
        target_price=target_price,
        projected_lt_growth_rate=projected_lt_growth_rate,
        next_earnings_date=next_earnings_date,
        next_earnings_time=next_earnings_time,
        next_earnings_source=next_earnings_source,
        current_grade=current_grade,
        score_history=score_history,
        recent_news=recent_news,
        ai_analysis=ai_analysis_data,
    )
    set_json(cache_key, asset_detail.model_dump(), ttl_secs=asset_ttl)
    return asset_detail


@router.post(
    "/refresh",
    response_model=GradingRefreshResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_operator_access)],
)
@router.get(
    "/refresh",
    response_model=GradingRefreshResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_operator_access)],
    deprecated=True,
)
def refresh_grading_cache(db: Session = Depends(get_db)):
    """
    Refresh universe eligibility and latest grades, and invalidate caches.

    - Refreshes `mv_universe_eligible` (price/liquidity policy; ETFs included)
    - Refreshes `mv_latest_grades` (composite A–F)
    - Invalidates Redis caches used by grading endpoints and the HTTP cache middleware

    Requires operator/admin privileges (RBAC) or a configured service/admin token.
    """
    # In a production system, this would clear any caching layer
    # For now, we just verify the data is fresh
    latest_date = db.execute(
        select(func.max(DimDate.full_date)).join(
            FactScoreHistory, FactScoreHistory.date_key == DimDate.date_key
        )
    ).scalar()

    # Invalidate cached pages so the frontend picks up fresh data
    invalidated = {
        "grades": invalidate_prefix("grades:"),
        "grades_v2": invalidate_prefix("grades_v2:"),
        "grades_v3": invalidate_prefix("grades_v3:"),
        "grades_v4": invalidate_prefix("grades_v4:"),
        "grades_v7": invalidate_prefix("grades_v7:"),
        "grades_v8": invalidate_prefix("grades_v8:"),
        "grades_count_v1": invalidate_prefix("grades_count_v1:"),
        "grade": invalidate_prefix("grade:"),
        "asset": invalidate_prefix("asset:"),
        "screener_changes": invalidate_prefix("screener_changes:"),
        "screener_breadth": invalidate_prefix("screener_breadth:"),
        "httpcache": invalidate_prefix("httpcache:"),
    }
    # Attempt to refresh materialized views used by grading/universe
    uni_refreshed = False
    try:
        # Universe eligibility first (used by fn_grades_as_of and API filters)
        db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_eligible"))
        db.commit()
        uni_refreshed = True
    except Exception:
        try:
            db.execute(text("REFRESH MATERIALIZED VIEW rankalpha.mv_universe_eligible"))
            db.commit()
            uni_refreshed = True
        except Exception:
            uni_refreshed = False
    try:
        db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_latest_grades"))
        db.commit()
        mv_refreshed = True
    except Exception:
        try:
            db.execute(text("REFRESH MATERIALIZED VIEW rankalpha.mv_latest_grades"))
            db.commit()
            mv_refreshed = True
        except Exception:
            mv_refreshed = False

    return GradingRefreshResponse(
        status="success",
        message="Universe and grades refreshed; caches invalidated",
        latest_data_date=latest_date,
        timestamp=datetime.now(UTC).isoformat(),
        invalidated_keys=invalidated,
        mv_universe_eligible_refreshed=uni_refreshed,
        mv_latest_grades_refreshed=mv_refreshed,
    )
