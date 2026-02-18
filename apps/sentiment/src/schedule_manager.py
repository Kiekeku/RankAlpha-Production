from __future__ import annotations

import contextlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from apps.common.src.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - platform-specific
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore


def _load_schedule_unlocked(schedule_file: Path) -> Dict[str, Any]:
    if not schedule_file.exists():
        return {}
    with schedule_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    for stock_key, info in data.items():
        info["analysis_dates"] = [
            datetime.strptime(day_str, "%Y-%m-%d").date()
            for day_str in info.get("analysis_dates", [])
        ]
    return data


def _save_schedule_unlocked(schedule_file: Path, schedule: Dict[str, Any]) -> None:
    serialisable: Dict[str, Any] = {}
    for stock_key, info in schedule.items():
        unique_dates = sorted(set(info.get("analysis_dates", [])))
        serialisable[stock_key] = {
            "company_name": info.get("company_name"),
            "symbol": info.get("symbol"),
            "analysis_dates": [
                day.strftime("%Y-%m-%d") if hasattr(day, "strftime") else str(day)
                for day in unique_dates
            ],
        }

    schedule_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{schedule_file.name}.",
        suffix=".tmp",
        dir=str(schedule_file.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(serialisable, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, schedule_file)
    except Exception:
        with contextlib.suppress(Exception):
            os.unlink(tmp_path)
        raise


@contextmanager
def _schedule_lock(schedule_file: Path):
    lock_path = schedule_file.with_suffix(f"{schedule_file.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_schedule(schedule_file: Path) -> Dict[str, Any]:
    """Load the analysis schedule from JSON file."""
    try:
        with _schedule_lock(schedule_file):
            return _load_schedule_unlocked(schedule_file)
    except Exception as exc:
        logger.error(f"Error loading schedule from {schedule_file}: {exc}")
        return {}


def save_schedule(schedule_file: Path, schedule: Dict[str, Any]) -> None:
    """Persist the analysis schedule to disk with date de-duplication."""
    try:
        with _schedule_lock(schedule_file):
            _save_schedule_unlocked(schedule_file, schedule)
    except Exception as exc:
        logger.error(f"Error saving schedule to {schedule_file}: {exc}")


def clean_schedule(schedule_file: Path) -> Dict[str, Any]:
    """Remove duplicate entries per stock and persist changes."""
    try:
        with _schedule_lock(schedule_file):
            schedule = _load_schedule_unlocked(schedule_file)
            cleaned = False
            for stock_key, info in schedule.items():
                original = len(info.get("analysis_dates", []))
                unique_dates = []
                seen = set()
                for dt in info.get("analysis_dates", []):
                    if dt not in seen:
                        unique_dates.append(dt)
                        seen.add(dt)
                if original != len(unique_dates):
                    logger.info(
                        f"Cleaned schedule for {info.get('symbol', stock_key)}: removed {original - len(unique_dates)} duplicates"
                    )
                    info["analysis_dates"] = unique_dates
                    cleaned = True
            if cleaned:
                _save_schedule_unlocked(schedule_file, schedule)
                logger.info("Schedule cleaned and saved")
            return schedule
    except Exception as exc:
        logger.error(f"Error cleaning schedule {schedule_file}: {exc}")
        return {}


def remove_date_from_schedule(schedule_file: Path, stock_key_str: str, target_date: date) -> None:
    """Remove a specific date from the schedule for a stock, if present."""
    try:
        with _schedule_lock(schedule_file):
            schedule = _load_schedule_unlocked(schedule_file)
            if stock_key_str not in schedule:
                return
            dates = schedule[stock_key_str].get("analysis_dates", [])
            new_dates = [d for d in dates if d != target_date]
            if len(new_dates) != len(dates):
                schedule[stock_key_str]["analysis_dates"] = new_dates
                _save_schedule_unlocked(schedule_file, schedule)
    except Exception as exc:
        logger.error(f"Failed to remove schedule date for stock_key={stock_key_str}: {exc}")


def update_queue_with_catalysts(db_conn, stock_key: int, analysis_id: Any) -> int:
    """Insert future queue items based on catalyst expected dates for a given analysis_id."""
    cur = db_conn.cursor()
    try:
        cur.execute(
            "SELECT expected_date FROM rankalpha.fact_ai_catalyst WHERE analysis_id = %s AND expected_date IS NOT NULL",
            (analysis_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return 0
        today = datetime.now().date()
        dates = set()
        for (expected,) in rows:
            if not expected:
                continue
            for delta in (-7, 1, 7):
                candidate = expected + timedelta(days=delta)
                if candidate >= today:
                    dates.add(candidate)
        if not dates:
            return 0
        for run_date in sorted(dates):
            cur.execute(
                """
                INSERT INTO rankalpha.sentiment_analysis_queue (stock_key, symbol, run_after_ts, priority, status, source, force_run)
                SELECT ds.stock_key, ds.symbol, %s::date, 0, 'pending', 'schedule', FALSE
                FROM rankalpha.dim_stock ds
                WHERE ds.stock_key = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM rankalpha.sentiment_analysis_queue s
                    WHERE s.stock_key = ds.stock_key
                      AND s.event_id IS NULL
                      AND s.status IN ('pending','in_progress')
                      AND s.run_after_date <= %s::date
                  )
                ON CONFLICT DO NOTHING
                """,
                (run_date.strftime("%Y-%m-%d"), int(stock_key), run_date.strftime("%Y-%m-%d")),
            )
        db_conn.commit()
        logger.info(f"Queue: added {len(dates)} future items for stock_key={stock_key}")
        return len(dates)
    except Exception as exc:
        with contextlib.suppress(Exception):
            db_conn.rollback()
        logger.error(f"Queue: failed to add catalyst dates for stock_key={stock_key}: {exc}")
        return 0
    finally:
        with contextlib.suppress(Exception):
            cur.close()


def update_schedule_with_catalysts(
    schedule_file: Path,
    stock_key: str,
    company_name: str,
    symbol: str,
    analysis_id: Any,
    cursor,
) -> int:
    """Update the JSON schedule with catalyst-driven analysis dates."""
    cursor.execute(
        "SELECT expected_date FROM rankalpha.fact_ai_catalyst WHERE analysis_id = %s AND expected_date IS NOT NULL",
        (analysis_id,),
    )
    rows = cursor.fetchall()
    if not rows:
        return 0

    today = datetime.now().date()
    new_dates = set()
    for (expected,) in rows:
        if not expected:
            continue
        for delta in (-7, 1, 7):
            candidate = expected + timedelta(days=delta)
            if candidate >= today:
                new_dates.add(candidate)
    if not new_dates:
        return 0

    try:
        with _schedule_lock(schedule_file):
            schedule = _load_schedule_unlocked(schedule_file)
            entry = schedule.setdefault(
                stock_key,
                {
                    "company_name": company_name,
                    "symbol": symbol,
                    "analysis_dates": [],
                },
            )
            # Merge and deduplicate
            existing_dates = set(entry.get("analysis_dates", []))
            added = False
            for dt in new_dates:
                if dt not in existing_dates:
                    entry.setdefault("analysis_dates", []).append(dt)
                    added = True
            if added:
                _save_schedule_unlocked(schedule_file, schedule)
                logger.info(
                    f"Schedule: added {len(new_dates)} catalyst-derived dates for stock_key={stock_key} ({symbol})"
                )
    except Exception as exc:
        logger.error(
            "Schedule: failed catalyst update for stock_key=%s (%s): %s",
            stock_key,
            symbol,
            exc,
        )
        return 0
    return len(new_dates)
