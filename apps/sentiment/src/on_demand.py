from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

try:  # Prefer package-relative imports
    from .schedule_manager import update_schedule_with_catalysts  # type: ignore[import]
except ImportError:
    from schedule_manager import update_schedule_with_catalysts  # type: ignore[import]

logger = get_logger(__name__)


async def handle_on_demand(
    analyzer_app: Any,
    *,
    settings: Settings,
    connection_factory,
    symbol: str,
    force: bool,
    schedule_file: Path,
    ai_analysis: Callable[..., Awaitable[bool]],
    already_completed_today: Callable[[int], bool],
    mark_completed_today: Callable[[int], None],
):
    """Handle the on-demand CLI workflow for a single symbol."""

    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stock_key, company_name FROM rankalpha.dim_stock WHERE symbol = %s AND is_active IS TRUE",
                (symbol,),
            )
            row = cur.fetchone()
        conn.close()
    except Exception as exc:
        conn.close()
        logger.error(f"Database error looking up {symbol}: {exc}")
        return

    if not row:
        logger.error(f"Symbol not found in dim_stock: {symbol}")
        return

    stock_key, company_name = int(row[0]), row[1]

    if not force:
        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT load_ts
                    FROM rankalpha.fact_ai_stock_analysis
                    WHERE stock_key = %s
                    ORDER BY load_ts DESC NULLS LAST, date_key DESC
                    LIMIT 1
                    """,
                    (stock_key,),
                )
                last = cur.fetchone()
        finally:
            conn.close()

        if last and last[0]:
            try:
                skip_window = int(getattr(settings, "sentiment_skip_if_within_days", 1) or 1)
            except Exception:
                skip_window = 1
            try:
                last_ts = last[0]
                if isinstance(last_ts, datetime):
                    aware = (
                        last_ts
                        if last_ts.tzinfo is not None
                        else last_ts.replace(tzinfo=timezone.utc)
                    )
                    delta_days = max((datetime.now(timezone.utc) - aware).days, 0)
                else:
                    delta_days = 0
            except Exception:
                delta_days = 0
            if delta_days < max(skip_window, 1):
                logger.info(
                    f"Skipping {symbol}: last analysis {delta_days} days ago (< {skip_window}d). Use --force to override."
                )
                return

    if (not force) and already_completed_today(stock_key):
        logger.info(
            f"Skipping on-demand for {company_name} ({symbol}): already completed today in this run"
        )
        return

    logger.info(
        f"Running on-demand analysis for {company_name} ({symbol}){' with --force' if force else ''}"
    )
    try:
        success = await ai_analysis(
            company_name,
            analyzer_app,
            symbol,
            trigger="on_demand",
        )
    except asyncio.TimeoutError:  # type: ignore[name-defined]
        logger.warning("On-demand analysis timed out; not retrying")
        return

    if not success:
        try:
            success = await ai_analysis(
                company_name,
                analyzer_app,
                symbol,
                trigger="on_demand",
            )
        except asyncio.TimeoutError:  # type: ignore[name-defined]
            logger.warning("On-demand retry timed out; aborting")
            return
    if not success:
        return

    conn = connection_factory()
    try:
        with conn.cursor() as cur:
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
                update_schedule_with_catalysts(
                    schedule_file,
                    str(stock_key),
                    company_name,
                    symbol,
                    new_analysis[0],
                    cur,
                )
                conn.commit()
    finally:
        conn.close()

    mark_completed_today(stock_key)
