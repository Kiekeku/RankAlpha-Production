from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from apps.common.src.logging import setup_logging
from apps.common.src.models import (
    DimNewsCluster,
    FactNewsEvent,
    FactNewsImpact,
    FactNewsRaw,
    NewsIngestQueue,
    NewsSuggestion,
)
from apps.common.src.news_utils.dedup import cluster_near_duplicates, simhash64
from apps.common.src.news_utils.entity_map import map_entities_to_symbols
from apps.common.src.news_utils.persist import (
    create_cluster,
    insert_event,
    insert_impacts,
    upsert_raw,
)
from apps.common.src.news_utils.prefilter import MaterialityPrefilter
from apps.common.src.news_utils.queue import enqueue_sentiment_analysis

from .body_store import store_body_if_needed
from .db import session_factory
from .llm import analyze_event_cluster
from .schedule import enqueue_analysis_for_stock
from .settings import NewswireSettings

logger = logging.getLogger("newswire.queue_worker")
_LLM_QUEUE_WINDOW_LOCK = threading.Lock()
_LLM_QUEUE_WINDOW_STARTED = 0.0
_LLM_QUEUE_WINDOW_COUNT = 0


def _ensure_logger_configured() -> None:
    level_name = os.environ.get("NEWS_LOG_LEVEL") or os.environ.get("LOG_LEVEL") or "INFO"
    setup_logging(level_name)


def _hostname_worker_id() -> str:
    host = socket.gethostname()
    pid = os.getpid()
    suffix = os.environ.get("NEWS_QUEUE_WORKER_ID")
    if suffix:
        return suffix
    return f"{host}:{pid}"


def _tz_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _source_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return (netloc or "").lower()
    except Exception:
        return ""


