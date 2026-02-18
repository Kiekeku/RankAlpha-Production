from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimStock,
    MvAiAnalysisLatestList,
    VwAiAnalysisFull,
)

from ..cache import get_json, make_key, set_json
from ..database import get_db
from ..services.ai_analysis import AiAnalysisCache
from ..services.ai_analysis.utils import list_row_to_dict, preview_map_for_symbols, row_to_dict
from ..settings import Settings
from ..utils.company import CompanyNameSanitizerMixin
from ..utils.date_range import parse_iso_date_range
from ..utils.settings_cache import make_cached_getter


class AiAnalysisItem(CompanyNameSanitizerMixin, BaseModel):
    analysis_id: UUID
    as_of_date: date
    symbol: str
    company_name: Optional[str] = None
    asset_type: Optional[str] = None
    source_name: Optional[str] = None

    market_cap_usd: Optional[float] = None
    revenue_cagr_3y_pct: Optional[float] = None

    gross_margin_trend: Optional[str] = None
    net_margin_trend: Optional[str] = None
    free_cash_flow_trend: Optional[str] = None
    insider_activity: Optional[str] = None

    beta_sp500: Optional[float] = None
    rate_sensitivity_bps: Optional[float] = None
    fx_sensitivity: Optional[str] = None
    commodity_exposure: Optional[str] = None

    news_sentiment_30d: Optional[float] = None
    social_sentiment_7d: Optional[float] = None
    options_skew_30d: Optional[float] = None
    short_interest_pct_float: Optional[float] = None
    employee_glassdoor_score: Optional[float] = None
    headline_buzz_score: Optional[str] = None
    commentary: Optional[str] = None
    analyst_summary: Optional[Dict[str, Any]] = None

    overall_rating: Optional[str] = None
    confidence: Optional[str] = None
    recommendation_timeframe: Optional[str] = None

    pe_forward: Optional[float] = None
    ev_ebitda_forward: Optional[float] = None
    pe_percentile_in_sector: Optional[float] = None

    value_score: Optional[float] = None
    quality_score: Optional[float] = None
    momentum_score: Optional[float] = None
    low_vol_score: Optional[float] = None

    bull_price_target: Optional[float] = None
    bull_probability_pct: Optional[float] = None
    base_price_target: Optional[float] = None
    base_probability_pct: Optional[float] = None
    bear_price_target: Optional[float] = None
    bear_probability_pct: Optional[float] = None

    short_catalysts: Optional[List[Dict[str, Any]]] = None
    long_catalysts: Optional[List[Dict[str, Any]]] = None
    events: Optional[List[Dict[str, Any]]] = None
    macro_risks: Optional[List[str]] = None
    headline_risks: Optional[List[str]] = None
    data_gaps: Optional[List[str]] = None
    peers: Optional[List[Dict[str, Any]]] = None
    human_analyst_targets_provider: Optional[str] = None
    human_analyst_targets_query: Optional[str] = None
    human_analyst_targets_organic: Optional[List[Dict[str, Any]]] = None
    human_analyst_target_low_usd: Optional[float] = None
    human_analyst_target_high_usd: Optional[float] = None
    human_analyst_target_median_usd: Optional[float] = None
    human_analyst_target_mean_usd: Optional[float] = None
    human_analyst_target_count: Optional[int] = None

    # Proximity (optional)
    price_close: Optional[float] = None
    price_date: Optional[date] = None
    delta_bull_pct: Optional[float] = None
    delta_base_pct: Optional[float] = None
    delta_bear_pct: Optional[float] = None
    nearest_scenario: Optional[str] = None
    nearest_distance_pct: Optional[float] = None


class AiAnalysisList(BaseModel):
    items: List[AiAnalysisItem]
    total_count: int
    page: int
    page_size: int


router = APIRouter(tags=["ai-analysis"], prefix="/api/v1/ai-analysis")
ai_cache = AiAnalysisCache()
_get_settings = make_cached_getter(lambda: Settings())


