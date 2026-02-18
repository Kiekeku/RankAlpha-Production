"""High‑yield stress tape derived from the CCC HY OAS series."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:  # pragma: no cover - allow pure-function tests without psycopg2 installed
    psycopg2 = None
    execute_values = None

try:
    from apps.ingestion.src.settings import Settings
except ImportError:  # pragma: no cover - allow isolated testing of pure functions
    Settings = None


@dataclass(frozen=True)
class HyStressRow:
    as_of_date: date
    raw: Optional[float]
    ma_10: Optional[float]
    z_750: Optional[float]


def compute_hy_stress(
    rows: Sequence[Tuple[date, Optional[float]]],
    *,
    ma_window: int = 10,
    z_window: int = 750,
) -> List[HyStressRow]:
    """Compute HY stress raw / MA / z-score over the supplied time series.

    rows must be ordered by as_of_date ascending and represent trading days only.
    """
    ma_q: deque[float] = deque()
    z_q: deque[float] = deque()
    ma_sum = 0.0
    z_sum = 0.0
    z_sumsq = 0.0
    out: List[HyStressRow] = []

    for dt, value in rows:
        ma_val: Optional[float] = None
        z_val: Optional[float] = None

        if value is not None:
            ma_q.append(float(value))
            ma_sum += float(value)
            if len(ma_q) > ma_window:
                ma_sum -= ma_q.popleft()
            if len(ma_q) == ma_window:
                ma_val = ma_sum / ma_window
                z_q.append(ma_val)
                z_sum += ma_val
                z_sumsq += ma_val * ma_val
                if len(z_q) > z_window:
                    old = z_q.popleft()
                    z_sum -= old
                    z_sumsq -= old * old
                if len(z_q) == z_window:
                    mean = z_sum / z_window
                    variance = (z_sumsq / z_window) - (mean * mean)
                    std = sqrt(variance) if variance > 0 else 0.0
                    if std > 0:
                        z_val = (ma_val - mean) / std

        out.append(HyStressRow(as_of_date=dt, raw=value, ma_10=ma_val, z_750=z_val))

    return out


class HyStressJob:
    """Derives HY stress metrics from CCCHYS benchmark and persists to fact_hy_stress."""

    def __init__(
        self, settings: Settings, logger, db_factory: Callable[[], "psycopg2.extensions.connection"]
    ):
        if Settings is None:
            raise RuntimeError("apps.ingestion.src.settings.Settings is required for HyStressJob")
        if psycopg2 is None or execute_values is None:
            raise RuntimeError("psycopg2 is required for HyStressJob but is not installed")
        self._settings = settings
        self._logger = logger
        self._db_factory = db_factory
        self._benchmark_name = (
            getattr(settings, "ingestion_hy_stress_benchmark", "%CCCHYS") or "%CCCHYS"
        )
        self._ma_window = int(getattr(settings, "ingestion_hy_stress_ma_window", 10) or 10)
        self._z_window = int(getattr(settings, "ingestion_hy_stress_z_window", 750) or 750)

    # Public API ---------------------------------------------------------
    def refresh(self, *, as_of: Optional[date] = None) -> None:
        enabled = bool(getattr(self._settings, "ingestion_hy_stress_enabled", True))
        if not enabled:
            self._logger.info("HY stress job disabled via INGESTION_HY_STRESS_ENABLED; skipping")
            return

        conn = self._db_factory()
        try:
            benchmark_key = self._lookup_benchmark_key(conn, self._benchmark_name)
            if benchmark_key is None:
                self._logger.warning(
                    "HY stress job: benchmark %s not found in dim_benchmark; skipping",
                    self._benchmark_name,
                )
                return

            last_date = self._latest_fact_date(conn, benchmark_key)
            series = self._fetch_series(conn, benchmark_key, as_of=as_of)
            if not series:
                self._logger.info(
                    "HY stress job: no source rows for %s; skipping", self._benchmark_name
                )
                return
            self._logger.info(
                "HY stress job: source rows=%d window=%s z_window=%s (from %s to %s)",
                len(series),
                self._ma_window,
                self._z_window,
                series[0][0],
                series[-1][0],
            )

            computed = compute_hy_stress(series, ma_window=self._ma_window, z_window=self._z_window)
            to_write = [row for row in computed if last_date is None or row.as_of_date > last_date]
            if not to_write:
                self._logger.info("HY stress job: no new dates to upsert (last=%s)", last_date)
                return

            self._upsert(conn, benchmark_key, to_write)
            self._logger.info(
                "HY stress job: upserted %d rows through %s", len(to_write), to_write[-1].as_of_date
            )
        finally:
            conn.close()

    # Internal helpers ---------------------------------------------------
    def _lookup_benchmark_key(self, conn, benchmark_name: str) -> Optional[int]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT benchmark_key FROM rankalpha.dim_benchmark WHERE benchmark_name = %s",
                (benchmark_name,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def _fetch_series(
        self,
        conn,
        benchmark_key: int,
        *,
        as_of: Optional[date] = None,
    ) -> List[Tuple[date, Optional[float]]]:
        params: List[object] = [benchmark_key]
        where = ["f.benchmark_key = %s"]
        if as_of is not None:
            where.append("d.full_date <= %s")
            params.append(as_of)

        sql = f"""
            SELECT d.full_date, f.close_px
            FROM rankalpha.fact_benchmark_price f
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE {" AND ".join(where)}
            ORDER BY d.full_date ASC
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [(r[0], float(r[1]) if r[1] is not None else None) for r in rows]

    def _latest_fact_date(self, conn, benchmark_key: int) -> Optional[date]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(d.full_date)
                FROM rankalpha.fact_hy_stress f
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE f.benchmark_key = %s
                """,
                (benchmark_key,),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def _upsert(self, conn, benchmark_key: int, rows: Iterable[HyStressRow]) -> None:
        values = [
            (
                r.as_of_date,
                benchmark_key,
                r.raw,
                r.ma_10,
                r.z_750,
            )
            for r in rows
        ]
        with conn.cursor() as cur:
            sql = """
                INSERT INTO rankalpha.fact_hy_stress
                  (date_key, benchmark_key, hy_stress_raw, hy_stress_ma, hy_stress_z)
                SELECT d.date_key,
                       v.benchmark_key,
                       v.hy_stress_raw::numeric,
                       v.hy_stress_ma::numeric,
                       v.hy_stress_z::numeric
                FROM (VALUES %s) AS v(as_of_date, benchmark_key, hy_stress_raw, hy_stress_ma, hy_stress_z)
                JOIN rankalpha.dim_date d ON d.full_date = v.as_of_date
                ON CONFLICT (date_key, benchmark_key) DO UPDATE
                  SET hy_stress_raw = EXCLUDED.hy_stress_raw,
                      hy_stress_ma  = EXCLUDED.hy_stress_ma,
                      hy_stress_z   = EXCLUDED.hy_stress_z,
                      load_ts       = now()
            """
            execute_values(cur, sql, values, page_size=200)
        conn.commit()
