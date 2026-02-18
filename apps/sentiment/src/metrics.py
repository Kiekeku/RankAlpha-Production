from __future__ import annotations

import asyncio
from typing import Callable, Optional

import psycopg2

from apps.common.src.logging import get_logger
from apps.common.src.observability import get_or_create_counter, get_or_create_gauge

logger = get_logger(__name__)


try:
    SENTIMENT_SYMBOLS_PROCESSED = get_or_create_counter(
        "rankalpha_sentiment_symbols_processed_total",
        "Count of sentiment analysis attempts per symbol, grouped by outcome and trigger.",
        labelnames=("outcome", "trigger"),
    )
    for outcome in ("success", "error", "skipped"):
        for trigger in ("queue", "schedule", "on_demand", "consensus"):
            SENTIMENT_SYMBOLS_PROCESSED.labels(outcome=outcome, trigger=trigger).inc(0)
except Exception:  # pragma: no cover - prometheus_client not installed / registry errors
    SENTIMENT_SYMBOLS_PROCESSED = None

try:
    SENTIMENT_QUEUE_DEPTH = get_or_create_gauge(
        "rankalpha_sentiment_queue_depth",
        "Current sentiment_analysis_queue row counts grouped by state.",
        labelnames=("state",),
    )
except Exception:  # pragma: no cover - prometheus_client not installed / registry errors
    SENTIMENT_QUEUE_DEPTH = None


def record_symbol_processed(*, outcome: str, trigger: str) -> None:
    if SENTIMENT_SYMBOLS_PROCESSED is None:
        return
    try:
        SENTIMENT_SYMBOLS_PROCESSED.labels(outcome=str(outcome), trigger=str(trigger)).inc()
    except Exception:
        return


def update_queue_depth_metrics(
    connection_factory: Callable[[], psycopg2.extensions.connection],
) -> None:
    if SENTIMENT_QUEUE_DEPTH is None:
        return

    counts = {"pending": 0, "due": 0, "in_progress": 0, "failed": 0}
    conn: Optional[psycopg2.extensions.connection] = None
    cur = None
    try:
        conn = connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE status = 'pending') AS pending,
              COUNT(*) FILTER (WHERE status = 'pending' AND run_after_ts <= now()) AS due,
              COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
              COUNT(*) FILTER (WHERE status = 'failed') AS failed
            FROM rankalpha.sentiment_analysis_queue
            """
        )
        row = cur.fetchone()
        if row:
            counts["pending"] = int(row[0] or 0)
            counts["due"] = int(row[1] or 0)
            counts["in_progress"] = int(row[2] or 0)
            counts["failed"] = int(row[3] or 0)
    except Exception as exc:
        logger.debug("Queue metrics query failed: %s", exc)
        return
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass

    try:
        for state, value in counts.items():
            SENTIMENT_QUEUE_DEPTH.labels(state=state).set(value)
    except Exception:
        return


async def run_queue_metrics_poller(
    *,
    connection_factory: Callable[[], psycopg2.extensions.connection],
    interval_seconds: int,
) -> None:
    interval_seconds = max(int(interval_seconds), 1)
    while True:
        update_queue_depth_metrics(connection_factory)
        await asyncio.sleep(interval_seconds)