def _norm_list(values: Optional[Sequence[str]], *, lower: bool = False) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s:
            continue
        out.append(s.lower() if lower else s)
    # stable de-dupe
    return list(dict.fromkeys(out))


@router.get("", response_model=AiAnalysisList)
def list_ai_analyses(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    latest_only_per_symbol: bool = Query(
        False, description="Return only the latest analysis per symbol"
    ),
):
    # Cache key (covers both branches via params)
    settings = _get_settings()
    list_ttl = int(settings.cache_ttl_default or 120)
    cache_key = make_key(
        "ai_list",
        {
            "symbol": (symbol or "").upper(),
            "date_from": date_from or "",
            "date_to": date_to or "",
            "skip": skip,
            "limit": limit,
            "sort_order": sort_order,
            "latest_only": latest_only_per_symbol,
        },
    )
    cached = get_json(cache_key)
    if cached is not None:
        return cached
    df, dt = parse_iso_date_range(date_from, date_to)
    # Build filters once (depending on view selection)
    if latest_only_per_symbol:
        criteria = []
        if symbol:
            criteria.append(MvAiAnalysisLatestList.symbol == symbol.upper())
        if df:
            criteria.append(MvAiAnalysisLatestList.as_of_date >= df)
        if dt:
            criteria.append(MvAiAnalysisLatestList.as_of_date <= dt)

        q = (
            select(MvAiAnalysisLatestList)
            .join(DimStock, DimStock.symbol == MvAiAnalysisLatestList.symbol)
            .where(*(criteria + [DimStock.is_active.is_(True)]))
            .order_by(
                desc(MvAiAnalysisLatestList.as_of_date)
                if sort_order == "desc"
                else asc(MvAiAnalysisLatestList.as_of_date)
            )
            .offset(skip)
            .limit(limit)
        )
        total_count = (
            db.execute(
                select(func.count())
                .select_from(MvAiAnalysisLatestList)
                .join(DimStock, DimStock.symbol == MvAiAnalysisLatestList.symbol)
                .where(*(criteria + [DimStock.is_active.is_(True)]))
            ).scalar()
            or 0
        )
        rows = db.execute(q).scalars().all()
        items = [AiAnalysisItem(**list_row_to_dict(r)) for r in rows]
        result = AiAnalysisList(
            items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
        )
        set_json(cache_key, result.model_dump(), ttl_secs=list_ttl)
        return result
    else:
        criteria = []
        if symbol:
            criteria.append(VwAiAnalysisFull.symbol == symbol.upper())
        if df:
            criteria.append(VwAiAnalysisFull.as_of_date >= df)
        if dt:
            criteria.append(VwAiAnalysisFull.as_of_date <= dt)

        q = (
            select(VwAiAnalysisFull)
            .join(DimStock, DimStock.symbol == VwAiAnalysisFull.symbol)
            .where(*(criteria + [DimStock.is_active.is_(True)]))
            .order_by(
                desc(VwAiAnalysisFull.as_of_date)
                if sort_order == "desc"
                else asc(VwAiAnalysisFull.as_of_date)
            )
            .offset(skip)
            .limit(limit)
        )
        total_count = (
            db.execute(
                select(func.count())
                .select_from(VwAiAnalysisFull)
                .join(DimStock, DimStock.symbol == VwAiAnalysisFull.symbol)
                .where(*(criteria + [DimStock.is_active.is_(True)]))
            ).scalar()
            or 0
        )
        rows = db.execute(q).scalars().all()
        items = [AiAnalysisItem(**row_to_dict(r)) for r in rows]
        result = AiAnalysisList(
            items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
        )
        set_json(cache_key, result.model_dump(), ttl_secs=list_ttl)
        return result


