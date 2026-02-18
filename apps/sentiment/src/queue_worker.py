from __future__ import annotations

import contextlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Tuple

import psycopg2

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

try:
    from .metrics import update_queue_depth_metrics
except Exception:  # pragma: no cover - direct execution fallback
    try:
        from metrics import update_queue_depth_metrics  # type: ignore
    except Exception:
        update_queue_depth_metrics = None  # type: ignore

try:
    from .signals.pipeline import Document, run_pipeline  # type: ignore[import]
except ImportError:  # pragma: no cover - fallback for script execution
    from signals.pipeline import Document, run_pipeline  # type: ignore[import]

try:  # Prefer relative import when used as package
    from .db_utils import get_connection  # type: ignore[import]
except ImportError:
    from db_utils import get_connection  # type: ignore[import]

AnalysisCallable = Callable[..., Awaitable[bool]]
AlreadyCompletedCallable = Callable[[int], bool]
MarkCompletedCallable = Callable[[int], None]


async def consume_queue_items(
    analyzer_app: Any,
    ai_analysis: AnalysisCallable,
    *,
    max_items: int = 5,
    settings: Optional[Settings] = None,
    already_completed_today: Optional[AlreadyCompletedCallable] = None,
    mark_completed_today: Optional[MarkCompletedCallable] = None,
    connection_factory: Optional[Callable[[], psycopg2.extensions.connection]] = None,
) -> int:
    """Consume up to ``max_items`` from rankalpha.sentiment_analysis_queue and run analyses.

    Parameters
    ----------
    analyzer_app:
        Shared MCP analyzer application passed through from the main runtime.
    ai_analysis:
        Coroutine that executes the full AI analysis workflow.
    max_items:
        Maximum number of queue rows to process in one pass. Defaults to 5.
    settings:
        Optional pre-loaded Settings instance. When omitted a fresh instance is created.
    already_completed_today:
        Callable used to determine whether a stock has already been handled in the
        current process/day. When ``None`` a stub that always returns ``False`` is used.
    mark_completed_today:
        Callable used to record completions within the current process/day.
    """
    logger = get_logger(__name__)

    if str(os.getenv("SENTIMENT_USE_QUEUE", "true")).lower() not in {"1", "true", "yes", "on"}:
        return 0

    settings = settings or Settings()
    already_completed_today = already_completed_today or (lambda _stock_key: False)
    mark_completed_today = mark_completed_today or (lambda _stock_key: None)

    def _get_db_connection() -> psycopg2.extensions.connection:
        if connection_factory is not None:
            return connection_factory()
        return get_connection(settings)

    if update_queue_depth_metrics is not None:
        try:
            update_queue_depth_metrics(_get_db_connection)
        except Exception:
            pass

    taken: list[tuple] = []
    grace_seconds = max(
        0, _coerce_int(os.getenv("SENTIMENT_QUEUE_IN_PROGRESS_GRACE_SEC"), default=600)
    )
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    WITH cte AS (
                      SELECT queue_id
                      FROM rankalpha.sentiment_analysis_queue
                      WHERE run_after_ts <= now()
                        AND (
                            status = 'pending'
                            OR (
                                status = 'in_progress'
                                AND (
                                    started_ts IS NULL
                                    OR started_ts <= now() - (%s * interval '1 second')
                                )
                            )
                        )                    
                      ORDER BY priority DESC, run_after_ts ASC, enqueue_ts ASC
                      LIMIT %s
                      FOR UPDATE SKIP LOCKED
                    )
                    UPDATE rankalpha.sentiment_analysis_queue saq
                    SET status='in_progress', started_ts=now(), attempts=attempts+1
                    FROM cte
                    WHERE saq.queue_id = cte.queue_id
                    RETURNING saq.queue_id,
                              saq.stock_key,
                              saq.symbol,
                              saq.event_id,
                              COALESCE(saq.title,''),
                              COALESCE(saq.url,''),
                              COALESCE(saq.source, ''),
                              saq.force_run,
                              saq.raw_id;
                    """,
                    (grace_seconds, max(1, int(max_items))),
                )
                taken = cur.fetchall()
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.error(f"Queue: error taking items: {exc}")
                taken = []

    if not taken:
        if update_queue_depth_metrics is not None:
            try:
                update_queue_depth_metrics(_get_db_connection)
            except Exception:
                pass
        return 0

    processed = 0
    max_attempts = _coerce_int(os.getenv("SENTIMENT_QUEUE_MAX_ATTEMPTS"), default=3)
    backoff_base = _coerce_int(os.getenv("SENTIMENT_QUEUE_BACKOFF_BASE_SEC"), default=300)
    skip_window = _coerce_int(getattr(settings, "sentiment_skip_if_within_days", None), default=1)

    for (
        qid,
        stock_key,
        symbol,
        event_id,
        news_title,
        news_url,
        source,
        force_run,
        raw_id,
    ) in taken:
        sym = str(symbol).upper()
        stock_key_int = int(stock_key)
        should_force = bool(force_run)
        ok = False
        raw_body: Optional[str] = None
        raw_source: Optional[str] = None
        raw_published: Optional[str] = None
        raw_title: Optional[str] = None
        raw_url: Optional[str] = None

        if raw_id:
            raw_ctx = _load_raw_context(_get_db_connection, raw_id)
            if raw_ctx:
                raw_body, raw_published, raw_source, raw_title, raw_url = raw_ctx
            if not news_title and raw_title:
                news_title = raw_title
            if not news_url and raw_url:
                news_url = raw_url
            if raw_body:
                try:
                    run_pipeline(
                        [
                            Document(
                                doc_id=str(raw_id),
                                publish_datetime=raw_published,
                                source_name=raw_source or source,
                                url=news_url or None,
                                text=raw_body,
                                ticker_candidates=[sym],
                            )
                        ],
                        ticker=sym,
                        trading_date=datetime.now(timezone.utc).date().isoformat(),
                    )
                except Exception as exc:
                    logger.warning("Pipeline stub failed for %s (%s): %s", sym, raw_id, exc)

        try:
            if not should_force and already_completed_today(stock_key_int):
                logger.info(f"Queue skip {sym}: already completed today in this process")
                ok = True
            else:
                if not should_force and skip_window > 0:
                    last_load_ts = _fetch_last_analysis_load_ts(_get_db_connection, stock_key_int)
                    if last_load_ts:
                        delta_days = _days_since_load(last_load_ts)
                        threshold = max(skip_window, 1)
                        if delta_days < threshold:
                            defer_days = max(1, threshold - delta_days)
                            _defer_queue_item(
                                qid=qid,
                                get_conn=_get_db_connection,
                                defer_days=defer_days,
                                attempts_modifier=-1,
                                logger=logger,
                                symbol=sym,
                                source=source,
                            )
                            continue
                elif should_force:
                    logger.info(
                        f"Queue force-run {sym}: bypassing recency guard (source={source or 'queue'})"
                    )

                ok = await ai_analysis(
                    None,
                    analyzer_app,
                    sym,
                    news_title=news_title or None,
                    news_url=news_url or None,
                    trigger="queue",
                )
                if ok:
                    mark_completed_today(stock_key_int)
        except Exception as exc:
            logger.error(f"Queue: analysis failed for {sym}: {exc}")
            ok = False

        _update_queue_row(
            qid=qid,
            success=ok,
            max_attempts=max_attempts,
            backoff_base=backoff_base,
            get_conn=_get_db_connection,
            logger=logger,
        )
        if ok:
            processed += 1

    cleanup_days = _coerce_int(os.getenv("SENTIMENT_QUEUE_CLEANUP_DAYS"), default=30)
    cleanup_batch = _coerce_int(os.getenv("SENTIMENT_QUEUE_CLEANUP_BATCH"), default=250)
    if cleanup_days > 0 and cleanup_batch > 0:
        removed = _cleanup_completed_items(
            get_conn=_get_db_connection,
            older_than_days=cleanup_days,
            batch_limit=cleanup_batch,
            logger=logger,
        )
        if removed:
            logger.info(
                "Queue cleanup: removed %s completed items older than %s days",
                removed,
                cleanup_days,
            )

    if update_queue_depth_metrics is not None:
        try:
            update_queue_depth_metrics(_get_db_connection)
        except Exception:
            pass

    return processed


def _coerce_int(value: Optional[str | int], default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_raw_context(
    get_conn: Callable[[], psycopg2.extensions.connection],
    raw_id,
) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT body_text, published_at, source_domain, title, url_canonical
                    FROM rankalpha.fact_news_raw
                    WHERE raw_id = %s
                    """,
                    (raw_id,),
                )
                row = cur.fetchone()
    except Exception as exc:
        get_logger(__name__).warning("Queue: failed to load raw context for %s: %s", raw_id, exc)
        return None
    if not row:
        return None
    body_text, published_at, source_domain, title, url = row
    published_iso: Optional[str] = None
    if isinstance(published_at, datetime):
        try:
            aware = published_at
            if aware.tzinfo is None:
                aware = aware.replace(tzinfo=timezone.utc)
            published_iso = aware.astimezone(timezone.utc).isoformat()
        except Exception:
            published_iso = published_at.isoformat()
    return body_text, published_iso, source_domain, title, url


