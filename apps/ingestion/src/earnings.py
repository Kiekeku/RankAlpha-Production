"""Finnhub earnings calendar integration for ingestion."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional

import requests
from prometheus_client import Counter

from apps.ingestion.src.settings import Settings

EARNINGS_REFRESH = Counter(
    "rankalpha_ingestion_earnings_refresh_total",
    "Count of Finnhub earnings refresh attempts grouped by status.",
    ["status"],
)
EARNINGS_UPDATED = Counter(
    "rankalpha_ingestion_earnings_updated_symbols_total",
    "Number of symbol earnings entries inserted or updated.",
)


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    earnings_date: date
    earnings_time: Optional[str]


class FinnhubClient:
    """Minimal Finnhub client for earnings calendar calls."""

    BASE_URL = "https://finnhub.io/api/v1/calendar/earnings"

    def __init__(self, api_key: str, logger, *, session: Optional[requests.Session] = None) -> None:
        self._api_key = api_key
        self._logger = logger
        self._session = session or requests.Session()
        self._timeout = 10
        self._max_retries = 3

    def fetch_calendar(self, start: date, end: date) -> List[EarningsEvent]:
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "token": self._api_key,
        }
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(self.BASE_URL, params=params, timeout=self._timeout)
                if resp.status_code == 429:
                    sleep_for = 2 * (attempt + 1)
                    self._logger.warning(
                        "Finnhub earnings calendar rate limited; retrying in %s seconds", sleep_for
                    )
                    time.sleep(sleep_for)
                    continue
                resp.raise_for_status()
                payload = resp.json() or {}
                items = payload.get("earningsCalendar") or []
                events: List[EarningsEvent] = []
                for item in items:
                    sym = str(item.get("symbol") or "").strip().upper()
                    date_str = item.get("date")
                    if not sym or not date_str:
                        continue
                    try:
                        earnings_dt = date.fromisoformat(str(date_str))
                    except Exception:
                        continue
                    hour = item.get("hour")
                    if isinstance(hour, str):
                        hour_val: Optional[str] = hour.strip() or None
                    else:
                        hour_val = None
                    events.append(
                        EarningsEvent(symbol=sym, earnings_date=earnings_dt, earnings_time=hour_val)
                    )
                return events
            except Exception as exc:  # pragma: no cover - network failure logging
                last_exc = exc
                self._logger.warning(
                    "Finnhub earnings fetch failed (attempt %s/%s): %s",
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                time.sleep(2 * (attempt + 1))
        if last_exc:
            raise last_exc
        return []


class EarningsCalendarUpdater:
    """Coordinates Finnhub earnings refresh and database upsert."""

    def __init__(
        self,
        settings: Settings,
        db_factory,
        logger,
    ) -> None:
        self._settings = settings
        self._db_factory = db_factory
        self._logger = logger
        api_key = getattr(settings, "finnhub_key", None)
        self._client: Optional[FinnhubClient] = FinnhubClient(api_key, logger) if api_key else None

    def refresh(self) -> None:
        if not getattr(self._settings, "ingestion_fetch_earnings", True):
            self._logger.info("Finnhub earnings refresh disabled via settings; skipping")
            return
        if not self._client:
            self._logger.info("Finnhub API key not configured; skipping earnings refresh")
            return
        window_days = int(getattr(self._settings, "ingestion_earnings_window_days", 7) or 7)
        window_days = max(window_days, 1)
        start = date.today()
        end = start + timedelta(days=window_days - 1)

        status = "success"
        try:
            events = self._client.fetch_calendar(start, end)
            symbol_events = self._select_next_event(events)
            updated = self._upsert_events(symbol_events)
            self._purge_stale(start)
            EARNINGS_UPDATED.inc(updated)
            self._logger.info(
                "Earnings calendar refresh complete. window=%s updated=%s", window_days, updated
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            status = "error"
            self._logger.error("Earnings calendar refresh failed: %s", exc)
            raise
        finally:
            EARNINGS_REFRESH.labels(status=status).inc()

    def _select_next_event(self, events: Iterable[EarningsEvent]) -> Dict[str, EarningsEvent]:
        upcoming: Dict[str, EarningsEvent] = {}
        today = date.today()
        for event in events:
            if event.earnings_date < today:
                continue
            existing = upcoming.get(event.symbol)
            if not existing or event.earnings_date < existing.earnings_date:
                upcoming[event.symbol] = event
        return upcoming

    def _upsert_events(self, events: Dict[str, EarningsEvent]) -> int:
        if not events:
            return 0
        conn = self._db_factory()
        updated = 0
        try:
            symbol_to_key = self._load_stock_map(conn)
            rows = []
            for symbol, event in events.items():
                stock_key = symbol_to_key.get(symbol)
                if not stock_key:
                    continue
                rows.append((stock_key, event.earnings_date, event.earnings_time, "finnhub"))
            if not rows:
                return 0
            cur = conn.cursor()
            try:
                from psycopg2.extras import execute_values

                execute_values(
                    cur,
                    """
                    INSERT INTO rankalpha.fact_stock_next_earnings (stock_key, earnings_date, earnings_time, earnings_source)
                    VALUES %s
                    ON CONFLICT (stock_key) DO UPDATE SET
                        earnings_date = EXCLUDED.earnings_date,
                        earnings_time = EXCLUDED.earnings_time,
                        earnings_source = EXCLUDED.earnings_source,
                        load_ts = now()
                    """,
                    rows,
                    template="(%s, %s, %s, %s)",
                    page_size=500,
                )
                updated = len(rows)
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()
        return updated

    def _purge_stale(self, start: date) -> None:
        conn = self._db_factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM rankalpha.fact_stock_next_earnings WHERE earnings_date < %s",
                    (start,),
                )
                if cur.rowcount:
                    self._logger.info("Pruned %s stale earnings rows", cur.rowcount)
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()

    def _load_stock_map(self, conn) -> Dict[str, int]:
        cur = conn.cursor()
        try:
            cur.execute("SELECT stock_key, symbol FROM dim_stock")
            rows = cur.fetchall()
            return {str(symbol).upper(): int(stock_key) for stock_key, symbol in rows if symbol}
        finally:
            cur.close()
