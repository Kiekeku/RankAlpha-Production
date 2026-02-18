from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from apps.api.src.database import get_db
from apps.api.src.security import require_admin_access
from apps.api.src.services.news_ingest import (
    enqueue_for_processing,
    find_existing_raw_matches,
    normalize_submission,
)
from apps.common.src.models import NewsIngestQueue, NewsSuggestion

router = APIRouter(
    tags=["news-ingest"],
    prefix="/api/v1/news/suggestions",
    dependencies=[Depends(require_admin_access)],
)


class QueueEntryOut(BaseModel):
    queue_id: UUID
    status: str
    priority: int
    enqueue_ts: datetime
    run_after_ts: datetime
    started_ts: Optional[datetime] = None
    completed_ts: Optional[datetime] = None
    attempts: int
    last_error: Optional[str] = None
    locked_by: Optional[str] = None
    locked_ts: Optional[datetime] = None


class SuggestionOut(BaseModel):
    suggestion_id: UUID
    source_name: str
    submitter_reference: Optional[str] = None
    idempotency_key: Optional[str] = None
    status: str
    status_reason: Optional[str] = None
    submitted_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None
    url: str
    url_canonical: str
    title: str
    snippet: Optional[str] = None
    body_text: Optional[str] = None
    body_bytes: Optional[int] = None
    published_at: Optional[datetime] = None
    language: Optional[str] = None
    country: Optional[str] = None
    raw_payload: Optional[dict] = None
    cluster_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    queue: List[QueueEntryOut] = Field(default_factory=list)


class SuggestionCreateRequest(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=120)
    url: str
    title: str = Field(..., min_length=1, max_length=1000)
    idempotency_key: Optional[str] = Field(default=None, max_length=200)
    submitter_reference: Optional[str] = Field(default=None, max_length=200)
    snippet: Optional[str] = Field(default=None, max_length=4000)
    body_text: Optional[str] = Field(default=None, max_length=200000)
    published_at: Optional[datetime] = None
    language: Optional[str] = Field(default=None, max_length=20)
    country: Optional[str] = Field(default=None, max_length=4)
    raw_payload: Optional[dict] = None
    priority: Optional[int] = Field(default=0, ge=-20, le=20)
    run_after_ts: Optional[datetime] = None


class SuggestionUpdateRequest(BaseModel):
    snippet: Optional[str] = Field(default=None, max_length=4000)
    body_text: Optional[str] = Field(default=None, max_length=200000)
    status: Optional[str] = None
    status_reason: Optional[str] = Field(default=None, max_length=500)
    language: Optional[str] = Field(default=None, max_length=20)
    country: Optional[str] = Field(default=None, max_length=4)
    raw_payload: Optional[dict] = None


class SuggestionListResponse(BaseModel):
    items: List[SuggestionOut]
    total: int
    page: int
    page_size: int


