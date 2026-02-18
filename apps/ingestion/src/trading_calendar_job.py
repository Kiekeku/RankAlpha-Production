from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Iterable, Optional

import psycopg2
from psycopg2.extras import execute_values

from apps.common.src.logging import get_logger

try:
    from apps.broker.tradeexec.utils.market_calendar import (  # type: ignore
        is_trading_day as _is_trading_day,
    )
except Exception:  # pragma: no cover - fallback for minimal environments

    def _observed(dt: date) -> date:
        if dt.weekday() == 5:  # Saturday -> observed Friday
            return dt - timedelta(days=1)
        if dt.weekday() == 6:  # Sunday -> observed Monday
            return dt + timedelta(days=1)
        return dt

    def _good_friday(year: int) -> date:
        # Meeus/Jones/Butcher algorithm for Easter Sunday, then minus 2 days
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        ell = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * ell) // 451
        month = (h + ell - 7 * m + 114) // 31
        day = ((h + ell - 7 * m + 114) % 31) + 1
        easter = date(year, month, day)
        return easter - timedelta(days=2)

    def _is_us_equity_holiday(d: date) -> bool:
        y = d.year
        if d == _observed(date(y, 1, 1)):
            return True  # New Year
        if d == _observed(date(y, 6, 19)):
            return True  # Juneteenth
        if d == _observed(date(y, 7, 4)):
            return True  # Independence Day
        if d == _observed(date(y, 12, 25)):
            return True  # Christmas

        if d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21:
            return True  # MLK Day
        if d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21:
            return True  # Presidents' Day
        if d.month == 5 and d.weekday() == 0 and d.day + 7 > 31:
            return True  # Memorial Day
        if d.month == 9 and d.weekday() == 0 and 1 <= d.day <= 7:
            return True  # Labor Day

        if d == _good_friday(y):
            return True

        if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:
            return True  # Thanksgiving

        return False

    def _is_trading_day(d: date) -> bool:
        return d.weekday() < 5 and not _is_us_equity_holiday(d)


class TradingCalendarJob:
    """Updates dim_date.is_trading_day with US equity holiday logic."""

    def __init__(
        self,
        db_factory: Callable[[], psycopg2.extensions.connection],
        logger=None,
    ) -> None:
        self._db_factory = db_factory
        self._logger = logger or get_logger(__name__)

    def refresh(self, *, start_date: Optional[date] = None, end_date: Optional[date] = None) -> int:
        conn = self._db_factory()
        try:
            start, end = self._resolve_range(conn, start_date, end_date)
            if start is None or end is None or start > end:
                return 0
            payload = [(d, _is_trading_day(d)) for d in self._iter_dates(start, end)]
            if not payload:
                return 0
            cur = conn.cursor()
            try:
                execute_values(
                    cur,
                    """
                    UPDATE rankalpha.dim_date AS d
                    SET is_trading_day = v.is_trading_day
                    FROM (VALUES %s) AS v(full_date, is_trading_day)
                    WHERE d.full_date = v.full_date
                    """,
                    payload,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
            self._logger.info(
                "Trading calendar updated: %d row(s) %s -> %s",
                len(payload),
                start.isoformat(),
                end.isoformat(),
            )
            return len(payload)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _resolve_range(
        self,
        conn: psycopg2.extensions.connection,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> tuple[Optional[date], Optional[date]]:
        if start_date is not None and end_date is not None:
            return start_date, end_date
        cur = conn.cursor()
        try:
            cur.execute("SELECT MIN(full_date), MAX(full_date) FROM rankalpha.dim_date")
            row = cur.fetchone() if cur else None
            db_start = row[0] if row else None
            db_end = row[1] if row else None
        finally:
            cur.close()
        start = start_date or db_start
        end = end_date or db_end
        return start, end

    def _iter_dates(self, start: date, end: date) -> Iterable[date]:
        current = start
        while current <= end:
            yield current
            current += timedelta(days=1)