def _claim_next_job(db: Session, worker_id: str) -> Optional[NewsIngestQueue]:
    now = datetime.now(timezone.utc)
    # Safety net: allow reclaiming jobs that have been stuck in_progress for too long (e.g., worker crash).
    try:
        stale_lock_sec = int(os.environ.get("NEWS_QUEUE_WORKER_STALE_LOCK_SEC", "0"))
    except Exception:
        stale_lock_sec = 0
    stale_cutoff = now - timedelta(seconds=max(60, stale_lock_sec)) if stale_lock_sec > 0 else None

    pending_filter = and_(
        NewsIngestQueue.status == "pending",
        NewsIngestQueue.run_after_ts <= now,
    )
    reclaim_filter = None
    if stale_cutoff is not None:
        # Only reclaim entries that were explicitly locked by a worker and have exceeded the lease duration.
        # Avoid treating NULL locked_ts as reclaimable (prevents immediate "steal" of externally-marked rows).
        reclaim_filter = and_(
            NewsIngestQueue.status == "in_progress",
            NewsIngestQueue.locked_by.is_not(None),
            NewsIngestQueue.locked_ts.is_not(None),
            NewsIngestQueue.locked_ts <= stale_cutoff,
        )

    if reclaim_filter is not None:
        where_filter = or_(pending_filter, reclaim_filter)
    else:
        where_filter = pending_filter
    stmt = (
        select(NewsIngestQueue)
        .options(selectinload(NewsIngestQueue.suggestion))
        .where(where_filter)
        .order_by(NewsIngestQueue.priority.desc(), NewsIngestQueue.enqueue_ts.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    entry = db.execute(stmt).scalars().first()
    if entry is None:
        return None

    entry.status = "in_progress"
    entry.locked_by = worker_id
    entry.locked_ts = now
    entry.started_ts = now
    entry.attempts = int(entry.attempts or 0) + 1
    suggestion = entry.suggestion
    if suggestion is not None:
        suggestion.status = "in_progress"
        suggestion.updated_at = now
    db.flush()
    return entry


def _store_body_from_suggestion(raw_row: FactNewsRaw, suggestion: NewsSuggestion) -> None:
    body = (suggestion.body_text or "").strip()
    if not body:
        return
    max_chars = int(os.environ.get("NEWS_BODY_MAX_CHARS", "120000"))
    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars]
        truncated = True
    body_bytes = len(body.encode("utf-8", errors="ignore"))
    try:
        body_fp = int(simhash64(body))
    except Exception:
        body_fp = None

    raw_row.body_text = body
    raw_row.body_bytes = body_bytes
    raw_row.body_fingerprint = body_fp
    raw_row.body_truncated = truncated
    raw_row.body_fetch_status = "provided"
    raw_row.body_fetch_error = None
    raw_row.body_fetch_ts = datetime.now(timezone.utc)
    raw_row.body_source = "suggestion"


def _duplicate_event_exists(
    db: Session,
    url_canonical: str,
    text_fp: Optional[int],
    window_hours: int,
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    filters = [or_(FactNewsEvent.decided_at >= cutoff, FactNewsRaw.published_at >= cutoff)]
    url_filter = FactNewsRaw.url_canonical == url_canonical
    if text_fp and text_fp > 0:
        fp_filter = FactNewsRaw.text_fingerprint == int(text_fp)
        combined = or_(url_filter, fp_filter)
    else:
        combined = url_filter
    exists = (
        db.query(FactNewsEvent.event_id)
        .join(DimNewsCluster, FactNewsEvent.cluster_id == DimNewsCluster.cluster_id)
        .join(FactNewsRaw, DimNewsCluster.centroid_raw_id == FactNewsRaw.raw_id)
        .filter(*filters)
        .filter(combined)
        .first()
    )
    return exists is not None


def _consume_llm_queue_budget() -> bool:
    global _LLM_QUEUE_WINDOW_STARTED, _LLM_QUEUE_WINDOW_COUNT
    try:
        cap = int(os.environ.get("NEWS_LLM_QUEUE_MAX_EVENTS", "10"))
    except Exception:
        cap = 10
    if cap <= 0:
        return False
    try:
        window_sec = int(os.environ.get("NEWS_LLM_QUEUE_WINDOW_SEC", "300"))
    except Exception:
        window_sec = 300
    window_sec = max(30, window_sec)
    now = time.monotonic()
    with _LLM_QUEUE_WINDOW_LOCK:
        if _LLM_QUEUE_WINDOW_STARTED <= 0 or (now - _LLM_QUEUE_WINDOW_STARTED) >= window_sec:
            _LLM_QUEUE_WINDOW_STARTED = now
            _LLM_QUEUE_WINDOW_COUNT = 0
        if _LLM_QUEUE_WINDOW_COUNT >= cap:
            return False
        _LLM_QUEUE_WINDOW_COUNT += 1
        return True


def _maybe_run_llm(db: Session, event_id, settings: NewswireSettings) -> None:
    try:
        llm_enabled = os.environ.get("NEWS_LLM_ENABLED", "true").lower() == "true"
        if not llm_enabled:
            return
        if os.environ.get("NEWS_LLM_AUTO", "false").lower() != "true":
            return
        ev = db.get(FactNewsEvent, event_id)
        if not ev:
            return
        min_score = float(os.environ.get("NEWS_LLM_MIN_SCORE", "0.50"))
        score = float(ev.materiality_score or 0) / 100.0
        if score < min_score:
            return
        if not _consume_llm_queue_budget():
            logger.info(
                "Skipping LLM analysis for event %s due to queue budget cap (NEWS_LLM_QUEUE_MAX_EVENTS)",
                event_id,
            )
            return
        analyze_event_cluster(db, event_id)
    except Exception:
        logger.exception("LLM analysis failed for event %s", event_id)


def _maybe_enqueue_sentiment(
    db: Session,
    event_id,
    settings: NewswireSettings,
) -> None:
    try:
        if os.environ.get("NEWS_SENTIMENT_ENQUEUE_ENABLED", "true").lower() != "true":
            return
        use_db_queue = os.environ.get("NEWS_SENTIMENT_QUEUE_ENABLED", "true").lower() == "true"
        enqueue_event_thr = float(os.environ.get("NEWS_SENTIMENT_ENQUEUE_MIN_EVENT_SCORE", "0.85"))
        enqueue_imp_thr = float(os.environ.get("NEWS_SENTIMENT_ENQUEUE_MIN_IMPACT_MAG", "70"))
        ev = db.get(FactNewsEvent, event_id)
        if not ev:
            return
        score = float(ev.materiality_score or 0) / 100.0
        if score < enqueue_event_thr:
            return
        title_for_event = None
        url_for_event = None
        raw_id_for_event = None
        try:
            cluster = db.get(DimNewsCluster, ev.cluster_id) if ev.cluster_id else None
            raw = (
                db.get(FactNewsRaw, cluster.centroid_raw_id)
                if cluster and cluster.centroid_raw_id
                else None
            )
            if raw:
                title_for_event = raw.title or ""
                url_for_event = raw.url_canonical or None
                raw_id_for_event = str(raw.raw_id)
        except Exception:
            title_for_event = None
            url_for_event = None
        impacts = db.query(FactNewsImpact).filter(FactNewsImpact.event_id == ev.event_id).all()
        any_enqueued = False
        for imp in impacts:
            mag = float(imp.magnitude_score or 0)
            if mag >= enqueue_imp_thr:
                ok = False
                if use_db_queue:
                    ok = enqueue_sentiment_analysis(
                        db,
                        int(imp.stock_key),
                        event_id=str(ev.event_id),
                        title=ev.summary or (title_for_event or ""),
                        url=url_for_event,
                        priority=int(round(float(ev.materiality_score or 0))),
                        source="newswire",
                        force_run=True,
                        raw_id=raw_id_for_event,
                    )
                else:
                    ok = enqueue_analysis_for_stock(db, int(imp.stock_key))
                if ok:
                    any_enqueued = True
        if not any_enqueued and impacts:
            for imp in impacts:
                ok = False
                if use_db_queue:
                    ok = enqueue_sentiment_analysis(
                        db,
                        int(imp.stock_key),
                        event_id=str(ev.event_id),
                        title=ev.summary or (title_for_event or ""),
                        url=url_for_event,
                        priority=int(round(float(ev.materiality_score or 0))),
                        source="newswire",
                        force_run=True,
                        raw_id=raw_id_for_event,
                    )
                else:
                    ok = enqueue_analysis_for_stock(db, int(imp.stock_key))
                if ok:
                    break
    except Exception:
        logger.exception("Sentiment enqueue failed for event %s", event_id)


def _process_suggestion(
    db: Session,
    entry: NewsIngestQueue,
    suggestion: NewsSuggestion,
    settings: NewswireSettings,
    prefilter: MaterialityPrefilter,
) -> Optional[str]:
    now = datetime.now(timezone.utc)
    doc = {
        "url": suggestion.url,
        "title": suggestion.title or "",
        "snippet": suggestion.snippet or "",
        "published_at": suggestion.published_at,
        "source_domain": _source_domain(suggestion.url),
        "language": suggestion.language,
        "country": suggestion.country,
        "raw": suggestion.raw_payload or {},
        "text_fp": suggestion.text_fingerprint,
    }

    docs = upsert_raw(db, [doc])
    doc = docs[0]
    raw_id = doc.get("raw_id")
    suggestion.url_canonical = doc.get("url_canonical") or suggestion.url
    suggestion.text_fingerprint = doc.get("text_fp") or suggestion.text_fingerprint
    raw_row = db.get(FactNewsRaw, raw_id) if raw_id else None

    if raw_row is None:
        raise RuntimeError("Failed to locate fact_news_raw row for suggestion")

    suggestion.cluster_id = raw_row.cluster_id

    if suggestion.body_text and not raw_row.body_text:
        _store_body_from_suggestion(raw_row, suggestion)

    if raw_row.cluster_id:
        existing_event = (
            db.query(FactNewsEvent)
            .filter(FactNewsEvent.cluster_id == raw_row.cluster_id)
            .order_by(FactNewsEvent.decided_at.desc())
            .first()
        )
        if existing_event:
            suggestion.event_id = existing_event.event_id
            suggestion.status = "merged"
            suggestion.status_reason = "existing_event"
            suggestion.processed_at = now
            suggestion.updated_at = now
            entry.status = "done"
            entry.completed_ts = now
            entry.last_error = None
            entry.locked_by = None
            entry.locked_ts = None
            return str(existing_event.event_id)

    clusters = cluster_near_duplicates([doc])
    if not clusters:
        raise RuntimeError("Unable to cluster suggestion document")
    cluster_docs = clusters[0]
    centroid = cluster_docs[0]
    member_ids = [d.get("raw_id") for d in cluster_docs if d.get("raw_id")]
    simhash = int(centroid.get("text_fp") or 0)
    cluster_row = create_cluster(
        db, centroid_raw_id=centroid["raw_id"], simhash=simhash, members_raw_ids=member_ids
    )
    suggestion.cluster_id = cluster_row.cluster_id
    suggestion.text_fingerprint = centroid.get("text_fp") or suggestion.text_fingerprint
    suggestion.url_canonical = centroid.get("url_canonical") or suggestion.url_canonical
    db.flush()

    m = prefilter.score(
        title=str(centroid.get("title", "")),
        snippet=str(centroid.get("snippet", "")),
        source_domain=str(centroid.get("source_domain", "")),
    )

    try:
        store_body_if_needed(
            db,
            raw_id=centroid.get("raw_id"),
            url=str(centroid.get("url_canonical") or centroid.get("url") or ""),
            prefilter_score=float(m.score or 0.0),
        )
    except Exception:
        logger.debug("store_body_if_needed errored; continuing", exc_info=True)

    if m.score < settings.materiality_threshold:
        suggestion.status = "rejected"
        suggestion.status_reason = f"materiality={m.score:.2f} reason={m.reason}"
        suggestion.processed_at = now
        suggestion.updated_at = now
        entry.status = "done"
        entry.completed_ts = now
        entry.last_error = None
        entry.locked_by = None
        entry.locked_ts = None
        return None

    dup_window = int(os.environ.get("NEWS_EVENT_DUP_WINDOW_HOURS", "72"))
    if _duplicate_event_exists(
        db,
        url_canonical=str(centroid.get("url_canonical") or centroid.get("url") or ""),
        text_fp=centroid.get("text_fp"),
        window_hours=dup_window,
    ):
        suggestion.status = "merged"
        suggestion.status_reason = "duplicate_guard"
        suggestion.processed_at = now
        suggestion.updated_at = now
        entry.status = "done"
        entry.completed_ts = now
        entry.last_error = None
        entry.locked_by = None
        entry.locked_ts = None
        return None

    ev = insert_event(
        db,
        cluster_id=cluster_row.cluster_id,
        score=m.score,
        summary=str(centroid.get("title", ""))[:500],
        event_type=None,
        direction=None,
        timescale=None,
        is_high_confidence=(m.score >= 0.9),
        prefilter_reason=m.reason,
    )
    impacts = map_entities_to_symbols(db, centroid.get("title", ""), centroid.get("snippet", ""))
    if impacts:
        insert_impacts(db, ev.event_id, impacts)
    db.flush()

    suggestion.event_id = ev.event_id
    suggestion.status = "accepted"
    suggestion.status_reason = f"materiality={m.score:.2f}"
    suggestion.processed_at = now
    suggestion.updated_at = now

    entry.status = "done"
    entry.completed_ts = now
    entry.last_error = None
    entry.locked_by = None
    entry.locked_ts = None

    _maybe_run_llm(db, ev.event_id, settings)
    _maybe_enqueue_sentiment(db, ev.event_id, settings)

    return str(ev.event_id)


def _retry_delay_seconds(attempt: int) -> int:
    """Exponential backoff delay in seconds for transient failures."""
    try:
        base = int(os.environ.get("NEWS_QUEUE_WORKER_RETRY_BACKOFF_BASE_SEC", "30"))
    except Exception:
        base = 30
    try:
        max_sec = int(os.environ.get("NEWS_QUEUE_WORKER_RETRY_BACKOFF_MAX_SEC", "3600"))
    except Exception:
        max_sec = 3600
    base = max(0, base)
    max_sec = max(0, max_sec)
    exp = min(max(0, int(attempt) - 1), 10)  # cap growth to avoid overflow
    return min(max_sec, base * (2**exp))


def run_once() -> bool:
    _ensure_logger_configured()
    SessionLocal = session_factory()
    settings = NewswireSettings.from_env()
    prefilter = MaterialityPrefilter(model_path=settings.tfidf_model_path)
    worker_id = _hostname_worker_id()
    try:
        max_attempts = int(os.environ.get("NEWS_QUEUE_WORKER_MAX_ATTEMPTS", "5"))
    except Exception:
        max_attempts = 5
    max_attempts = max(1, max_attempts)

    with SessionLocal() as db:
        try:
            entry = _claim_next_job(db, worker_id)
            if not entry:
                db.commit()
                return False
            if entry.suggestion is None:
                entry.status = "failed"
                entry.last_error = "suggestion_missing"
                entry.completed_ts = datetime.now(timezone.utc)
                db.commit()
                return True
            try:
                _process_suggestion(db, entry, entry.suggestion, settings, prefilter)
                db.commit()
                return True
            except Exception as exc:
                logger.exception("Failed to process suggestion %s", entry.suggestion.suggestion_id)
                db.rollback()
                entry = db.get(NewsIngestQueue, entry.queue_id)
                if entry is None:
                    return True
                now = datetime.now(timezone.utc)
                # Count this attempt (the in_progress update was rolled back).
                entry.attempts = int(entry.attempts or 0) + 1
                entry.last_error = str(exc)[:500]
                entry.locked_by = None
                entry.locked_ts = None
                entry.started_ts = None
                suggestion = entry.suggestion
                if entry.attempts < max_attempts:
                    delay = _retry_delay_seconds(entry.attempts)
                    entry.status = "pending"
                    entry.run_after_ts = now + timedelta(seconds=delay)
                    entry.completed_ts = None
                    if suggestion:
                        suggestion.status = "pending"
                        suggestion.status_reason = f"retry_in={delay}s error: {entry.last_error}"
                        suggestion.updated_at = now
                        suggestion.processed_at = None
                else:
                    entry.status = "failed"
                    entry.completed_ts = now
                    if suggestion:
                        suggestion.status = "rejected"
                        suggestion.status_reason = f"error: {entry.last_error}"
                        suggestion.updated_at = now
                        suggestion.processed_at = now
                db.commit()
                return True
        except SQLAlchemyError:
            logger.exception("Database error while claiming queue entry")
            db.rollback()
            return False


def run_forever() -> None:
    _ensure_logger_configured()
    sleep_seconds = int(os.environ.get("NEWS_QUEUE_WORKER_SLEEP_SEC", "5"))
    logger.info("Newswire queue worker starting (sleep=%ss)", sleep_seconds)
    while True:
        processed = False
        try:
            processed = run_once()
        except Exception:
            logger.exception("Unhandled error in queue worker cycle")
        if not processed:
            time.sleep(max(1, sleep_seconds))


if __name__ == "__main__":
    run_forever()
