from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, aliased

from apps.api.src.cache import _get_client as _get_redis_client
from apps.api.src.cache import invalidate_prefix
from apps.api.src.database import get_db
from apps.api.src.security import require_admin_access
from apps.api.src.services.ai_analysis import AiAnalysisCache
from apps.api.src.services.prices import PriceHistoryCache
from apps.api.src.settings import Settings
from apps.api.src.utils.settings_cache import make_cached_getter
from apps.common.src.models import (
    DimNewsCluster,
    DimStock,
    FactNewsEvent,
    FactNewsImpact,
    FactNewsRaw,
    FactScoreHistory,
    MvAiAnalysisLatestList,
    SentimentAnalysisQueue,
)
from apps.common.src.news_utils.dedup import cluster_near_duplicates, simhash64
from apps.common.src.news_utils.entity_map import map_entities_to_symbols
from apps.common.src.news_utils.persist import create_cluster, insert_event, insert_impacts

# Reuse lightweight newswire logic for reprocessing
from apps.common.src.news_utils.prefilter import MaterialityPrefilter
from apps.common.src.news_utils.queue import enqueue_sentiment_analysis

_get_settings = make_cached_getter(lambda: Settings())


router = APIRouter(
    tags=["admin"],
    prefix="/api/v1/admin",
    dependencies=[Depends(require_admin_access)],
)
logger = logging.getLogger(__name__)

_STOCK_SYMBOL_MAX_LEN = 20


def _candidate_deleted_symbol(original_symbol: str, *, deleted_on: date, suffix: str = "") -> str:
    base = (original_symbol or "").strip().upper()
    stamp = deleted_on.strftime("%Y%m%d")
    end = f"-{stamp}{suffix}"
    max_base = max(_STOCK_SYMBOL_MAX_LEN - len(end), 0)
    base = base[:max_base] if max_base > 0 else ""
    return f"{base}{end}"


class AdminSoftDeleteStockRequest(BaseModel):
    symbol: Optional[str] = None
    stock_key: Optional[int] = None
    deleted_on: Optional[date] = None
    dry_run: bool = False


class AdminSoftDeleteStockResponse(BaseModel):
    ok: bool
    stock_key: int
    old_symbol: str
    new_symbol: str
    deleted_on: date
    was_active: bool


@router.post("/stocks/soft-delete", response_model=AdminSoftDeleteStockResponse)
def soft_delete_stock(payload: AdminSoftDeleteStockRequest, db: Session = Depends(get_db)):
    """Soft-delete a stock by deactivating it and renaming its ticker to free the symbol.

    This preserves historical joins by `stock_key` while allowing a new row to be created later
    using the original `symbol` (e.g., ticker reuse / corporate actions / symbol changes).
    """
    if payload.stock_key is None and not (payload.symbol or "").strip():
        raise HTTPException(status_code=422, detail="Provide symbol or stock_key")

    row: DimStock | None
    if payload.stock_key is not None:
        row = db.get(DimStock, int(payload.stock_key))
    else:
        sym = (payload.symbol or "").strip().upper()
        row = db.scalar(select(DimStock).where(DimStock.symbol == sym).limit(1))
    if row is None:
        raise HTTPException(status_code=404, detail="Stock not found")

    deleted_on = payload.deleted_on or date.today()
    old_symbol = str(row.symbol)
    was_active = bool(getattr(row, "is_active", True))

    # Find an unused deleted symbol; keep within DimStock.symbol length.
    candidate = _candidate_deleted_symbol(old_symbol, deleted_on=deleted_on)
    if candidate == old_symbol:
        candidate = _candidate_deleted_symbol(old_symbol, deleted_on=deleted_on, suffix="-1")
    for i in range(0, 100):
        suffix = "" if i == 0 else f"-{i}"
        candidate = _candidate_deleted_symbol(old_symbol, deleted_on=deleted_on, suffix=suffix)
        exists = db.scalar(
            select(DimStock.stock_key)
            .where(DimStock.symbol == candidate)
            .where(DimStock.stock_key != int(row.stock_key))
            .limit(1)
        )
        if exists is None:
            break
    else:
        raise HTTPException(status_code=409, detail="Unable to allocate unique deleted symbol")

    if payload.dry_run:
        return AdminSoftDeleteStockResponse(
            ok=True,
            stock_key=int(row.stock_key),
            old_symbol=old_symbol,
            new_symbol=candidate,
            deleted_on=deleted_on,
            was_active=was_active,
        )

    row.is_active = False
    row.symbol = candidate
    db.flush()
    return AdminSoftDeleteStockResponse(
        ok=True,
        stock_key=int(row.stock_key),
        old_symbol=old_symbol,
        new_symbol=str(row.symbol),
        deleted_on=deleted_on,
        was_active=was_active,
    )


class ActivityItem(BaseModel):
    symbol: str
    is_active: bool
    last_date: Optional[date]
    gap_bdays: Optional[int]
    status: Literal["fresh", "stale", "reactivate", "unknown"]
    suggested_action: Optional[Literal["inactivate", "reactivate"]] = None


class ActivityResponse(BaseModel):
    anchor_date: date
    anchor_source: Literal["reference", "modal", "max"]
    inactive_after_bdays: int
    reactivate_if_within_bdays: int
    reference_symbol: str
    anchor_min_share: float
    items: List[ActivityItem]


class AdminGradesRefreshResponse(BaseModel):
    ok: bool
    mv_universe_eligible_refreshed: Optional[bool] = None
    mv_latest_grades_refreshed: bool
    latest_date_key: Optional[int] = None
    invalidated: Optional[dict[str, int]] = None
    # OpenAPI example
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "mv_universe_eligible_refreshed": True,
                "mv_latest_grades_refreshed": True,
                "latest_date_key": 20251008,
                "invalidated": {
                    "grades": 124,
                    "grades_v2": 310,
                    "grade": 75,
                    "asset": 10,
                    "screener_changes": 14,
                    "screener_breadth": 7,
                    "httpcache": 120,
                },
            }
        }
    )


class AdminAiRefreshResponse(BaseModel):
    ok: bool
    mv_ai_scenario_proximity_refreshed: bool
    mv_ai_latest_list_refreshed: bool
    invalidated: Optional[dict[str, int]] = None
    # OpenAPI example
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "mv_ai_scenario_proximity_refreshed": True,
                "mv_ai_latest_list_refreshed": True,
                "invalidated": {"ai_list": 30, "ai_latest": 1, "ai_id": 5, "httpcache": 50},
            }
        }
    )


class PriceCacheRefreshRequest(BaseModel):
    symbols: list[str]
    reason: Optional[str] = None
    as_of: Optional[datetime] = None
    force: bool = False
    chunk_size: Optional[int] = Field(default=None, ge=1, le=1000)


