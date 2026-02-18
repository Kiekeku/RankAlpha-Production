from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.common.src.models import (
    DimNewsCluster,
    FactNewsEvent,
    FactNewsImpact,
    FactNewsRaw,
)

from .dedup import canonicalize_url


def _sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def _build_dedup_key(url_canon: str, text_fp: int | None) -> str:
    if isinstance(text_fp, int) and text_fp > 0:
        try:
            parsed = urlparse(url_canon)
            host = (parsed.netloc or "").lower()
            path = parsed.path or "/"
        except Exception:
            host = ""
            path = ""
        if host and path:
            return _sha1(f"fp_path:{host}:{path}:{text_fp}")
        return _sha1(f"fp_url:{url_canon}:{text_fp}")
    return _sha1(f"url:{url_canon}")


def upsert_raw(db: Session, docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Upsert raw docs into fact_news_raw and return rows augmented with raw_id and url_canonical.
    Uses ON CONFLICT DO NOTHING on dedup_key.
    """
    results: List[Dict[str, Any]] = []
    for d in docs:
        url = d.get("url") or d.get("link") or ""
        url_canon = canonicalize_url(url)
        text_fp = d.get("text_fp")
        try:
            text_fp_val = int(text_fp) if text_fp is not None else None
        except Exception:
            text_fp_val = None
        dedup = _build_dedup_key(url_canon, text_fp_val)
        title = d.get("title") or ""
        snippet = d.get("snippet")
        row = {
            "source_domain": d.get("source_domain") or "",
            "url_canonical": url_canon,
            "title": title,
            "snippet": snippet,
            "language": d.get("language"),
            "country": d.get("country"),
            "published_at": d.get("published_at"),
            "dedup_key": dedup,
            "text_fingerprint": text_fp_val,
        }
        stmt = (
            pg_insert(FactNewsRaw)
            .values(**row)
            .on_conflict_do_nothing(index_elements=[FactNewsRaw.dedup_key])
            .returning(FactNewsRaw.raw_id)
        )
        raw_id = db.execute(stmt).scalar()
        if raw_id is None:
            # already exists; fetch id
            raw_id = db.query(FactNewsRaw.raw_id).filter(FactNewsRaw.dedup_key == dedup).scalar()
        d["raw_id"] = raw_id
        d["url_canonical"] = url_canon
        results.append(d)
    db.flush()
    return results


def create_cluster(
    db: Session, centroid_raw_id, simhash: int, members_raw_ids: List
) -> DimNewsCluster:
    cl = DimNewsCluster(
        simhash=simhash, source_count=len(members_raw_ids), centroid_raw_id=centroid_raw_id
    )
    db.add(cl)
    db.flush()
    # update members to reference cluster
    db.query(FactNewsRaw).filter(FactNewsRaw.raw_id.in_(members_raw_ids)).update(
        {FactNewsRaw.cluster_id: cl.cluster_id}, synchronize_session=False
    )
    db.flush()
    return cl


def insert_event(
    db: Session,
    cluster_id,
    score: float,
    summary: Optional[str],
    event_type: Optional[str] = None,
    direction: Optional[str] = None,
    timescale: Optional[str] = None,
    model_version: str = "prefilter_v1",
    is_high_confidence: bool = False,
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
