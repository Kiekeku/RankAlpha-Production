from __future__ import annotations

import hashlib
from typing import Any, Dict, List
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimNewsCluster,
    FactNewsEvent,
    FactNewsImpact,
    FactNewsRaw,
    NewsSuggestion,
)

from .dedup import canonicalize_url, simhash64


def _build_dedup_key(url_canon: str, text_fp: int | None) -> str:
    """Build a dedup key that is stable across URL query variants.

    Prefer canonical host+path + fingerprint when available; fall back to canonical URL.
    This avoids collisions between different articles on the same host that share a title/snippet.
    """
    if isinstance(text_fp, int) and text_fp > 0:
        try:
            parsed = urlparse(url_canon)
            host = (parsed.netloc or "").lower()
            path = parsed.path or "/"
        except Exception:
            host = ""
            path = ""
        if host and path:
            basis = f"fp_path:{host}:{path}:{text_fp}"
        else:
            basis = f"fp_url:{url_canon}:{text_fp}"
    else:
        basis = f"url:{url_canon}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def upsert_raw(db: Session, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for d in docs:
        url = d.get("url") or d.get("link") or ""
        url_canon = canonicalize_url(url)
        title = d.get("title") or ""
        snippet = d.get("snippet") or ""
        text_fp = d.get("text_fp")
        if text_fp is None:
            try:
                text_fp = int(simhash64(f"{title} {snippet}"))
            except Exception:
                text_fp = None
        dedup = _build_dedup_key(url_canon, text_fp if isinstance(text_fp, int) else None)
        row = {
            "source_domain": d.get("source_domain") or "",
            "url_canonical": url_canon,
            "title": title,
            "snippet": snippet,
            "language": d.get("language"),
            "country": d.get("country"),
            "published_at": d.get("published_at"),
            "dedup_key": dedup,
            "text_fingerprint": text_fp,
            "raw_json": d.get("raw") or {},
        }
        stmt = pg_insert(FactNewsRaw).values(**row)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[FactNewsRaw.dedup_key],
            set_={
                "source_domain": excluded.source_domain,
                "url_canonical": excluded.url_canonical,
                "title": func.coalesce(func.nullif(excluded.title, ""), FactNewsRaw.title),
                "snippet": func.coalesce(func.nullif(excluded.snippet, ""), FactNewsRaw.snippet),
                "language": func.coalesce(excluded.language, FactNewsRaw.language),
                "country": func.coalesce(excluded.country, FactNewsRaw.country),
                "published_at": func.coalesce(excluded.published_at, FactNewsRaw.published_at),
                "text_fingerprint": func.coalesce(
                    excluded.text_fingerprint, FactNewsRaw.text_fingerprint
                ),
                "raw_json": func.coalesce(excluded.raw_json, FactNewsRaw.raw_json),
            },
        ).returning(FactNewsRaw.raw_id)
        raw_id = db.execute(stmt).scalar()
        if raw_id is None:
            raw_id = db.query(FactNewsRaw.raw_id).filter(FactNewsRaw.dedup_key == dedup).scalar()
        d["raw_id"] = raw_id
        d["url_canonical"] = url_canon
        results.append(d)
    db.flush()
    return results