class CachePurgeRequest(BaseModel):
    prefixes: list[str] = Field(
        default_factory=lambda: ["httpcache:"],
        description="Redis key prefixes to delete (SCAN match prefix*)",
    )


class CachePurgeResponse(BaseModel):
    ok: bool
    invalidated: dict[str, int]


@router.post("/cache/purge", response_model=CachePurgeResponse)
def purge_cache(payload: CachePurgeRequest):
    """Purge Redis key prefixes (best-effort).

    Intended for Airflow or operator use after pipeline completes to ensure the API's
    Redis HTTP cache is cleared immediately (not waiting for TTL expiry).
    """
    invalidated: dict[str, int] = {}
    for prefix in payload.prefixes or []:
        p = (prefix or "").strip()
        if not p:
            continue
        invalidated[p] = invalidate_prefix(p)
    return CachePurgeResponse(ok=True, invalidated=invalidated)


class PriceCacheRefreshResponse(BaseModel):
    ok: bool
    requested: int
    enqueued: int
    batches: int
    reason: Optional[str] = None
    as_of: Optional[datetime] = None


class NewswireRawItem(BaseModel):
    raw_id: UUID
    is_centroid: bool
    source_domain: Optional[str]
    title: Optional[str]
    snippet: Optional[str]
    published_at: Optional[datetime]
    first_seen_ts: Optional[datetime]
    url: Optional[str]
    body_fetch_status: Optional[str]
    body_fetch_ts: Optional[datetime]
    body_source: Optional[str]
    body_bytes: Optional[int]
    language: Optional[str]
    country: Optional[str]


class NewswireImpactItem(BaseModel):
    stock_key: int
    symbol: Optional[str]
    company_name: Optional[str]
    role: Optional[str]
    confidence: Optional[float]
    direction: Optional[str]
    magnitude_score: Optional[float]


class NewswireEventItem(BaseModel):
    event_id: UUID
    decided_at: datetime
    cluster_id: UUID
    cluster_first_seen: Optional[datetime]
    centroid_raw_id: Optional[UUID]
    materiality_score: float
    prefilter_score: float
    prefilter_reason: Optional[str]
    summary: Optional[str]
    llm_status: str
    llm_model: Optional[str]
    llm_ran_at: Optional[datetime]
    llm_error: Optional[str]
    sources: List[str]
    impacts: List[NewswireImpactItem]
    raw_items: List[NewswireRawItem]


class NewswireEventsResponse(BaseModel):
    items: List[NewswireEventItem]
    count: int


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _warm_price_cache_batch(
    symbols: list[str], *, force: bool, reason: Optional[str], as_of: Optional[str]
) -> None:
    cache = PriceHistoryCache()
    for sym in symbols:
        try:
            cache.warm(sym, force=force)
        except Exception as exc:
            logger.warning(
                "Price cache warm failed for %s (reason=%s, as_of=%s): %s", sym, reason, as_of, exc
            )


def _llm_status(event: FactNewsEvent) -> str:
    if event.llm_response:
        return "completed"
    if event.llm_error:
        return str(event.llm_error)
    if event.llm_prompt:
        return "pending"
    return "not_started"


@router.get("/newswire/events", response_model=NewswireEventsResponse)
def get_newswire_events(
    limit: int = 25,
    hours: Optional[int] = None,
    db: Session = Depends(get_db),
) -> NewswireEventsResponse:
    limit = max(1, min(limit, 100))
    since: Optional[datetime] = None
    if hours is not None and hours > 0:
        since = datetime.now(tz=timezone.utc) - timedelta(hours=abs(hours))

    centroid_raw = aliased(FactNewsRaw)
    query = (
        db.query(FactNewsEvent, DimNewsCluster, centroid_raw)
        .join(DimNewsCluster, DimNewsCluster.cluster_id == FactNewsEvent.cluster_id)
        .outerjoin(centroid_raw, centroid_raw.raw_id == DimNewsCluster.centroid_raw_id)
    )
    if since is not None:
        query = query.filter(FactNewsEvent.decided_at >= since)
    rows = query.order_by(FactNewsEvent.decided_at.desc()).limit(limit).all()

    if not rows:
        return NewswireEventsResponse(items=[], count=0)

    cluster_ids = [cl.cluster_id for _, cl, _ in rows if cl.cluster_id is not None]
    event_ids = [ev.event_id for ev, _, _ in rows]

    raw_by_cluster: dict[UUID, list[FactNewsRaw]] = defaultdict(list)
    if cluster_ids:
        raw_rows = (
            db.query(FactNewsRaw)
            .filter(FactNewsRaw.cluster_id.in_(cluster_ids))
            .order_by(FactNewsRaw.first_seen_ts.asc())
            .all()
        )
        for raw in raw_rows:
            if raw.cluster_id is not None:
                raw_by_cluster[raw.cluster_id].append(raw)

    impacts_by_event: dict[UUID, list[tuple[FactNewsImpact, DimStock]]] = defaultdict(list)
    if event_ids:
        impact_rows = (
            db.query(FactNewsImpact, DimStock)
            .join(DimStock, DimStock.stock_key == FactNewsImpact.stock_key)
            .filter(FactNewsImpact.event_id.in_(event_ids))
            .all()
        )
        for impact, stock in impact_rows:
            impacts_by_event[impact.event_id].append((impact, stock))

    items: list[NewswireEventItem] = []
    for event, cluster, centroid in rows:
        centroid_id = centroid.raw_id if centroid else cluster.centroid_raw_id
        raw_items: list[NewswireRawItem] = []
        for raw in raw_by_cluster.get(cluster.cluster_id, []):
            raw_items.append(
                NewswireRawItem(
                    raw_id=raw.raw_id,
                    is_centroid=bool(centroid_id and raw.raw_id == centroid_id),
                    source_domain=raw.source_domain,
                    title=raw.title,
                    snippet=raw.snippet,
                    published_at=raw.published_at,
                    first_seen_ts=raw.first_seen_ts,
                    url=raw.url_canonical,
                    body_fetch_status=raw.body_fetch_status,
                    body_fetch_ts=raw.body_fetch_ts,
                    body_source=raw.body_source,
                    body_bytes=raw.body_bytes,
                    language=raw.language,
                    country=raw.country,
                )
            )

        impacts: list[NewswireImpactItem] = []
        for impact, stock in impacts_by_event.get(event.event_id, []):
            impacts.append(
                NewswireImpactItem(
                    stock_key=int(impact.stock_key),
                    symbol=(stock.symbol or "").upper() if stock and stock.symbol else None,
                    company_name=stock.company_name if stock else None,
                    role=impact.role,
                    confidence=float(impact.confidence) if impact.confidence is not None else None,
                    direction=impact.direction,
                    magnitude_score=float(impact.magnitude_score)
                    if impact.magnitude_score is not None
                    else None,
                )
            )

        sources = sorted({ri.source_domain for ri in raw_items if ri.source_domain})
        materiality_score = float(event.materiality_score or 0.0)
        prefilter_score = materiality_score / 100.0
        items.append(
            NewswireEventItem(
                event_id=event.event_id,
                decided_at=event.decided_at,
                cluster_id=cluster.cluster_id,
                cluster_first_seen=cluster.first_seen_ts,
                centroid_raw_id=centroid_id,
                materiality_score=materiality_score,
                prefilter_score=prefilter_score,
                prefilter_reason=event.prefilter_reason,
                summary=event.summary,
                llm_status=_llm_status(event),
                llm_model=event.llm_model,
                llm_ran_at=event.llm_ran_at,
                llm_error=event.llm_error,
                sources=sources,
                impacts=impacts,
                raw_items=raw_items,
            )
        )

    return NewswireEventsResponse(items=items, count=len(items))


class AiCacheRefreshRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    analysis_ids: list[UUID] = Field(default_factory=list)
    include_proximity: bool = False
    reason: Optional[str] = None
    chunk_size: Optional[int] = Field(default=None, ge=1, le=1000)


class AiCacheRefreshResponse(BaseModel):
    ok: bool
    symbols: int
    analysis_ids: int
    batches: int
    include_proximity: bool
    reason: Optional[str] = None


def _warm_ai_cache_batch(
    symbols: list[str],
    analysis_ids: list[UUID | str],
    *,
    include_proximity: bool,
    reason: Optional[str],
) -> None:
    cache = AiAnalysisCache()
    if symbols:
        try:
            cache.invalidate_symbols(symbols)
        except Exception as exc:
            logger.debug("AI cache symbol invalidation failed (%s): %s", symbols, exc)
        for sym in symbols:
            try:
                cache.warm_latest(sym, include_proximity=False)
                if include_proximity:
                    cache.warm_latest(sym, include_proximity=True)
            except Exception as exc:
                logger.warning(
                    "AI cache warm failed for symbol %s (reason=%s): %s", sym, reason, exc
                )
    if analysis_ids:
        try:
            cache.invalidate_analyses(analysis_ids)
        except Exception as exc:
            logger.debug("AI cache analysis invalidation failed (%s): %s", analysis_ids, exc)
        for aid in analysis_ids:
            try:
                cache.warm_detail(aid, include_proximity=False)
                if include_proximity:
                    cache.warm_detail(aid, include_proximity=True)
            except Exception as exc:
                logger.warning(
                    "AI cache warm failed for analysis %s (reason=%s): %s", aid, reason, exc
                )


@router.post("/prices/cache-refresh", response_model=PriceCacheRefreshResponse)
def admin_prices_cache_refresh(
    request: PriceCacheRefreshRequest,
    background_tasks: BackgroundTasks,
) -> PriceCacheRefreshResponse:
    symbols = sorted({(s or "").upper() for s in request.symbols if (s or "").strip()})
    if not symbols:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No symbols provided")

    settings = _get_settings()
    default_chunk = int(getattr(settings, "price_history_cache_refresh_chunk_size", None) or 50)
    chunk_size = request.chunk_size or default_chunk
    chunk_size = max(1, min(int(chunk_size), 500))
    batches = _chunked(symbols, chunk_size)
    as_of_iso = request.as_of.isoformat() if request.as_of else None
    for chunk in batches:
        background_tasks.add_task(
            _warm_price_cache_batch,
            chunk,
            force=request.force,
            reason=request.reason,
            as_of=as_of_iso,
        )
    logger.info(
        "Price cache refresh queued: symbols=%d batches=%d chunk_size=%d reason=%s as_of=%s force=%s",
        len(symbols),
        len(batches),
        chunk_size,
        request.reason,
        as_of_iso,
        request.force,
    )
    return PriceCacheRefreshResponse(
        ok=True,
        requested=len(request.symbols),
        enqueued=sum(len(chunk) for chunk in batches),
        batches=len(batches),
        reason=request.reason,
        as_of=request.as_of,
    )


@router.post("/ai-analysis/cache-refresh", response_model=AiCacheRefreshResponse)
def admin_ai_analysis_cache_refresh(
    request: AiCacheRefreshRequest,
    background_tasks: BackgroundTasks,
) -> AiCacheRefreshResponse:
    symbols = sorted({(s or "").upper() for s in request.symbols if (s or "").strip()})
    analysis_ids = []
    for aid in request.analysis_ids:
        try:
            analysis_ids.append(UUID(str(aid)))
        except Exception:
            continue

    if not symbols and not analysis_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Provide symbols and/or analysis_ids"
        )

    settings = _get_settings()
    default_chunk = int(getattr(settings, "ai_analysis_cache_refresh_chunk_size", None) or 25)
    chunk_size = request.chunk_size or default_chunk
    chunk_size = max(1, min(int(chunk_size), 500))

    batches = 0
    for chunk in _chunked(symbols, chunk_size) if symbols else []:
        background_tasks.add_task(
            _warm_ai_cache_batch,
            chunk,
            [],
            include_proximity=request.include_proximity,
            reason=request.reason,
        )
        batches += 1
    for chunk in _chunked(analysis_ids, chunk_size) if analysis_ids else []:
        background_tasks.add_task(
            _warm_ai_cache_batch,
            [],
            chunk,
            include_proximity=request.include_proximity,
            reason=request.reason,
        )
        batches += 1

    logger.info(
        "AI cache refresh queued: symbols=%d analysis_ids=%d batches=%d include_proximity=%s reason=%s",
        len(symbols),
        len(analysis_ids),
        batches,
        request.include_proximity,
        request.reason,
    )
    return AiCacheRefreshResponse(
        ok=True,
        symbols=len(symbols),
        analysis_ids=len(analysis_ids),
        batches=batches,
        include_proximity=request.include_proximity,
        reason=request.reason,
    )


# -------------------- QUEUE MAINTENANCE -----------------------------


class QueueMaintenanceRequest(BaseModel):
    dry_run: bool = True
    include_event_specific: bool = False
    cleanup_done_days: int | None = 30
    cleanup_failed_days: int | None = 14


class QueueMaintenanceResponse(BaseModel):
    ok: bool
    dry_run: bool
    deleted_pending_duplicates: int = 0
    deleted_event_duplicates: int = 0
    deleted_done: int = 0
    deleted_failed: int = 0
    examined_pending: int | None = None
    examined_event: int | None = None


