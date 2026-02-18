from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import psycopg2

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

try:  # Prefer package-relative import when available
    from .db_utils import get_connection  # type: ignore[import]
    from .schedule_manager import remove_date_from_schedule  # type: ignore[import]
except ImportError:  # Fallback for direct execution
    from db_utils import get_connection  # type: ignore[import]
    from schedule_manager import remove_date_from_schedule  # type: ignore[import]

AnalysisCallable = Callable[..., Awaitable[bool]]
AlreadyCompletedCallable = Callable[[int], bool]
MarkCompletedCallable = Callable[[int], None]


async def run_consensus_batch(
    analyzer_app: Any,
    ai_analysis: AnalysisCallable,
    *,
    settings: Optional[Settings] = None,
    already_completed_today: Optional[AlreadyCompletedCallable] = None,
    mark_completed_today: Optional[MarkCompletedCallable] = None,
    schedule_file: Optional[Path] = None,
    connection_factory: Optional[Callable[[], psycopg2.extensions.connection]] = None,
) -> None:
    """Run a one-off batch of consensus symbols using v_latest_screener_consensus."""
    settings = settings or Settings()
    already_completed_today = already_completed_today or (lambda _stock_key: False)
    mark_completed_today = mark_completed_today or (lambda _stock_key: None)

    logger = get_logger(__name__)

    min_app = _coerce_int(getattr(settings, "sentiment_consensus_min_appearances", None), default=0)
    min_styles = _coerce_int(getattr(settings, "sentiment_consensus_min_styles", None), default=0)
    limit = _coerce_int(getattr(settings, "sentiment_consensus_limit", None), default=0)
    if limit <= 0:
        logger.info("Consensus batch: limit <= 0; skipping")
        return

    def get_db_connection() -> psycopg2.extensions.connection:
        if connection_factory is not None:
            return connection_factory()
        return get_connection(settings)

    rows = _fetch_consensus_rows(get_db_connection, min_app, min_styles, limit)
    if not rows:
        logger.info("Consensus batch: no eligible symbols returned from view")
        return

    skip_window = _coerce_int(getattr(settings, "sentiment_skip_if_within_days", None), default=1)

    processed = 0
    skipped_recent = 0
    for symbol, company_name in rows:
        sym = str(symbol).upper()
        stock_key = _lookup_stock_key(get_db_connection, sym)
        if stock_key is None:
            continue
        if already_completed_today(stock_key):
            logger.info(f"Consensus skip {sym}: already completed in this run")
            continue

        last_load_ts = _fetch_last_analysis_load_ts(get_db_connection, stock_key)
        if last_load_ts and _within_recency_window(last_load_ts, skip_window):
            skipped_recent += 1
            logger.info(
                f"Consensus skip {sym}: last analysis {_days_since_load(last_load_ts)} days ago (< {skip_window}d)"
            )
            continue

        logger.info(f"Consensus run for {(company_name or sym)} ({sym})")
        try:
            success = await ai_analysis(
                company_name,
                analyzer_app,
                sym,
                trigger="consensus",
            )
        except asyncio.TimeoutError:
            logger.warning(f"Consensus analysis timed out for {sym}; not retrying")
            success = False

        if not success:
            continue

        mark_completed_today(stock_key)
        processed += 1
        if schedule_file:
            try:
                remove_date_from_schedule(schedule_file, str(stock_key), datetime.now().date())
            except Exception:
                pass

    logger.info(
        f"Consensus batch done: processed={processed}, skipped_recent={skipped_recent}, requested={len(rows)}"
    )


def _coerce_int(value: Optional[int | str], default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _fetch_consensus_rows(get_conn, min_app: int, min_styles: int, limit: int):
    conn = get_conn()
    cur = conn.cursor()
    try:
        query = (
            "SELECT v.symbol, ds.company_name "
            "FROM rankalpha.v_latest_screener_consensus v "
            "JOIN rankalpha.dim_stock ds ON ds.symbol = v.symbol "
            "JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE "
            "WHERE ds.is_active IS TRUE "
        )
        params = []
        if min_app > 0:
            query += " AND v.appearances >= %s"
            params.append(min_app)
        if min_styles > 0:
            query += " AND v.styles_distinct >= %s"
            params.append(min_styles)
        query += " ORDER BY v.consensus_score DESC LIMIT %s"
        params.append(limit)
        cur.execute(query, tuple(params))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _lookup_stock_key(get_conn, symbol: str) -> Optional[int]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT ds.stock_key FROM rankalpha.dim_stock ds "
            "JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE "
            "WHERE UPPER(ds.symbol) = %s AND ds.is_active IS TRUE",
            (symbol.upper(),),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        cur.close()
        conn.close()


def _fetch_last_analysis_load_ts(get_conn, stock_key: int) -> Optional[datetime]:
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT MAX(load_ts) FROM rankalpha.fact_ai_stock_analysis WHERE stock_key = %s",
            (stock_key,),
        )
        row = cur.fetchone()
        ts = row[0] if row else None
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
        return None
    finally:
        cur.close()
        conn.close()


def _within_recency_window(last_load_ts: Optional[datetime], skip_window: int) -> bool:
    if not last_load_ts:
        return False
    try:
        delta = datetime.now(timezone.utc) - last_load_ts.astimezone(timezone.utc)
        return delta.days < max(skip_window, 1)
    except Exception:
        return False


def _days_since_load(last_load_ts: datetime) -> int:
    try:
        delta = datetime.now(timezone.utc) - last_load_ts.astimezone(timezone.utc)
        return delta.days
    except Exception:
        return 0
