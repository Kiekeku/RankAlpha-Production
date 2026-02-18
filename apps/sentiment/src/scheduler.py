from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

try:
    from .queue_worker import consume_queue_items  # type: ignore[import]
    from .schedule_manager import (  # type: ignore[import]
        load_schedule,
        remove_date_from_schedule,
        update_queue_with_catalysts,
        update_schedule_with_catalysts,
    )
except ImportError:
    from queue_worker import consume_queue_items  # type: ignore[import]
    from schedule_manager import (  # type: ignore[import]
        load_schedule,
        remove_date_from_schedule,
        update_queue_with_catalysts,
        update_schedule_with_catalysts,
    )

logger = get_logger(__name__)


async def run_scheduled_analyses(
    analyzer_app: Any,
    *,
    settings: Settings,
    connection_factory,
    ai_analysis: Callable[..., Awaitable[bool]],
    schedule_file,
    already_completed_today: Callable[[int], bool],
    mark_completed_today: Callable[[int], None],
) -> None:
    try:
        max_q = int(os.getenv("SENTIMENT_QUEUE_MAX", "5") or 5)
    except Exception:
        max_q = 5

    try:
        qn = await consume_queue_items(
            analyzer_app,
            ai_analysis,
            max_items=max_q,
            settings=settings,
            already_completed_today=already_completed_today,
            mark_completed_today=mark_completed_today,
            connection_factory=connection_factory,
        )
        if qn:
            logger.info("Queue: processed %s queued analyses before schedule checks", qn)
    except Exception as exc:
        logger.error(f"Queue: error in pre-schedule consumption: {exc}")

    if str(os.getenv("SENTIMENT_SCHEDULE_MODE", "queue")).lower() == "queue":
        return

    schedule = load_schedule(schedule_file)
    current_date = datetime.now().date()

    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ds.stock_key, ds.company_name, ds.symbol,
                       CASE WHEN fasa.stock_key IS NULL THEN 0 ELSE 1 END AS has_analysis
                FROM rankalpha.dim_stock ds
                JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
                LEFT JOIN (SELECT DISTINCT stock_key FROM rankalpha.fact_ai_stock_analysis) fasa
                  ON ds.stock_key = fasa.stock_key
                WHERE ds.is_active IS TRUE
                ORDER BY has_analysis ASC, ds.company_name ASC
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    stocks = [(int(row[0]), row[1], row[2], bool(row[3])) for row in rows]

    stocks_without_analysis = sum(1 for _, _, _, has in stocks if not has)
    logger.info(
        "Found %s total stocks, %s without analysis (will be processed first)",
        len(stocks),
        stocks_without_analysis,
    )

    processed_count = 0
    skipped_recent = 0
    try:
        max_analyses_cap = int(getattr(settings, "sentiment_max_analyses", 0) or 0)
    except Exception:
        max_analyses_cap = 0
    if max_analyses_cap > 0:
        logger.info("Analyses cap active: SENTIMENT_MAX_ANALYSES=%s", max_analyses_cap)

    def fetch_latest_analysis(stock_key: int):
        conn_local = connection_factory()
        try:
            with conn_local.cursor() as cur:
                cur.execute(
                    """
                    SELECT analysis_id, load_ts
                    FROM rankalpha.fact_ai_stock_analysis
                    WHERE stock_key = %s
                    ORDER BY load_ts DESC NULLS LAST, date_key DESC
                    LIMIT 1
                    """,
                    (stock_key,),
                )
                return cur.fetchone()
        finally:
            conn_local.close()

    def fetch_last_load(stock_key: int):
        conn_local = connection_factory()
        try:
            with conn_local.cursor() as cur:
                cur.execute(
                    "SELECT MAX(load_ts) FROM rankalpha.fact_ai_stock_analysis WHERE stock_key = %s",
                    (stock_key,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        finally:
            conn_local.close()

    def _days_since_load(ts: datetime) -> int:
        try:
            if isinstance(ts, datetime):
                aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
                return max((datetime.now(timezone.utc) - aware).days, 0)
        except Exception:
            pass
        return 0

    for stock_key, company_name, stock_symbol, has_analysis in stocks:
        if max_analyses_cap > 0 and processed_count >= max_analyses_cap:
            logger.info(
                "Reached analyses cap (%s/%s); stopping scheduled run",
                processed_count,
                max_analyses_cap,
            )
            break

        stock_key_str = str(stock_key)
        if already_completed_today(stock_key):
            logger.info(
                "Skipping %s (%s): already completed today in this run",
                company_name,
                stock_symbol,
            )
            continue

        latest = fetch_latest_analysis(stock_key) if has_analysis else None

        if latest is None:
            logger.info(
                "🚀 PRIORITY: No analysis found for %s (%s) - running immediate initial analysis",
                company_name,
                stock_symbol,
            )
            try:
                success = await ai_analysis(
                    company_name,
                    analyzer_app,
                    stock_symbol,
                    trigger="schedule",
                )
            except asyncio.TimeoutError:  # type: ignore[name-defined]
                logger.warning(
                    "Initial analysis timed out for %s (%s); skipping retries",
                    company_name,
                    stock_symbol,
                )
                success = False

            if success:
                conn_local = connection_factory()
                try:
                    with conn_local.cursor() as cur:
                        cur.execute(
                            """
                            SELECT analysis_id
                            FROM rankalpha.fact_ai_stock_analysis
                            WHERE stock_key = %s
                            ORDER BY load_ts DESC NULLS LAST, date_key DESC
                            LIMIT 1
                            """,
                            (stock_key,),
                        )
                        row = cur.fetchone()
                        if row:
                            update_schedule_with_catalysts(
                                schedule_file,
                                stock_key_str,
                                company_name,
                                stock_symbol,
                                row[0],
                                cur,
                            )
                            conn_local.commit()
                            schedule = load_schedule(schedule_file)
                finally:
                    conn_local.close()
                mark_completed_today(stock_key)
                processed_count += 1
            continue

        analysis_id, last_load_ts = latest

        if stock_key_str not in schedule:
            if str(os.getenv("SENTIMENT_SCHEDULE_MODE", "queue")).lower() == "queue":
                conn_local = connection_factory()
                try:
                    update_queue_with_catalysts(conn_local, stock_key, analysis_id)
                finally:
                    conn_local.close()
            else:
                conn_local = connection_factory()
                try:
                    with conn_local.cursor() as cur:
                        update_schedule_with_catalysts(
                            schedule_file,
                            stock_key_str,
                            company_name,
                            stock_symbol,
                            analysis_id,
                            cur,
                        )
                        conn_local.commit()
                        schedule = load_schedule(schedule_file)
                finally:
                    conn_local.close()
            logger.info(
                "Initialized schedule from catalysts for %s (%s)", company_name, stock_symbol
            )
            continue

        scheduled_dates = schedule[stock_key_str].get("analysis_dates", [])
        if current_date not in scheduled_dates:
            continue

        try:
            skip_window = int(getattr(settings, "sentiment_skip_if_within_days", 1) or 1)
        except Exception:
            skip_window = 1

        last_load_ts = last_load_ts or fetch_last_load(stock_key)
        if last_load_ts:
            delta_days = _days_since_load(last_load_ts)
            if 0 <= delta_days < max(skip_window, 1):
                logger.info(
                    "Skipping scheduled analysis for %s (%s): last run %s days ago (< %sd)",
                    company_name,
                    stock_symbol,
                    delta_days,
                    max(skip_window, 1),
                )
                remove_date_from_schedule(schedule_file, stock_key_str, current_date)
                schedule = load_schedule(schedule_file)
                skipped_recent += 1
                continue

        try:
            success = await ai_analysis(
                company_name,
                analyzer_app,
                stock_symbol,
                trigger="schedule",
            )
        except asyncio.TimeoutError:  # type: ignore[name-defined]
            logger.warning(
                "Scheduled analysis timed out for %s (%s); skipping",
                company_name,
                stock_symbol,
            )
            success = False

        if not success:
            continue

        conn_local = connection_factory()
        try:
            with conn_local.cursor() as cur:
                cur.execute(
                    """
                    SELECT analysis_id
                    FROM rankalpha.fact_ai_stock_analysis
                    WHERE stock_key = %s
                    ORDER BY load_ts DESC NULLS LAST, date_key DESC
                    LIMIT 1
                    """,
                    (stock_key,),
                )
                new_analysis = cur.fetchone()
                if new_analysis:
                    if str(os.getenv("SENTIMENT_SCHEDULE_MODE", "queue")).lower() == "queue":
                        conn_tmp = connection_factory()
                        try:
                            update_queue_with_catalysts(conn_tmp, stock_key, new_analysis[0])
                        finally:
                            conn_tmp.close()
                    else:
                        update_schedule_with_catalysts(
                            schedule_file,
                            stock_key_str,
                            company_name,
                            stock_symbol,
                            new_analysis[0],
                            cur,
                        )
                        schedule = load_schedule(schedule_file)
            conn_local.commit()
        finally:
            conn_local.close()

        remove_date_from_schedule(schedule_file, stock_key_str, current_date)
        schedule = load_schedule(schedule_file)
        mark_completed_today(stock_key)
        processed_count += 1

    try:
        logger.info(
            "Scheduled check summary: processed=%s, skipped_recent=%s, total_stocks=%s",
            processed_count,
            skipped_recent,
            len(stocks),
        )
    except Exception:
        pass