@router.post("/news/queue/maintain", response_model=QueueMaintenanceResponse)
def maintain_sentiment_queue(
    req: QueueMaintenanceRequest, db: Session = Depends(get_db)
) -> QueueMaintenanceResponse:
    """Clean up duplicate sentiment queue rows and optionally age out old done/failed rows.

    Policy:
    - Eventless rows (event_id IS NULL): keep the earliest run_after_date per stock_key across pending/in_progress; delete later pending rows.
    - Event-specific rows (event_id NOT NULL): optionally keep earliest run_after_ts per (stock_key,event_id) among pending; delete later pending rows.
    - Optionally, delete completed/failed rows older than configured days.
    """
    # Dry-run counts
    pending_dupes = 0
    event_dupes = 0
    deleted_pending = 0
    deleted_event = 0
    deleted_done = 0
    deleted_failed = 0

    # Count potential pending duplicates
    try:
        pending_sql = text(
            """
            WITH winners AS (
              SELECT stock_key, MIN(run_after_date) AS earliest
              FROM rankalpha.sentiment_analysis_queue
              WHERE event_id IS NULL AND status IN ('pending','in_progress')
              GROUP BY stock_key
            )
            SELECT COUNT(*)
            FROM rankalpha.sentiment_analysis_queue q
            JOIN winners w ON w.stock_key = q.stock_key
            WHERE q.event_id IS NULL
              AND q.status = 'pending'
              AND q.run_after_date > w.earliest
            """
        )
        pending_dupes = int(db.execute(pending_sql).scalar() or 0)
    except Exception:
        pending_dupes = 0

    if req.include_event_specific:
        try:
            event_sql = text(
                """
                WITH ranked AS (
                  SELECT queue_id,
                         ROW_NUMBER() OVER (PARTITION BY stock_key, event_id ORDER BY run_after_ts ASC, enqueue_ts ASC) AS rn
                  FROM rankalpha.sentiment_analysis_queue
                  WHERE event_id IS NOT NULL AND status = 'pending'
                )
                SELECT COUNT(*) FROM ranked WHERE rn > 1
                """
            )
            event_dupes = int(db.execute(event_sql).scalar() or 0)
        except Exception:
            event_dupes = 0

    if req.dry_run:
        return QueueMaintenanceResponse(
            ok=True,
            dry_run=True,
            deleted_pending_duplicates=0,
            deleted_event_duplicates=0,
            deleted_done=0,
            deleted_failed=0,
            examined_pending=pending_dupes,
            examined_event=event_dupes if req.include_event_specific else None,
        )

    # Apply deletions in a transaction
    try:
        del_pending_sql = text(
            """
            WITH winners AS (
              SELECT stock_key, MIN(run_after_date) AS earliest
              FROM rankalpha.sentiment_analysis_queue
              WHERE event_id IS NULL AND status IN ('pending','in_progress')
              GROUP BY stock_key
            ),
            to_delete AS (
              SELECT q.queue_id
              FROM rankalpha.sentiment_analysis_queue q
              JOIN winners w ON w.stock_key = q.stock_key
              WHERE q.event_id IS NULL
                AND q.status = 'pending'
                AND q.run_after_date > w.earliest
            )
            DELETE FROM rankalpha.sentiment_analysis_queue saq
            USING to_delete td
            WHERE saq.queue_id = td.queue_id
            RETURNING saq.queue_id
            """
        )
        deleted_pending = db.execute(del_pending_sql).rowcount or 0

        if req.include_event_specific:
            del_event_sql = text(
                """
                WITH ranked AS (
                  SELECT queue_id,
                         ROW_NUMBER() OVER (PARTITION BY stock_key, event_id ORDER BY run_after_ts ASC, enqueue_ts ASC) AS rn
                  FROM rankalpha.sentiment_analysis_queue
                  WHERE event_id IS NOT NULL AND status = 'pending'
                )
                DELETE FROM rankalpha.sentiment_analysis_queue q
                USING ranked r
                WHERE q.queue_id = r.queue_id AND r.rn > 1
                RETURNING q.queue_id
                """
            )
            deleted_event = db.execute(del_event_sql).rowcount or 0

        if isinstance(req.cleanup_done_days, int) and req.cleanup_done_days > 0:
            del_done_sql = text(
                "DELETE FROM rankalpha.sentiment_analysis_queue WHERE status='done' AND completed_ts IS NOT NULL AND completed_ts < now() - make_interval(days => :d)"
            )
            deleted_done = db.execute(del_done_sql, {"d": int(req.cleanup_done_days)}).rowcount or 0

        if isinstance(req.cleanup_failed_days, int) and req.cleanup_failed_days > 0:
            del_failed_sql = text(
                "DELETE FROM rankalpha.sentiment_analysis_queue WHERE status='failed' AND enqueue_ts < now() - make_interval(days => :d)"
            )
            deleted_failed = (
                db.execute(del_failed_sql, {"d": int(req.cleanup_failed_days)}).rowcount or 0
            )

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Queue maintenance failed")
        raise HTTPException(status_code=500, detail="Queue maintenance failed") from exc

    return QueueMaintenanceResponse(
        ok=True,
        dry_run=False,
        deleted_pending_duplicates=int(deleted_pending or 0),
        deleted_event_duplicates=int(deleted_event or 0),
        deleted_done=int(deleted_done or 0),
        deleted_failed=int(deleted_failed or 0),
        examined_pending=pending_dupes,
        examined_event=event_dupes if req.include_event_specific else None,
    )


# -------------------- BUDGET ADMIN OPS -----------------------------


class BudgetServiceSnapshot(BaseModel):
    service: str
    date_utc: str
    tokens_used_today: int
    cost_used_today: float
    rpm_last_minute: int
    notes: Optional[str] = None


class BudgetSnapshotResponse(BaseModel):
    ok: bool
    services: list[BudgetServiceSnapshot]


class BudgetResetRequest(BaseModel):
    services: Optional[list[str]] = None  # default: all known
    reset_tokens_today: bool = True
    reset_cost_today: bool = True
    reset_rpm: bool = True


def _today_str_utc() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d")


def _known_budget_services() -> list[str]:
    # Align with guards used in newswire/sentiment
    return [
        "newswire_search",
        "newswire_llm",
        "sentiment_llm",
    ]


def _to_float(v) -> float:
    try:
        return float(v if v is not None else 0.0)
    except Exception:
        return 0.0


def _to_int(v) -> int:
    try:
        return int(float(v if v is not None else 0.0))
    except Exception:
        return 0


