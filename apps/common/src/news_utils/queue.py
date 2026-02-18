from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.common.src.models import DimStock, SentimentAnalysisQueue


def enqueue_sentiment_analysis(
    db: Session,
    stock_key: int,
    event_id: Optional[str] = None,
    symbol: Optional[str] = None,
    title: Optional[str] = None,
    url: Optional[str] = None,
    priority: int = 0,
    run_after_ts: Optional[datetime] = None,
    source: str = "newswire",
    force_run: bool = False,
    raw_id: Optional[str] = None,
) -> bool:
    if symbol is None:
        r = db.query(DimStock.symbol).filter(DimStock.stock_key == int(stock_key)).one_or_none()
        symbol = (r[0] if r else "").upper() if r else ""
    if not symbol:
        return False
    if run_after_ts is None:
        run_after_ts = datetime.now(tz=timezone.utc)
    try:
        # Normalize to UTC date for duplicate guard
        dt = run_after_ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        candidate_date = dt.astimezone(timezone.utc).date()
    except Exception:
        candidate_date = datetime.now(tz=timezone.utc).date()

    # Skip if an earlier or same-day pending/in-progress item exists for this stock (event-agnostic only)
    try:
        exists = (
            db.query(SentimentAnalysisQueue.queue_id)
            .filter(SentimentAnalysisQueue.stock_key == int(stock_key))
            .filter(SentimentAnalysisQueue.event_id.is_(None))
            .filter(SentimentAnalysisQueue.status.in_(["pending", "in_progress"]))
            .filter(SentimentAnalysisQueue.run_after_date <= candidate_date)
            .first()
        )
        if exists is not None:
            return False
    except Exception:
        # If guard check fails, fall back to best-effort insert below
        pass
    row = {
        "stock_key": int(stock_key),
        "symbol": symbol,
        "event_id": event_id,
        "title": title,
        "url": url,
        "priority": int(priority),
        "status": "pending",
        "run_after_ts": run_after_ts,
        "source": source,
        "force_run": bool(force_run),
        "raw_id": raw_id,
    }
    try:
        stmt = pg_insert(SentimentAnalysisQueue).values(**row).on_conflict_do_nothing()
        res = db.execute(stmt)
        return res.rowcount > 0
    except Exception:
        return False