@router.get("/latest", response_model=AiAnalysisList)
def list_ai_analyses_latest(
    db: Session = Depends(get_db),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD inclusive"),
    ratings: Optional[List[str]] = Query(
        None, description="Repeatable. Values: strong_buy|buy|neutral|sell|strong_sell"
    ),
    confidences: Optional[List[str]] = Query(
        None, description="Repeatable. Values: low|medium|high"
    ),
    sectors: Optional[List[str]] = Query(
        None, description="Repeatable. Uses dim_stock.sector values"
    ),
    nearest_scenarios: Optional[List[str]] = Query(
        None, description="Repeatable. Values: bull|base|bear"
    ),
    nearest_distance_pct_max: Optional[float] = Query(
        None, ge=0, description="Max nearest distance (%)"
    ),
    delta_base_pct_min: Optional[float] = Query(None, description="Min delta to base target (%)"),
    delta_base_pct_max: Optional[float] = Query(None, description="Max delta to base target (%)"),
    base_probability_pct_min: Optional[float] = Query(
        None, ge=0, le=100, description="Min base-case probability (%)"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    sort_by: str = Query("date", pattern="^(date|symbol)$"),
    include_proximity: bool = Query(False, description="Attach scenario proximity vs latest close"),
):
    settings = _get_settings()
    list_ttl = int(settings.cache_ttl_default or 120)

    ratings_norm = _norm_list(ratings, lower=True)
    confidences_norm = _norm_list(confidences, lower=True)
    sectors_norm = _norm_list(sectors, lower=False)
    scenarios_norm = _norm_list(nearest_scenarios, lower=True)
    has_advanced_filters = any(
        [
            ratings_norm,
            confidences_norm,
            sectors_norm,
            scenarios_norm,
            nearest_distance_pct_max is not None,
            delta_base_pct_min is not None,
            delta_base_pct_max is not None,
            base_probability_pct_min is not None,
        ]
    )

    if symbol and skip > 0:
        return AiAnalysisList(items=[], total_count=0, page=skip // limit + 1, page_size=limit)

    if symbol and not has_advanced_filters:
        cached_entry = ai_cache.get_latest(symbol, include_proximity=include_proximity)
        if cached_entry is None:
            cached_entry = ai_cache.warm_latest(
                symbol, include_proximity=include_proximity, session=db
            )
        if cached_entry is not None:
            item = AiAnalysisItem(**cached_entry)
            return AiAnalysisList(items=[item], total_count=1, page=1, page_size=limit)

    cache_key = make_key(
        "ai_latest",
        {
            "symbol": (symbol or "").upper(),
            "date_from": date_from or "",
            "date_to": date_to or "",
            "ratings": ",".join(sorted(ratings_norm)),
            "confidences": ",".join(sorted(confidences_norm)),
            "sectors": ",".join(sorted(sectors_norm)),
            "nearest_scenarios": ",".join(sorted(scenarios_norm)),
            "nearest_distance_pct_max": nearest_distance_pct_max
            if nearest_distance_pct_max is not None
            else "",
            "delta_base_pct_min": delta_base_pct_min if delta_base_pct_min is not None else "",
            "delta_base_pct_max": delta_base_pct_max if delta_base_pct_max is not None else "",
            "base_probability_pct_min": base_probability_pct_min
            if base_probability_pct_min is not None
            else "",
            "skip": skip,
            "limit": limit,
            "sort_order": sort_order,
            "sort_by": sort_by,
            "prox": include_proximity,
        },
    )
    cached = get_json(cache_key)
    if cached is not None:
        return cached
    df, dt = parse_iso_date_range(date_from, date_to)
    criteria = []
    if symbol:
        criteria.append(MvAiAnalysisLatestList.symbol == symbol.upper())
    if df:
        criteria.append(MvAiAnalysisLatestList.as_of_date >= df)
    if dt:
        criteria.append(MvAiAnalysisLatestList.as_of_date <= dt)

    if ratings_norm:
        criteria.append(func.lower(MvAiAnalysisLatestList.overall_rating).in_(ratings_norm))
    if confidences_norm:
        criteria.append(func.lower(MvAiAnalysisLatestList.confidence).in_(confidences_norm))
    if scenarios_norm:
        criteria.append(func.lower(MvAiAnalysisLatestList.nearest_scenario).in_(scenarios_norm))
    if nearest_distance_pct_max is not None:
        criteria.append(MvAiAnalysisLatestList.nearest_distance_pct <= nearest_distance_pct_max)
    if delta_base_pct_min is not None:
        criteria.append(MvAiAnalysisLatestList.delta_base_pct >= delta_base_pct_min)
    if delta_base_pct_max is not None:
        criteria.append(MvAiAnalysisLatestList.delta_base_pct <= delta_base_pct_max)
    if base_probability_pct_min is not None:
        criteria.append(MvAiAnalysisLatestList.base_probability_pct >= base_probability_pct_min)

    # Determine sort column
    if sort_by == "symbol":
        primary_order = (
            desc(MvAiAnalysisLatestList.symbol)
            if sort_order == "desc"
            else asc(MvAiAnalysisLatestList.symbol)
        )
    else:
        primary_order = (
            desc(MvAiAnalysisLatestList.as_of_date)
            if sort_order == "desc"
            else asc(MvAiAnalysisLatestList.as_of_date)
        )

    q = (
        select(MvAiAnalysisLatestList)
        .join(DimStock, DimStock.symbol == MvAiAnalysisLatestList.symbol)
        .where(
            *(criteria + [DimStock.is_active.is_(True)])
            + ([DimStock.sector.in_(sectors_norm)] if sectors_norm else [])
        )
        .order_by(primary_order)
        .offset(skip)
        .limit(limit)
    )
    total_count = (
        db.execute(
            select(func.count())
            .select_from(MvAiAnalysisLatestList)
            .join(DimStock, DimStock.symbol == MvAiAnalysisLatestList.symbol)
            .where(
                *(criteria + [DimStock.is_active.is_(True)])
                + ([DimStock.sector.in_(sectors_norm)] if sectors_norm else [])
            )
        ).scalar()
        or 0
    )

    rows = db.execute(q).scalars().all()
    dicts = [list_row_to_dict(r) for r in rows]

    items = [AiAnalysisItem(**d) for d in dicts]
    result = AiAnalysisList(
        items=items, total_count=total_count, page=skip // limit + 1, page_size=limit
    )
    set_json(cache_key, result.model_dump(), ttl_secs=list_ttl)
    return result


@router.get("/id/{analysis_id}", response_model=AiAnalysisItem)
def get_by_id(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    include_proximity: bool = Query(
        False, description="Attach scenario proximity vs latest close for this analysis"
    ),
):
    cached_entry = ai_cache.get_detail(analysis_id, include_proximity=include_proximity)
    if cached_entry is None:
        cached_entry = ai_cache.warm_detail(
            analysis_id, include_proximity=include_proximity, session=db
        )
    if cached_entry is None:
        raise HTTPException(status_code=404, detail="analysis_id not found")
    return AiAnalysisItem(**cached_entry)


class AiPreview(BaseModel):
    events_count: Optional[int] = None
    base_price_target: Optional[float] = None
    has_thesis: Optional[bool] = None


@router.get("/preview", response_model=Dict[str, AiPreview])
def get_ai_preview(symbols: List[str] = Query(...), db: Session = Depends(get_db)):
    """Batch preview for latest AI analysis per symbol.

    Returns a mapping of symbol → { events_count, base_price_target, has_thesis }.
    """
    settings = _get_settings()
    norm = [(s or "").strip().upper() for s in (symbols or []) if isinstance(s, str)]
    uniq = list(dict.fromkeys([s for s in norm if s]))  # stable de-dupe
    if not uniq:
        return {}
    max_symbols = int(settings.ai_preview_max_symbols or 200)
    if len(uniq) > max_symbols:
        raise HTTPException(status_code=400, detail=f"Too many symbols; max {max_symbols}")
    raw = preview_map_for_symbols(db, uniq)
    return {sym: AiPreview(**payload) for sym, payload in raw.items()}


@router.get("/{symbol}", response_model=AiAnalysisItem)
def get_latest_for_symbol(symbol: str, db: Session = Depends(get_db)):
    entry = ai_cache.get_latest(symbol, include_proximity=False)
    if entry is None:
        entry = ai_cache.warm_latest(symbol, include_proximity=False, session=db)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No AI analysis for {symbol}")
    return AiAnalysisItem(**entry)