@router.get("/budget", response_model=BudgetSnapshotResponse)
def get_budget_snapshot() -> BudgetSnapshotResponse:
    """Return a snapshot of token/cost usage for known services (Redis-backed only).

    If Redis is unavailable or services use process-local counters, values may be zero/absent.
    """
    try:
        r = _get_redis_client()
    except Exception:
        return BudgetSnapshotResponse(ok=False, services=[])
    today = _today_str_utc()
    out: list[BudgetServiceSnapshot] = []
    for svc in _known_budget_services():
        try:
            tkey = f"{svc}:tokens:{today}"
            ckey = f"{svc}:cost:{today}"
            rkey = f"{svc}:rpm"
            vals = r.mget([tkey, ckey, rkey])
            t_used = _to_int(vals[0])
            c_used = _to_float(vals[1])
            rpm = _to_int(vals[2])
            out.append(
                BudgetServiceSnapshot(
                    service=svc,
                    date_utc=today,
                    tokens_used_today=t_used,
                    cost_used_today=c_used,
                    rpm_last_minute=rpm,
                )
            )
        except Exception:
            out.append(
                BudgetServiceSnapshot(
                    service=svc,
                    date_utc=today,
                    tokens_used_today=0,
                    cost_used_today=0.0,
                    rpm_last_minute=0,
                    notes="unavailable",
                )
            )
    return BudgetSnapshotResponse(ok=True, services=out)


@router.post("/budget/reset", response_model=BudgetSnapshotResponse)
def reset_budget(req: BudgetResetRequest) -> BudgetSnapshotResponse:
    """Reset today’s token/cost counters and/or RPM for selected services (Redis-backed only)."""
    try:
        r = _get_redis_client()
    except Exception:
        return BudgetSnapshotResponse(ok=False, services=[])
    today = _today_str_utc()
    services = req.services or _known_budget_services()
    for svc in services:
        try:
            keys: list[str] = []
            if req.reset_tokens_today:
                keys.append(f"{svc}:tokens:{today}")
            if req.reset_cost_today:
                keys.append(f"{svc}:cost:{today}")
            if req.reset_rpm:
                keys.append(f"{svc}:rpm")
            if keys:
                r.delete(*keys)
        except Exception:
            continue
    # Return fresh snapshot after reset
    return get_budget_snapshot()


class ToggleFlagRequest(BaseModel):
    value: bool = True


@router.post("/weights/recompute")
def force_recompute_weights(req: ToggleFlagRequest, db: Session = Depends(get_db)):
    """Set the admin flag to force hybrid weight recompute on next scorer run.

    Security: this route is not exposed in the UI; protect it upstream via network or auth.
    """
    try:
        db.execute(
            text(
                """
                INSERT INTO rankalpha.admin_flag(flag_name, flag_value, updated_at)
                VALUES ('force_recompute_weights', :v, now())
                ON CONFLICT (flag_name)
                DO UPDATE SET flag_value = EXCLUDED.flag_value, updated_at = now()
                """
            ),
            {"v": bool(req.value)},
        )
        db.commit()
        return {"ok": True, "flag": "force_recompute_weights", "value": bool(req.value)}
    except Exception:
        db.rollback()
        logger.exception("Failed to update admin flag force_recompute_weights")
        return {"ok": False, "error": "internal_error"}


@router.post("/grades/refresh", response_model=AdminGradesRefreshResponse)
def refresh_grades_mv(db: Session = Depends(get_db)):
    """Refresh universe eligibility and `mv_latest_grades`, then invalidate grade caches.

    - Refreshes `mv_universe_eligible` (price/liquidity policy; ETFs included)
    - Refreshes `mv_latest_grades` (composite A–F)
    - Invalidates Redis caches used by grading endpoints and the HTTP cache middleware

    Admin-only convenience; the operator refresh exists at `POST /api/v1/grading/refresh` (GET is deprecated).
    """
    try:
        latest_date = db.execute(select(func.max(FactScoreHistory.date_key))).scalar()
    except Exception:
        latest_date = None

    # Invalidate caches so frontend/API read fresh data
    invalidated = {
        "grades": invalidate_prefix("grades:"),
        "grades_v2": invalidate_prefix("grades_v2:"),
        "grade": invalidate_prefix("grade:"),
        "asset": invalidate_prefix("asset:"),
        "screener_changes": invalidate_prefix("screener_changes:"),
        "screener_breadth": invalidate_prefix("screener_breadth:"),
        "httpcache": invalidate_prefix("httpcache:"),
    }
    # Refresh related MVs (universe first; then grades)
    uni_refreshed = False
    try:
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
            db.rollback()
            mv_refreshed = False
            return AdminGradesRefreshResponse(
                ok=False,
                mv_universe_eligible_refreshed=uni_refreshed,
                mv_latest_grades_refreshed=mv_refreshed,
                latest_date_key=int(latest_date or 0),
                invalidated=invalidated,
            )

    return AdminGradesRefreshResponse(
        ok=True,
        mv_universe_eligible_refreshed=uni_refreshed,
        mv_latest_grades_refreshed=mv_refreshed,
        latest_date_key=int(latest_date or 0),
        invalidated=invalidated,
    )


@router.post("/ai-analysis/refresh", response_model=AdminAiRefreshResponse)
def refresh_ai_analysis(db: Session = Depends(get_db)):
    """Refresh AI Analysis proximity MV and invalidate related caches.

    - Refreshes `rankalpha.mv_ai_scenario_proximity` (CONCURRENTLY if possible).
    - Invalidates Redis keys used by ai-analysis list/latest/detail endpoints.
    """
    # Invalidate API caches first so subsequent reads don't serve stale data
    invalidated = {
        "ai_list": invalidate_prefix("ai_list:"),
        "ai_latest": invalidate_prefix("ai_latest:"),
        "ai_id": invalidate_prefix("ai_id:"),
        "httpcache": invalidate_prefix("httpcache:"),
    }

    # Refresh MV (best effort)
    mv_prox_refreshed = False
    mv_list_refreshed = False
    try:
        db.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_ai_scenario_proximity")
        )
        db.commit()
        mv_prox_refreshed = True
    except Exception:
        try:
            db.execute(text("REFRESH MATERIALIZED VIEW rankalpha.mv_ai_scenario_proximity"))
            db.commit()
            mv_prox_refreshed = True
        except Exception:
            db.rollback()
            return AdminAiRefreshResponse(
                ok=False,
                mv_ai_scenario_proximity_refreshed=mv_prox_refreshed,
                mv_ai_latest_list_refreshed=mv_list_refreshed,
                invalidated=invalidated,
            )

    try:
        db.execute(
            text("REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_ai_analysis_latest_list")
        )
        db.commit()
        mv_list_refreshed = True
    except Exception:
        try:
            db.execute(text("REFRESH MATERIALIZED VIEW rankalpha.mv_ai_analysis_latest_list"))
            db.commit()
            mv_list_refreshed = True
        except Exception:
            db.rollback()
            return AdminAiRefreshResponse(
                ok=False,
                mv_ai_scenario_proximity_refreshed=mv_prox_refreshed,
                mv_ai_latest_list_refreshed=mv_list_refreshed,
                invalidated=invalidated,
            )

    return AdminAiRefreshResponse(
        ok=True,
        mv_ai_scenario_proximity_refreshed=mv_prox_refreshed,
        mv_ai_latest_list_refreshed=mv_list_refreshed,
        invalidated=invalidated,
    )