def _fetch_last_analysis_load_ts(
    get_conn: Callable[[], psycopg2.extensions.connection],
    stock_key: int,
) -> Optional[datetime]:
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
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
    except Exception:
        return None
    finally:
        if cur is not None:
            with contextlib.suppress(Exception):
                cur.close()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


def _days_since_load(load_ts: datetime) -> int:
    try:
        delta = datetime.now(timezone.utc) - load_ts.astimezone(timezone.utc)
        return max(delta.days, 0)
    except Exception:
        return 0


def _defer_queue_item(
    qid: Any,
    get_conn: Callable[[], psycopg2.extensions.connection],
    *,
    defer_days: int,
    attempts_modifier: int,
    logger: Any,
    symbol: str,
    source: Optional[str],
) -> None:
    conn = None
    cur = None
    try:
        next_run_ts = datetime.now(timezone.utc) + timedelta(days=defer_days)
        next_run_date = next_run_ts.date()
        conn = get_conn()
        cur = conn.cursor()
        # Conflict-aware deferral: only move if no same/earlier pending exists for this stock/date.
        cur.execute(
            """
            WITH target AS (
              SELECT %s::date AS d
            )
            UPDATE rankalpha.sentiment_analysis_queue saq
            SET status='pending',
                run_after_ts=(SELECT d FROM target),
                attempts=GREATEST(attempts + %s, 0)
            WHERE saq.queue_id=%s
              AND NOT EXISTS (
                SELECT 1 FROM rankalpha.sentiment_analysis_queue s
                WHERE s.stock_key = saq.stock_key
                  AND s.queue_id <> saq.queue_id
                  AND s.event_id IS NULL
                  AND s.status IN ('pending','in_progress')
                  AND s.run_after_date <= (SELECT d FROM target)
              )
            RETURNING saq.queue_id
            """,
            (next_run_date.strftime("%Y-%m-%d"), attempts_modifier, qid),
        )
        updated = cur.fetchone()
        if updated is None:
            # A same/earlier pending exists; mark this row done and skip requeue
            cur.execute(
                "UPDATE rankalpha.sentiment_analysis_queue SET status='done', completed_ts=now() WHERE queue_id=%s",
                (qid,),
            )
            conn.commit()
            logger.info(
                f"Queue skip {symbol}: recency guard active; existing earlier/same-day item covers target; marking done (source={source or 'queue'})"
            )
        else:
            conn.commit()
            logger.info(
                f"Queue skip {symbol}: recency guard active; requeued for {next_run_ts.isoformat()} (source={source or 'queue'})"
            )
    except Exception as exc:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.rollback()
        logger.error(f"Queue: failed to defer recency-skipped item qid={qid}: {exc}")
    finally:
        if cur is not None:
            with contextlib.suppress(Exception):
                cur.close()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


