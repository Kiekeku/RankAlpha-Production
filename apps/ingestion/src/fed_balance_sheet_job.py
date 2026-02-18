"""Fetch Federal Reserve balance sheet series from FRED.

This ingests a small set of Fed balance sheet / SOMA composition series into:
- rankalpha.dim_macro_series
- rankalpha.fact_macro_series

Series are pulled from the FRED JSON API.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List, Optional, Tuple

import psycopg2
import requests
from psycopg2.extras import execute_values

from apps.common.src.logging import get_logger

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass(frozen=True)
class FredSeries:
    fred_id: str
    series_code: str
    series_name: str
    category: str
    frequency: str
    units: str
    description: str


SERIES: Tuple[FredSeries, ...] = (
    FredSeries(
        fred_id="WALCL",
        series_code="US_FED_WALCL",
        series_name="Federal Reserve Total Assets (WALCL)",
        category="liquidity",
        frequency="W",
        units="millions_usd",
        description="FRED WALCL (Total Assets, Less Eliminations from Consolidation)",
    ),
    FredSeries(
        fred_id="WSHOSHO",
        series_code="US_FED_WSHOSHO",
        series_name="SOMA Securities Held Outright (WSHOSHO)",
        category="liquidity",
        frequency="W",
        units="millions_usd",
        description="FRED WSHOSHO (Securities Held Outright: System Open Market Account) used as a SOMA proxy",
    ),
    FredSeries(
        fred_id="TREAST",
        series_code="US_FED_TREAST",
        series_name="SOMA Treasury Securities Held Outright (TREAST)",
        category="liquidity",
        frequency="W",
        units="millions_usd",
        description="FRED TREAST (Treasury Securities Held Outright: System Open Market Account)",
    ),
    FredSeries(
        fred_id="MBST",
        series_code="US_FED_MBST",
        series_name="SOMA Mortgage-Backed Securities Held Outright (MBST)",
        category="liquidity",
        frequency="W",
        units="millions_usd",
        description="FRED MBST (Mortgage-Backed Securities Held Outright: System Open Market Account)",
    ),
)


class FedBalanceSheetJob:
    """Pulls Fed balance sheet series from FRED into fact_macro_series."""

    def __init__(self, settings, logger=None, db_factory=None) -> None:
        if psycopg2 is None or execute_values is None:  # pragma: no cover - defensive
            raise RuntimeError("psycopg2 is required for FedBalanceSheetJob")
        self._settings = settings
        self._logger = logger or get_logger(__name__)
        self._db_factory = db_factory
        self._api_key = getattr(settings, "fred_api_key", None) or os.getenv("FRED_API_KEY")
        self._lookback_days = self._resolve_lookback_days()

    def refresh(self, *, as_of: Optional[date] = None) -> None:
        enabled = bool(getattr(self._settings, "ingestion_fed_balance_sheet_enabled", True))
        if not enabled:
            self._logger.info(
                "Fed balance sheet job disabled via INGESTION_FED_BALANCE_SHEET_ENABLED; skipping"
            )
            return
        if not self._api_key:
            self._logger.warning("Fed balance sheet job skipped: FRED_API_KEY is not set")
            return

        conn = self._db_factory()
        try:
            source_key = self._ensure_source(conn)
            for meta in SERIES:
                series_key = self._ensure_dim_series(conn, meta)
                latest_date = self._latest_fact_date(conn, series_key)
                if latest_date:
                    if self._lookback_days > 0:
                        start = latest_date - timedelta(days=self._lookback_days)
                    else:
                        start = latest_date + timedelta(days=1)
                else:
                    start = None
                rows = self._fetch_fred(meta.fred_id, start_date=start, end_date=as_of)
                if not rows:
                    self._logger.info(
                        "Fed balance sheet: no new data for %s (latest=%s)",
                        meta.series_code,
                        latest_date,
                    )
                    continue
                self._upsert(conn, series_key, source_key, rows)
                self._logger.info(
                    "Fed balance sheet: upserted %d rows for %s through %s",
                    len(rows),
                    meta.series_code,
                    rows[-1][0],
                )
        finally:
            conn.close()

    def _resolve_lookback_days(self) -> int:
        raw = getattr(self._settings, "ingestion_fred_lookback_days", None)
        if raw is None:
            return 5
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 5
        return max(0, value)

    # ---------------------------------------------------------------- helpers
    def _ensure_source(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rankalpha.dim_source (source_name, version, exclude_from_screener, screener_weight) "
                "VALUES (%s, '1', false, 1.0) "
                "ON CONFLICT (source_name) DO NOTHING",
                ("FRED",),
            )
            conn.commit()
            cur.execute(
                "SELECT source_key FROM rankalpha.dim_source WHERE source_name = %s", ("FRED",)
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Could not resolve source_key for FRED")
            return int(row[0])

    def _ensure_dim_series(self, conn, meta: FredSeries) -> int:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rankalpha.dim_macro_series (series_code, series_name, category, frequency, units, is_active, description)
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (series_code) DO UPDATE
                  SET series_name = EXCLUDED.series_name,
                      category    = EXCLUDED.category,
                      frequency   = EXCLUDED.frequency,
                      units       = EXCLUDED.units,
                      description = EXCLUDED.description,
                      is_active   = TRUE
                """,
                (
                    meta.series_code,
                    meta.series_name,
                    meta.category,
                    meta.frequency,
                    meta.units,
                    meta.description,
                ),
            )
            conn.commit()
            cur.execute(
                "SELECT series_key FROM rankalpha.dim_macro_series WHERE series_code = %s",
                (meta.series_code,),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"Could not resolve series_key for {meta.series_code}")
            return int(row[0])

    def _latest_fact_date(self, conn, series_key: int) -> Optional[date]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(d.full_date)
                FROM rankalpha.fact_macro_series f
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE f.series_key = %s
                """,
                (series_key,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def _fetch_fred(
        self,
        fred_id: str,
        *,
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> List[Tuple[date, float]]:
        params = {
            "series_id": fred_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        if start_date:
            params["observation_start"] = start_date.strftime("%Y-%m-%d")
        if end_date:
            params["observation_end"] = end_date.strftime("%Y-%m-%d")

        resp = requests.get(FRED_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json() or {}
        obs = payload.get("observations") or []
        rows: List[Tuple[date, float]] = []
        for item in obs:
            val = item.get("value")
            if val is None or val == ".":
                continue
            try:
                v = float(val)
            except Exception:
                continue
            try:
                d = date.fromisoformat(item["date"])
            except Exception:
                continue
            rows.append((d, v))
        rows.sort(key=lambda x: x[0])
        return rows

    def _upsert(
        self,
        conn,
        series_key: int,
        source_key: int,
        rows: Iterable[Tuple[date, float]],
    ) -> None:
        values = [(r[0], series_key, source_key, r[1]) for r in rows]
        with conn.cursor() as cur:
            sql = """
                INSERT INTO rankalpha.fact_macro_series (date_key, series_key, source_key, value)
                SELECT d.date_key,
                       v.series_key,
                       v.source_key,
                       v.value::numeric
                FROM (VALUES %s) AS v(as_of_date, series_key, source_key, value)
                JOIN rankalpha.dim_date d ON d.full_date = v.as_of_date
                ON CONFLICT (date_key, series_key) DO UPDATE
                  SET value  = EXCLUDED.value,
                      source_key = EXCLUDED.source_key,
                      load_ts = now()
            """
            execute_values(cur, sql, values, page_size=200)
        conn.commit()