def create_cluster(
    db: Session, centroid_raw_id, simhash: int, members_raw_ids: List
) -> DimNewsCluster:
    """Create (or reuse) a cluster and attach member raw rows.

    This function is intentionally idempotent:
    - If any member already belongs to an existing cluster, reuse that cluster_id.
    - If members span multiple clusters, pick a primary and merge by re-pointing members.
    """
    members = [rid for rid in members_raw_ids if rid]
    if not members:
        raise ValueError("create_cluster() requires at least one member raw_id")

    existing_cluster_ids = {
        cid
        for (cid,) in db.query(FactNewsRaw.cluster_id)
        .filter(FactNewsRaw.raw_id.in_(members))
        .filter(FactNewsRaw.cluster_id.is_not(None))
        .distinct()
        .all()
        if cid is not None
    }

    cluster_by_id: dict[Any, DimNewsCluster] = {}
    if existing_cluster_ids:
        clusters = (
            db.query(DimNewsCluster)
            .filter(DimNewsCluster.cluster_id.in_(list(existing_cluster_ids)))
            .all()
        )
        cluster_by_id = {c.cluster_id: c for c in clusters}

    # If member rows point at missing dim_news_cluster rows, fall back to creating a new cluster.
    existing_cluster_ids = set(cluster_by_id.keys())

    if existing_cluster_ids:
        # Prefer the cluster that already has an event (keeps event/suggestion joins stable).
        primary_cluster_id = (
            db.query(FactNewsEvent.cluster_id)
            .filter(FactNewsEvent.cluster_id.in_(list(existing_cluster_ids)))
            .order_by(FactNewsEvent.decided_at.desc())
            .limit(1)
            .scalar()
        )
        if primary_cluster_id not in existing_cluster_ids:
            # Prefer an "official" cluster if present; otherwise choose the oldest (stable).
            official = [c for c in cluster_by_id.values() if bool(c.is_official)]
            if official:
                official.sort(key=lambda c: c.first_seen_ts)
                primary_cluster_id = official[0].cluster_id
            else:
                primary_cluster_id = min(
                    cluster_by_id.values(), key=lambda c: c.first_seen_ts
                ).cluster_id

        primary = cluster_by_id[primary_cluster_id]
        secondary_ids = [cid for cid in existing_cluster_ids if cid != primary_cluster_id]

        # Merge secondary clusters into primary (raw membership + foreign-keyed references).
        if secondary_ids:
            db.query(FactNewsRaw).filter(FactNewsRaw.cluster_id.in_(secondary_ids)).update(
                {FactNewsRaw.cluster_id: primary_cluster_id},
                synchronize_session=False,
            )
            db.query(NewsSuggestion).filter(NewsSuggestion.cluster_id.in_(secondary_ids)).update(
                {NewsSuggestion.cluster_id: primary_cluster_id},
                synchronize_session=False,
            )
            db.query(FactNewsEvent).filter(FactNewsEvent.cluster_id.in_(secondary_ids)).update(
                {FactNewsEvent.cluster_id: primary_cluster_id},
                synchronize_session=False,
            )

        # Ensure the provided members are attached to the primary cluster.
        db.query(FactNewsRaw).filter(FactNewsRaw.raw_id.in_(members)).update(
            {FactNewsRaw.cluster_id: primary_cluster_id},
            synchronize_session=False,
        )

        # Backfill centroid/simhash for non-official clusters (keep official clusters stable).
        if not primary.is_official:
            if primary.centroid_raw_id is None and centroid_raw_id:
                primary.centroid_raw_id = centroid_raw_id
            try:
                primary.simhash = int(simhash)
            except Exception:
                pass
            try:
                primary.source_count = int(
                    db.query(func.count(FactNewsRaw.raw_id))
                    .filter(FactNewsRaw.cluster_id == primary_cluster_id)
                    .scalar()
                    or primary.source_count
                    or 1
                )
            except Exception:
                pass

        db.flush()
        return primary

    # No prior cluster: create a fresh one.
    cl = DimNewsCluster(
        simhash=int(simhash), source_count=len(members), centroid_raw_id=centroid_raw_id
    )
    db.add(cl)
    db.flush()
    db.query(FactNewsRaw).filter(FactNewsRaw.raw_id.in_(members)).update(
        {FactNewsRaw.cluster_id: cl.cluster_id},
        synchronize_session=False,
    )
    db.flush()
    return cl


def insert_event(
    db: Session,
    cluster_id,
    score: float,
    summary: str | None,
    event_type: str | None = None,
    direction: str | None = None,
    timescale: str | None = None,
    model_version: str = "prefilter_v1",
    is_high_confidence: bool = False,
    prefilter_reason: str | None = None,
) -> FactNewsEvent:
    ev = FactNewsEvent(
        cluster_id=cluster_id,
        materiality_score=round(float(score) * 100.0, 2),
        summary=summary,
        event_type=event_type,
        direction=direction,
        timescale=timescale,
        model_version=model_version,
        is_high_confidence=is_high_confidence,
        prefilter_reason=prefilter_reason,
    )
    db.add(ev)
    db.flush()
    return ev


def insert_impacts(db: Session, event_id, impacts: List[Dict[str, Any]]):
    for imp in impacts:
        db.add(
            FactNewsImpact(
                event_id=event_id,
                stock_key=int(imp["stock_key"]),
                role=str(imp.get("role") or "issuer"),
                confidence=float(imp.get("confidence", 0.5)),
                rationale=str(imp.get("rationale", "")),
            )
        )
    db.flush()