def _update_queue_row(
    *,
    qid: Any,
    success: bool,
    max_attempts: int,
    backoff_base: int,
    get_conn: Callable[[], psycopg2.extensions.connection],
    logger: Any,
) -> None:
    conn = None
    cur = None
    try:
        conn = get_conn()
        cur = conn.cursor()
        if success:
            cur.execute(
                "UPDATE rankalpha.sentiment_analysis_queue SET status='done', completed_ts=now() WHERE queue_id=%s",
                (qid,),
            )
        else:
            cur.execute(
                "SELECT attempts FROM rankalpha.sentiment_analysis_queue WHERE queue_id=%s",
                (qid,),
            )
            row = cur.fetchone()
            attempts = int(row[0] or 1) if row else 1
            if attempts >= max_attempts:
                cur.execute(
                    "UPDATE rankalpha.sentiment_analysis_queue SET status='failed' WHERE queue_id=%s",
                    (qid,),
                )
            else:
                delay = backoff_base * (2 ** max(0, attempts - 1))
                cur.execute(
                    """
                    UPDATE rankalpha.sentiment_analysis_queue
                    SET status='pending',
                        run_after_ts = now() + make_interval(secs => %s)
                    WHERE queue_id=%s
                    """,
                    (int(delay), qid),
                )
        conn.commit()
    except Exception as exc:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.rollback()
        logger.error(f"Queue: failed to update status for qid={qid}: {exc}")
    finally:
        if cur is not None:
            with contextlib.suppress(Exception):
                cur.close()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


def _cleanup_completed_items(
    *,
    get_conn: Callable[[], psycopg2.extensions.connection],
    older_than_days: int,
    batch_limit: int,
    logger: Any,
) -> int:
    conn = None
    cur = None
    removed = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            WITH stale AS (
                SELECT queue_id
                FROM rankalpha.sentiment_analysis_queue
                WHERE status = 'done'
                  AND completed_ts IS NOT NULL
                  AND completed_ts < %s
                ORDER BY completed_ts ASC
                LIMIT %s
            )
            DELETE FROM rankalpha.sentiment_analysis_queue saq
            USING stale
            WHERE saq.queue_id = stale.queue_id
            RETURNING saq.queue_id
            """,
            (cutoff, int(batch_limit)),
        )
        removed = cur.rowcount or 0
        conn.commit()
    except Exception as exc:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.rollback()
        logger.error("Queue cleanup failed: %s", exc)
    finally:
        if cur is not None:
            with contextlib.suppress(Exception):
                cur.close()
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    return int(removed)