class DedupeCheckRequest(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    body_text: Optional[str] = None
    text_fingerprint: Optional[int] = None
    limit: Optional[int] = Field(default=10, ge=1, le=50)


class DedupeMatch(BaseModel):
    match_type: str
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    source_domain: Optional[str] = None
    raw_id: Optional[UUID] = None
    event_id: Optional[UUID] = None
    suggestion_id: Optional[UUID] = None
    status: Optional[str] = None
    source_name: Optional[str] = None


class DedupeCheckResponse(BaseModel):
    matches: List[DedupeMatch]


def _serialize_queue(entries: list[NewsIngestQueue]) -> list[QueueEntryOut]:
    return [
        QueueEntryOut(
            queue_id=e.queue_id,
            status=e.status,
            priority=e.priority,
            enqueue_ts=e.enqueue_ts,
            run_after_ts=e.run_after_ts,
            started_ts=e.started_ts,
            completed_ts=e.completed_ts,
            attempts=e.attempts,
            last_error=e.last_error,
            locked_by=e.locked_by,
            locked_ts=e.locked_ts,
        )
        for e in entries
    ]


def _serialize_suggestion(suggestion: NewsSuggestion) -> SuggestionOut:
    queue_entries = sorted(
        list(suggestion.queue_entries or []),
        key=lambda q: (q.enqueue_ts or datetime(1970, 1, 1, tzinfo=timezone.utc)),
        reverse=True,
    )
    return SuggestionOut(
        suggestion_id=suggestion.suggestion_id,
        source_name=suggestion.source_name,
        submitter_reference=suggestion.submitter_reference,
        idempotency_key=suggestion.idempotency_key,
        status=suggestion.status,
        status_reason=suggestion.status_reason,
        submitted_at=suggestion.submitted_at,
        updated_at=suggestion.updated_at,
        processed_at=suggestion.processed_at,
        url=suggestion.url,
        url_canonical=suggestion.url_canonical,
        title=suggestion.title,
        snippet=suggestion.snippet,
        body_text=suggestion.body_text,
        body_bytes=suggestion.body_bytes,
        published_at=suggestion.published_at,
        language=suggestion.language,
        country=suggestion.country,
        raw_payload=suggestion.raw_payload,
        cluster_id=suggestion.cluster_id,
        event_id=suggestion.event_id,
        queue=_serialize_queue(queue_entries),
    )


def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.post("", response_model=SuggestionOut, status_code=201)
def create_suggestion(
    request: SuggestionCreateRequest,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    normalized = normalize_submission(
        url=str(request.url),
        title=request.title,
        snippet=request.snippet,
        body=request.body_text,
    )

    existing: Optional[NewsSuggestion] = None
    if request.idempotency_key:
        existing = (
            db.execute(
                select(NewsSuggestion)
                .options(selectinload(NewsSuggestion.queue_entries))
                .where(
                    func.lower(NewsSuggestion.source_name) == request.source_name.lower(),
                    NewsSuggestion.idempotency_key == request.idempotency_key,
                )
            )
            .scalars()
            .first()
        )
        if existing:
            enqueue_for_processing(
                db,
                existing,
                priority=request.priority or 0,
                run_after=_ensure_aware(request.run_after_ts),
            )
            db.commit()
            db.refresh(existing)
            return _serialize_suggestion(existing)

    suggestion = NewsSuggestion(
        source_name=request.source_name.strip(),
        submitter_reference=request.submitter_reference,
        idempotency_key=request.idempotency_key,
        status="pending",
        url=str(request.url).strip(),
        url_canonical=normalized["url_canonical"],
        url_hash=normalized["url_hash"],
        title=request.title.strip(),
        snippet=request.snippet,
        body_text=request.body_text,
        body_bytes=normalized["body_bytes"],
        body_fingerprint=normalized["body_fingerprint"],
        text_fingerprint=normalized["text_fingerprint"],
        published_at=_ensure_aware(request.published_at),
        language=(
            request.language.strip().lower()
            if request.language and request.language.strip()
            else None
        ),
        country=(
            request.country.strip().upper() if request.country and request.country.strip() else None
        ),
        raw_payload=request.raw_payload,
        submitted_at=now,
        updated_at=now,
    )
    db.add(suggestion)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Suggestion already exists for this idempotency key",
        ) from exc

    enqueue_for_processing(
        db,
        suggestion,
        priority=request.priority or 0,
        run_after=_ensure_aware(request.run_after_ts),
    )
    db.commit()
    db.refresh(suggestion)
    return _serialize_suggestion(suggestion)


@router.get("", response_model=SuggestionListResponse)
def list_suggestions(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    base_query = select(NewsSuggestion)
    if status:
        base_query = base_query.where(NewsSuggestion.status == status)
    if source:
        base_query = base_query.where(func.lower(NewsSuggestion.source_name) == source.lower())

    count_query = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_query).scalar() or 0
    query = base_query.options(selectinload(NewsSuggestion.queue_entries))
    rows = (
        db.execute(
            query.order_by(NewsSuggestion.submitted_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    items = [_serialize_suggestion(row) for row in rows]
    return SuggestionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{suggestion_id}", response_model=SuggestionOut)
def get_suggestion(
    suggestion_id: UUID,
    db: Session = Depends(get_db),
):
    suggestion = (
        db.execute(
            select(NewsSuggestion)
            .options(selectinload(NewsSuggestion.queue_entries))
            .where(NewsSuggestion.suggestion_id == suggestion_id)
        )
        .scalars()
        .first()
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return _serialize_suggestion(suggestion)


@router.put("/{suggestion_id}", response_model=SuggestionOut)
def update_suggestion(
    suggestion_id: UUID,
    payload: SuggestionUpdateRequest,
    db: Session = Depends(get_db),
):
    suggestion = db.get(NewsSuggestion, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    changed = False
    if payload.snippet is not None:
        suggestion.snippet = payload.snippet
        changed = True
    if payload.body_text is not None:
        suggestion.body_text = payload.body_text
        normalized = normalize_submission(
            url=suggestion.url,
            title=suggestion.title,
            snippet=suggestion.snippet,
            body=payload.body_text,
        )
        suggestion.body_fingerprint = normalized["body_fingerprint"]
        suggestion.body_bytes = normalized["body_bytes"]
        suggestion.text_fingerprint = normalized["text_fingerprint"]
        changed = True
    if payload.status is not None:
        suggestion.status = payload.status
        changed = True
    if payload.status_reason is not None:
        suggestion.status_reason = payload.status_reason
        changed = True
    if payload.language is not None:
        suggestion.language = (
            payload.language.strip().lower()
            if payload.language and payload.language.strip()
            else None
        )
        changed = True
    if payload.country is not None:
        suggestion.country = (
            payload.country.strip().upper() if payload.country and payload.country.strip() else None
        )
        changed = True
    if payload.raw_payload is not None:
        suggestion.raw_payload = payload.raw_payload
        changed = True

    if changed:
        suggestion.updated_at = datetime.now(timezone.utc)
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)

    return _serialize_suggestion(suggestion)


@router.post("/dedupe-check", response_model=DedupeCheckResponse)
def dedupe_check(
    request: DedupeCheckRequest = Body(...),
    db: Session = Depends(get_db),
):
    normalized = normalize_submission(
        url=request.url or "",
        title=request.title or "",
        snippet=request.snippet or "",
        body=request.body_text or "",
    )
    text_fp = request.text_fingerprint or normalized["text_fingerprint"]
    matches = find_existing_raw_matches(
        db,
        url_canonical=normalized["url_canonical"],
        url_hash=normalized["url_hash"],
        text_fingerprint=text_fp,
        limit=request.limit or 10,
    )
    result = []
    for match in matches:
        result.append(
            DedupeMatch(
                match_type=match.get("match_type") or "unknown",
                url=match.get("url"),
                published_at=match.get("published_at"),
                source_domain=match.get("source_domain"),
                raw_id=match.get("raw_id"),
                event_id=match.get("event_id"),
                suggestion_id=match.get("suggestion_id"),
                status=match.get("status"),
                source_name=match.get("source_name"),
            )
        )
    return DedupeCheckResponse(matches=result)
