from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimNewsCluster,
    FactNewsEvent,
    FactNewsRaw,
    NewsIngestQueue,
    NewsSuggestion,
)
from apps.common.src.news_utils.dedup import canonicalize_url, simhash64


def _safe_simhash(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    try:
        return int(simhash64(text))
    except Exception:
        return None


def normalize_submission(
    url: str,
    title: str,
    snippet: Optional[str] = None,
    body: Optional[str] = None,
) -> dict[str, Optional[str | int]]:
    canonical = canonicalize_url(url or "")
    if not canonical:
        canonical = (url or "").strip()
    url_hash = hashlib.sha1((canonical or "").encode("utf-8", errors="ignore")).hexdigest()
    combined_text = " ".join(part for part in [title or "", snippet or "", body or ""] if part)
    text_fp = _safe_simhash(combined_text)
    body_fp = _safe_simhash(body)
    body_bytes = len(body.encode("utf-8", errors="ignore")) if body else None
    return {
        "url_canonical": canonical,
        "url_hash": url_hash,
        "text_fingerprint": text_fp,
        "body_fingerprint": body_fp,
        "body_bytes": body_bytes,
    }


def _tz_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def enqueue_for_processing(
    db: Session,
    suggestion: NewsSuggestion,
    *,
    priority: int = 0,
    run_after: Optional[datetime] = None,
) -> NewsIngestQueue:
    existing = (
        db.execute(
            select(NewsIngestQueue).where(
                NewsIngestQueue.suggestion_id == suggestion.suggestion_id,
                NewsIngestQueue.status.in_(("pending", "in_progress")),
            )
        )
        .scalars()
        .first()
    )
    if existing:
        updated = False
        if priority is not None and int(priority or 0) != int(existing.priority or 0):
            existing.priority = int(priority or 0)
            updated = True
        normalized_run_after = _tz_aware(run_after)
        if normalized_run_after is not None:
            if existing.run_after_ts is None or normalized_run_after != existing.run_after_ts:
                existing.run_after_ts = normalized_run_after
                updated = True
        if updated:
            existing.locked_by = None
            existing.locked_ts = None
            db.flush()
        return existing

    queue_entry = NewsIngestQueue(
        suggestion_id=suggestion.suggestion_id,
        priority=int(priority or 0),
    )
    normalized_run_after = _tz_aware(run_after)
    if normalized_run_after is not None:
        queue_entry.run_after_ts = normalized_run_after
    db.add(queue_entry)
    db.flush()
    return queue_entry


def find_existing_raw_matches(
    db: Session,
    *,
    url_canonical: Optional[str] = None,
    url_hash: Optional[str] = None,
    text_fingerprint: Optional[int] = None,
    limit: int = 10,
) -> list[dict[str, Optional[str]]]:
    matches: list[dict[str, Optional[str]]] = []
    seen_raw_ids: set[str] = set()

    if url_canonical:
        rows = db.execute(
            select(FactNewsRaw, FactNewsEvent)
            .select_from(FactNewsRaw)
            .outerjoin(DimNewsCluster, DimNewsCluster.cluster_id == FactNewsRaw.cluster_id)
            .outerjoin(FactNewsEvent, FactNewsEvent.cluster_id == DimNewsCluster.cluster_id)
            .where(FactNewsRaw.url_canonical == url_canonical)
            .limit(limit)
        ).all()
        for raw, event in rows:
            if raw.raw_id in seen_raw_ids:
                continue
            seen_raw_ids.add(raw.raw_id)
            matches.append(
                {
                    "raw_id": raw.raw_id,
                    "event_id": event.event_id if event else None,
                    "url": raw.url_canonical,
                    "published_at": raw.published_at,
                    "source_domain": raw.source_domain,
                    "match_type": "url",
                }
            )
        if len(matches) >= limit:
            return matches[:limit]

    if text_fingerprint is not None:
        rows = db.execute(
            select(FactNewsRaw, FactNewsEvent)
            .select_from(FactNewsRaw)
            .outerjoin(DimNewsCluster, DimNewsCluster.cluster_id == FactNewsRaw.cluster_id)
            .outerjoin(FactNewsEvent, FactNewsEvent.cluster_id == DimNewsCluster.cluster_id)
            .where(FactNewsRaw.text_fingerprint == text_fingerprint)
            .limit(limit)
        ).all()
        for raw, event in rows:
            if raw.raw_id in seen_raw_ids:
                continue
            seen_raw_ids.add(raw.raw_id)
            matches.append(
                {
                    "raw_id": raw.raw_id,
                    "event_id": event.event_id if event else None,
                    "url": raw.url_canonical,
                    "published_at": raw.published_at,
                    "source_domain": raw.source_domain,
                    "match_type": "text_fingerprint",
                }
            )
        if len(matches) >= limit:
            return matches[:limit]

    # Look for other suggestions with the same hash for visibility
    if url_hash:
        existing_suggestions: Iterable[NewsSuggestion] = (
            db.execute(
                select(NewsSuggestion).where(NewsSuggestion.url_hash == url_hash).limit(limit)
            )
            .scalars()
            .all()
        )
        for suggestion in existing_suggestions:
            matches.append(
                {
                    "suggestion_id": suggestion.suggestion_id,
                    "status": suggestion.status,
                    "source_name": suggestion.source_name,
                    "url": suggestion.url_canonical,
                    "published_at": suggestion.published_at,
                    "match_type": "suggestion",
                }
            )
            if len(matches) >= limit:
                break

    return matches[:limit]