def _int_yyyymmdd_to_date(v: Optional[int]) -> Optional[date]:
    if v is None:
        return None
    try:
        year = v // 10000
        month = (v // 100) % 100
        day = v % 100
        return date(int(year), int(month), int(day))
    except Exception:
        return None


def _business_days_gap(a: Optional[date], b: Optional[date]) -> int:
    """Return business day count from a (exclusive) to b (inclusive), Mon–Fri.
    If a is None or a >= b, returns 0.
    """
    if a is None or b is None or a >= b:
        return 0
    start = a + timedelta(days=1)
    total_days = (b - start).days + 1
    if total_days <= 0:
        return 0
    full_weeks, rem = divmod(total_days, 7)
    count = full_weeks * 5
    # Count weekdays in the remainder
    for i in range(rem):
        if (start.weekday() + i) % 7 < 5:
            count += 1
    return count


@router.get("/activity", response_model=ActivityResponse)
def get_market_activity(db: Session = Depends(get_db)) -> ActivityResponse:
    # Use the common Settings to ensure we read the same ingestion
    # thresholds/env as the ingestion job (keeps admin UI consistent
    # with production behavior).
    settings = Settings()
    inact_bdays = int(settings.ingestion_inactive_after_missing_bdays or 5)
    react_bdays = int(settings.ingestion_reactivate_if_within_bdays or 1)
    ref_sym = (settings.ingestion_reference_symbol or "SPY").upper()
    min_share = float(settings.ingestion_anchor_min_share or 0.5)

    # Latest score date per stock as a proxy for last price date
    latest_sq = (
        select(
            FactScoreHistory.stock_key, func.max(FactScoreHistory.date_key).label("last_date_key")
        )
        .group_by(FactScoreHistory.stock_key)
        .subquery()
    )

    rows = db.execute(
        select(DimStock.symbol, DimStock.is_active, latest_sq.c.last_date_key)
        .select_from(DimStock)
        .join(latest_sq, latest_sq.c.stock_key == DimStock.stock_key, isouter=True)
    ).all()

    # Build mapping and anchor candidates
    last_map: dict[str, Optional[date]] = {}
    for sym, is_active, last_date_key in rows:
        last_map[str(sym).upper()] = _int_yyyymmdd_to_date(last_date_key)

    # Choose anchor date
    anchor_source: Literal["reference", "modal", "max"] = "max"
    anchor_date: Optional[date] = None
    if ref_sym in last_map and last_map[ref_sym] is not None:
        anchor_date = last_map[ref_sym]
        anchor_source = "reference"
    else:
        vals = [d for d in last_map.values() if d is not None]
        if vals:
            # modal date
            cnt = Counter(vals)
            top_date, top_count = cnt.most_common(1)[0]
            share = float(top_count) / float(sum(cnt.values()))
            if share >= min_share:
                anchor_date = top_date
                anchor_source = "modal"
            else:
                anchor_date = max(vals)
                anchor_source = "max"
    if anchor_date is None:
        # No data at all – default to today to avoid crash
        anchor_date = date.today()
        anchor_source = "max"

    # Compute statuses
    items: list[ActivityItem] = []
    for sym, is_active, last_date_key in rows:
        last_dt = _int_yyyymmdd_to_date(last_date_key)
        gap = _business_days_gap(last_dt, anchor_date)
        status: Literal["fresh", "stale", "reactivate", "unknown"]
        suggested: Optional[Literal["inactivate", "reactivate"]] = None

        if last_dt is None:
            status = "unknown"
        else:
            if gap >= inact_bdays:
                status = "stale"
                if is_active:
                    suggested = "inactivate"
            elif gap <= react_bdays and not is_active:
                status = "reactivate"
                suggested = "reactivate"
            else:
                status = "fresh"

        items.append(
            ActivityItem(
                symbol=sym,
                is_active=bool(is_active),
                last_date=last_dt,
                gap_bdays=int(gap) if last_dt is not None else None,
                status=status,
                suggested_action=suggested,
            )
        )

    # Sort by largest lag first
    items.sort(key=lambda x: (x.gap_bdays or -1), reverse=True)

    return ActivityResponse(
        anchor_date=anchor_date,
        anchor_source=anchor_source,
        inactive_after_bdays=inact_bdays,
        reactivate_if_within_bdays=react_bdays,
        reference_symbol=ref_sym,
        anchor_min_share=min_share,
        items=items,
    )


# -------------------- NEWSWIRE ADMIN OPS -----------------------------
@router.post("/news/reprocess")
def reprocess_news_window(
    db: Session = Depends(get_db),
    since: str | None = None,
    until: str | None = None,
    threshold: float = 0.70,
    max_hamming: int = 4,
):
    """Re-cluster raw news and re-score materiality for a time window.

    - since/until: ISO timestamps in UTC. If omitted, defaults to last 6 hours.
    - threshold: materiality decision threshold (0..1).
    - max_hamming: simhash proximity for clustering.
    """

    def _parse_ts(s: str | None, default):
        if not s:
            return default
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid timestamp; use ISO 8601")

    now = datetime.now(tz=timezone.utc)
    dt_until = _parse_ts(until, now)
    dt_since = _parse_ts(since, now - timedelta(hours=6))

    rows = (
        db.query(FactNewsRaw)
        .filter(
            func.coalesce(FactNewsRaw.published_at, FactNewsRaw.first_seen_ts).between(
                dt_since, dt_until
            )
        )
        .all()
    )
    if not rows:
        return {"ok": True, "raw_count": 0, "clusters_created": 0, "events_created": 0}

    raw_ids = [r.raw_id for r in rows]
    old_cluster_ids = {r.cluster_id for r in rows if r.cluster_id is not None}
    # Clear existing clustering/events in window
    db.query(FactNewsRaw).filter(FactNewsRaw.raw_id.in_(raw_ids)).update(
        {FactNewsRaw.cluster_id: None}, synchronize_session=False
    )
    if old_cluster_ids:
        db.execute(
            delete(DimNewsCluster).where(DimNewsCluster.cluster_id.in_(list(old_cluster_ids)))
        )
    db.flush()

    # Build docs for clustering
    docs = []
    for r in rows:
        title = r.title or ""
        snippet = r.snippet or ""
        text_fp = int(r.text_fingerprint or 0)
        if text_fp == 0:
            text_fp = simhash64(f"{title}\n{snippet}")
        docs.append(
            {
                "url": r.url_canonical,
                "title": title,
                "snippet": snippet,
                "source_domain": r.source_domain,
                "text_fp": text_fp,
                "raw_id": r.raw_id,
            }
        )

    clusters = cluster_near_duplicates(docs, max_hamming=max_hamming)
    pf = MaterialityPrefilter(model_path=None)

    clusters_created = 0
    events_created = 0
    for cl in clusters:
        centroid = cl[0]
        member_ids = [d["raw_id"] for d in cl]
        cluster_row = create_cluster(
            db,
            centroid_raw_id=centroid["raw_id"],
            simhash=int(centroid["text_fp"]),
            members_raw_ids=member_ids,
        )
        clusters_created += 1

        m = pf.score(
            title=str(centroid.get("title", "")),
            snippet=str(centroid.get("snippet", "")),
            source_domain=str(centroid.get("source_domain", "")),
        )
        if m.score >= threshold:
            ev = insert_event(
                db,
                cluster_id=cluster_row.cluster_id,
                score=float(m.score),
                summary=str(centroid.get("title", ""))[:500],
                model_version="prefilter_v1",
                is_high_confidence=(m.score >= 0.9),
            )
            impacts = map_entities_to_symbols(
                db, centroid.get("title", ""), centroid.get("snippet", "")
            )
            if impacts:
                insert_impacts(db, ev.event_id, impacts)
            events_created += 1

    # Persist reclustering work before refreshing the MV so changes are visible
    db.commit()

    # Refresh MV to expose new events. Use an AUTOCOMMIT connection for CONCURRENTLY.
    try:
        bind = db.get_bind()
        with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            try:
                conn.execute(
                    text("REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_latest_material_news")
                )
            except Exception:
                # Fallback to non-concurrent refresh. Ensure we are not in an aborted txn.
                conn.execute(text("REFRESH MATERIALIZED VIEW rankalpha.mv_latest_material_news"))
    except Exception as exc:
        # If refresh fails entirely, surface the error but keep reclustering committed
        logger.exception("Materialized view refresh failed for mv_latest_material_news")
        raise HTTPException(status_code=500, detail="MV refresh failed") from exc

    # Invalidate cache prefix used by news endpoints
    invalidated = {
        "news_latest": invalidate_prefix("news_latest:"),
        "news_symbol": invalidate_prefix("news_symbol:"),
        "httpcache": invalidate_prefix("httpcache:"),
    }

    return {
        "ok": True,
        "raw_count": len(rows),
        "clusters_created": clusters_created,
        "events_created": events_created,
        "window": {"since": dt_since.isoformat(), "until": dt_until.isoformat()},
        "invalidated": invalidated,
    }


@router.post("/news/recluster")
def recluster_hours(
    db: Session = Depends(get_db), hours: int = 24, threshold: float = 0.70, max_hamming: int = 4
):
    now = datetime.now(tz=timezone.utc)
    since = (now - timedelta(hours=abs(int(hours)))).isoformat()
    return reprocess_news_window(
        db=db, since=since, until=now.isoformat(), threshold=threshold, max_hamming=max_hamming
    )


@router.post("/news/analyze")
def analyze_news_recent(
    db: Session = Depends(get_db), hours: int = 12, limit: int = 50, min_score: float = 70.0
):
    """Enqueue impacted symbols from recent material events for sentiment analysis.

    This avoids tight coupling with the newswire LLM code and triggers the sentiment workers
    to run fresh analyses using the DB-backed queue.
    """
    from sqlalchemy import desc

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=abs(int(hours)))
    events = (
        db.query(FactNewsEvent)
        .join(DimNewsCluster, DimNewsCluster.cluster_id == FactNewsEvent.cluster_id)
        .join(FactNewsRaw, FactNewsRaw.raw_id == DimNewsCluster.centroid_raw_id)
        .filter(func.coalesce(FactNewsRaw.published_at, FactNewsRaw.first_seen_ts) >= cutoff)
        .filter(FactNewsEvent.materiality_score >= float(min_score))
        .order_by(desc(FactNewsEvent.decided_at))
        .limit(min(200, max(1, limit)))
        .all()
    )
    enq = 0
    for ev in events:
        raw = (
            db.query(FactNewsRaw)
            .join(DimNewsCluster, DimNewsCluster.centroid_raw_id == FactNewsRaw.raw_id)
            .filter(DimNewsCluster.cluster_id == ev.cluster_id)
            .one_or_none()
        )
        raw_id = str(raw.raw_id) if raw else None
        title_override = ev.summary or (raw.title if raw else None)
        url_override = raw.url_canonical if raw else None
        impacts = db.query(FactNewsImpact).filter(FactNewsImpact.event_id == ev.event_id).all()
        for imp in impacts:
            if enqueue_sentiment_analysis(
                db,
                int(imp.stock_key),
                event_id=str(ev.event_id),
                title=title_override,
                url=url_override,
                priority=int(ev.materiality_score or 0),
                source="api-admin",
                force_run=True,
                raw_id=raw_id,
            ):
                enq += 1
    db.commit()
    return {"ok": True, "events": len(events), "enqueued": enq}


