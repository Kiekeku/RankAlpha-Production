from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    MvLatestMaterialNews,
    VwNewsBySymbol,
)

from ..cache import get_json, make_key, set_json
from ..database import get_db
from ..settings import Settings
from ..utils.company import CompanyNameSanitizerMixin
from ..utils.settings_cache import make_cached_getter

router = APIRouter(tags=["news"], prefix="/api/v1/news")
_get_settings = make_cached_getter(lambda: Settings())


class NewsItem(CompanyNameSanitizerMixin, BaseModel):
    event_id: str
    decided_at: Optional[datetime] = None
    first_seen_ts: Optional[datetime] = None
    materiality_score: Optional[float] = Field(None, description="0..100 scale")
    event_type: Optional[str] = None
    direction: Optional[str] = None
    timescale: Optional[str] = None
    summary: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    source_domain: Optional[str] = None
    symbol: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[str] = None
    confidence: Optional[float] = None


class NewsList(BaseModel):
    items: List[NewsItem]
    total_count: int
    page: int
    page_size: int


@router.get("/latest", response_model=NewsList)
def get_latest_news(
    db: Session = Depends(get_db),
    min_score: float = Query(70.0, ge=0, le=100, description="Minimum materiality score (0..100)"),
    symbol: Optional[str] = Query(None, description="Filter to a specific symbol"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    settings = _get_settings()
    ttl = int(settings.cache_ttl_default or 120)
    key = make_key(
        "news_latest",
        {"min_score": min_score, "symbol": (symbol or "").upper(), "skip": skip, "limit": limit},
    )
    cached = get_json(key)
    if cached is not None:
        return cached

    criteria = [MvLatestMaterialNews.materiality_score >= min_score]
    if symbol:
        criteria.append(MvLatestMaterialNews.symbol == symbol.upper())

    total = (
        db.execute(select(func.count()).select_from(MvLatestMaterialNews).where(*criteria)).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(MvLatestMaterialNews)
            .where(*criteria)
            .order_by(desc(MvLatestMaterialNews.decided_at))
            .offset(skip)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = [
        NewsItem(
            event_id=str(r.event_id),
            decided_at=r.decided_at,
            first_seen_ts=r.first_seen_ts,
            materiality_score=float(r.materiality_score)
            if r.materiality_score is not None
            else None,
            event_type=r.event_type,
            direction=r.direction,
            timescale=r.timescale,
            summary=r.summary,
            title=r.title,
            url=r.url,
            source_domain=r.source_domain,
            symbol=r.symbol,
            company_name=r.company_name,
            role=r.role,
            confidence=float(r.confidence) if r.confidence is not None else None,
        )
        for r in rows
    ]
    result = NewsList(items=items, total_count=total, page=skip // limit + 1, page_size=limit)
    set_json(key, result.model_dump(), ttl_secs=ttl)
    return result


@router.get("/symbol/{symbol}", response_model=NewsList)
def get_news_by_symbol(
    symbol: str,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    settings = _get_settings()
    ttl = int(settings.cache_ttl_default or 120)
    symu = symbol.upper()
    key = make_key("news_symbol", {"symbol": symu, "skip": skip, "limit": limit})
    cached = get_json(key)
    if cached is not None:
        return cached

    total = (
        db.execute(
            select(func.count()).select_from(VwNewsBySymbol).where(VwNewsBySymbol.symbol == symu)
        ).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(VwNewsBySymbol)
            .where(VwNewsBySymbol.symbol == symu)
            .order_by(desc(VwNewsBySymbol.decided_at))
            .offset(skip)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = [
        NewsItem(
            event_id=str(r.event_id),
            decided_at=r.decided_at,
            first_seen_ts=r.first_seen_ts,
            materiality_score=float(r.materiality_score)
            if r.materiality_score is not None
            else None,
            event_type=r.event_type,
            direction=r.direction,
            timescale=r.timescale,
            summary=r.summary,
            title=r.title,
            url=r.url,
            source_domain=r.source_domain,
            symbol=r.symbol,
            company_name=r.company_name,
            role=r.role,
            confidence=float(r.confidence) if r.confidence is not None else None,
        )
        for r in rows
    ]
    result = NewsList(items=items, total_count=total, page=skip // limit + 1, page_size=limit)
    set_json(key, result.model_dump(), ttl_secs=ttl)
    return result