# -------------------- SENTIMENT QUEUE ADMIN OPS -----------------------
@router.get("/news/queue")
def list_sentiment_queue(
    db: Session = Depends(get_db),
    status: str | None = None,
    symbol: str | None = None,
    search: str | None = None,
    limit: int = 100,
    sort_by: str | None = None,
    sort_order: str = "desc",
    include_last_analysis: bool = False,
):
    last_completed_entry = (
        db.query(SentimentAnalysisQueue)
        .filter(SentimentAnalysisQueue.completed_ts.isnot(None))
        .order_by(SentimentAnalysisQueue.completed_ts.desc())
        .first()
    )
    last_started_entry = (
        db.query(SentimentAnalysisQueue)
        .filter(SentimentAnalysisQueue.started_ts.isnot(None))
        .order_by(SentimentAnalysisQueue.started_ts.desc())
        .first()
    )

    last_completed_ts = last_completed_entry.completed_ts if last_completed_entry else None
    last_started_ts = last_started_entry.started_ts if last_started_entry else None

    # Prefer the most recent completed item; fall back to most recent started item
    last_processed_entry = None
    if last_completed_ts and (not last_started_ts or last_completed_ts >= last_started_ts):
        last_processed_entry = last_completed_entry
    elif last_started_entry:
        last_processed_entry = last_started_entry

    last_processed_ts = (
        last_processed_entry.completed_ts
        if (last_processed_entry and last_processed_entry.completed_ts)
        else (last_processed_entry.started_ts if last_processed_entry else None)
    )
    last_processed_symbol = last_processed_entry.symbol if last_processed_entry else None

    query = db.query(SentimentAnalysisQueue)
    if status:
        query = query.filter(SentimentAnalysisQueue.status == status)
    if symbol:
        query = query.filter(SentimentAnalysisQueue.symbol == symbol.upper())
    elif search:
        query = query.filter(func.upper(SentimentAnalysisQueue.symbol).like(f"%{search.upper()}%"))
    total = query.count()
    pending_now = None
    pending_future = None
    if status == "pending":
        now = datetime.now(tz=timezone.utc)
        pending_now = query.filter(
            (SentimentAnalysisQueue.run_after_ts.is_(None))
            | (SentimentAnalysisQueue.run_after_ts <= now)
        ).count()
        pending_future = query.filter(
            SentimentAnalysisQueue.run_after_ts.isnot(None),
            SentimentAnalysisQueue.run_after_ts > now,
        ).count()
    sort_key = (sort_by or "enqueue_ts").strip().lower()
    sort_dir = "asc" if sort_order and sort_order.lower() == "asc" else "desc"
    needs_analysis_join = include_last_analysis or sort_key == "last_analysis_date"

    last_analysis_date_col = None
    last_analysis_id_col = None
    row_query = query
    if needs_analysis_join:
        last_analysis_date_col = MvAiAnalysisLatestList.as_of_date.label("last_analysis_date")
        last_analysis_id_col = MvAiAnalysisLatestList.analysis_id.label("last_analysis_id")
        row_query = row_query.outerjoin(
            MvAiAnalysisLatestList,
            MvAiAnalysisLatestList.symbol == SentimentAnalysisQueue.symbol,
        ).add_columns(last_analysis_date_col, last_analysis_id_col)

    sort_columns = {
        "enqueue_ts": SentimentAnalysisQueue.enqueue_ts,
        "run_after_ts": SentimentAnalysisQueue.run_after_ts,
        "priority": SentimentAnalysisQueue.priority,
        "status": SentimentAnalysisQueue.status,
        "started_ts": SentimentAnalysisQueue.started_ts,
        "completed_ts": SentimentAnalysisQueue.completed_ts,
        "symbol": SentimentAnalysisQueue.symbol,
        "last_analysis_date": last_analysis_date_col,
    }
    sort_col = sort_columns.get(sort_key) or SentimentAnalysisQueue.enqueue_ts
    if sort_dir == "asc":
        order_expr = sort_col.asc()
    else:
        order_expr = sort_col.desc()
    if sort_key == "last_analysis_date":
        order_expr = order_expr.nullslast()

    rows = (
        row_query.order_by(order_expr, SentimentAnalysisQueue.enqueue_ts.desc())
        .limit(min(1000, max(1, limit)))
        .all()
    )
    out = []
    for row in rows:
        if needs_analysis_join:
            r = row[0]
            last_analysis_date = row[1]
            last_analysis_id = row[2]
        else:
            r = row
            last_analysis_date = None
            last_analysis_id = None
        out.append(
            {
                "queue_id": str(r.queue_id),
                "symbol": r.symbol,
                "stock_key": int(r.stock_key),
                "status": r.status,
                "priority": int(r.priority or 0),
                "enqueue_ts": r.enqueue_ts,
                "run_after_ts": r.run_after_ts,
                "started_ts": r.started_ts,
                "completed_ts": r.completed_ts,
                "attempts": int(r.attempts or 0),
                "event_id": str(r.event_id) if r.event_id else None,
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "force_run": bool(r.force_run),
                "raw_id": str(r.raw_id) if r.raw_id else None,
                "last_analysis_date": last_analysis_date,
                "last_analysis_id": str(last_analysis_id) if last_analysis_id else None,
            }
        )
    result = {
        "ok": True,
        "total": total,
        "items": out,
        "last_completed_ts": last_completed_ts,
        "last_started_ts": last_started_ts,
        "last_processed_ts": last_processed_ts,
        "last_processed_symbol": last_processed_symbol,
    }
    if pending_now is not None:
        result["pending_ready"] = pending_now
    if pending_future is not None:
        result["pending_future"] = pending_future
    return result


@router.post("/news/queue/enqueue")
def enqueue_sentiment(
    symbol: str,
    db: Session = Depends(get_db),
    event_id: str | None = None,
    title: str | None = None,
    url: str | None = None,
    priority: int = 70,
    force: bool = True,
    raw_id: str | None = None,
):
    sym = symbol.upper()
    r = db.query(DimStock).filter(DimStock.symbol == sym).one_or_none()
    if not r:
        raise HTTPException(status_code=400, detail="Unknown symbol")
    ok = enqueue_sentiment_analysis(
        db,
        int(r.stock_key),
        event_id=event_id,
        symbol=sym,
        title=title,
        url=url,
        priority=int(priority),
        source="admin",
        force_run=bool(force),
        raw_id=raw_id,
    )
    db.commit()
    return {"ok": bool(ok)}


@router.post("/news/queue/retry")
def retry_queue(
    db: Session = Depends(get_db),
    queue_id: str | None = None,
    all_failed: bool = False,
    limit: int = 100,
):
    if queue_id:
        n = db.execute(
            text(
                "UPDATE rankalpha.sentiment_analysis_queue SET status='pending', run_after_ts=now() WHERE queue_id = :qid"
            ),
            {"qid": queue_id},
        ).rowcount
        db.commit()
        return {"ok": True, "retried": int(n)}
    if all_failed:
        lim = min(1000, max(1, limit))
        sql = text(
            """
            WITH cte AS (
              SELECT queue_id
              FROM rankalpha.sentiment_analysis_queue
              WHERE status = 'failed'
              ORDER BY enqueue_ts DESC
              LIMIT :lim
            )
            UPDATE rankalpha.sentiment_analysis_queue saq
            SET status = 'pending', run_after_ts = now()
            FROM cte
            WHERE saq.queue_id = cte.queue_id
            """
        )
        n = db.execute(sql, {"lim": lim}).rowcount
        db.commit()
        return {"ok": True, "retried": int(n)}
    raise HTTPException(status_code=400, detail="Provide queue_id or set all_failed=true")


@router.post("/news/queue/clear")
def clear_queue(
    db: Session = Depends(get_db),
    status: str = "done",
    older_than_hours: int = 48,
    event_id: str | None = None,
):
    if status not in {"done", "failed", "pending", "in_progress", "all"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    if event_id:
        n = db.execute(
            text("DELETE FROM rankalpha.sentiment_analysis_queue WHERE event_id = :eid"),
            {"eid": event_id},
        ).rowcount
        db.commit()
        return {"ok": True, "deleted": int(n)}
    cond = ""
    if status != "all":
        cond += " status = :st AND"
    sql = f"DELETE FROM rankalpha.sentiment_analysis_queue WHERE{cond} enqueue_ts < now() - make_interval(hours => :hrs)"
    params = (
        {"st": status, "hrs": int(older_than_hours)}
        if status != "all"
        else {"hrs": int(older_than_hours)}
    )
    n = db.execute(text(sql), params).rowcount
    db.commit()
    return {"ok": True, "deleted": int(n)}
