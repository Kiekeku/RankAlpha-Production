"""DB helpers for SOFR futures and derived FRA–OIS storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from apps.common.src.db import BatchWriter
from apps.ingestion.src.settings import Settings


@dataclass(frozen=True)
class SofrFutureRow:
    as_of_date: date
    root: str  # 'SR1' | 'SR3'
    year: int
    month: int
    local_symbol: str
    conid: Optional[int]
    last_px: Optional[float]
    settle_px: Optional[float]


def _get_date_key(conn, d: date) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT date_key FROM rankalpha.dim_date WHERE full_date = %s", (d,))
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"dim_date missing row for {d.isoformat()}")
        return int(row[0])


def upsert_sofr_futures(settings: Settings, rows: Sequence[SofrFutureRow]) -> int:
    if not rows:
        return 0
    writer = BatchWriter(settings=settings, page_size=200)
    # All rows share the same as_of_date most of the time, but allow mixed
    # dates in a single call (we compute date_key per row).
    values: List[Tuple[Any, ...]] = [
        (
            r.as_of_date,
            r.root.upper(),
            int(r.year),
            int(r.month),
            r.local_symbol,
            r.conid,
            r.last_px,
            r.settle_px,
        )
        for r in rows
    ]
    sql = (
        "INSERT INTO rankalpha.fact_sofr_futures (date_key, root, year_num, month_num, local_symbol, conid, last_px, settle_px)\n"
        "SELECT d.date_key, v.root, v.year_num, v.month_num, v.local_symbol, v.conid,\n"
        "       CASE WHEN v.last_px::text = '' THEN NULL ELSE v.last_px::numeric(10,4) END,\n"
        "       CASE WHEN v.settle_px::text = '' THEN NULL ELSE v.settle_px::numeric(10,4) END\n"
        "FROM (VALUES %s) AS v(as_of_date, root, year_num, month_num, local_symbol, conid, last_px, settle_px)\n"
        "JOIN rankalpha.dim_date d ON d.full_date = v.as_of_date\n"
        "ON CONFLICT (date_key, root, year_num, month_num) DO UPDATE\n"
        "  SET local_symbol = EXCLUDED.local_symbol,\n"
        "      conid        = COALESCE(EXCLUDED.conid, rankalpha.fact_sofr_futures.conid),\n"
        "      last_px      = EXCLUDED.last_px,\n"
        "      settle_px    = COALESCE(EXCLUDED.settle_px, rankalpha.fact_sofr_futures.settle_px),\n"
        "      load_ts      = now()\n"
    )
    writer.execute_values(sql, values, page_size=200)
    return len(values)


def compute_fra_ois_z(
    history: list[tuple[date, Optional[float]]],
    *,
    new_point: tuple[date, Optional[float]],
    ma_window: int = 5,
    z_window: int = 750,
    min_count: int = 500,
    clip_low: float = -3.0,
    clip_high: float = 5.0,
) -> Optional[float]:
    """
    Compute a rolling z-score for FRA–OIS spreads using a short smoothing MA first.

    history: ordered ascending list of (as_of_date, spread_bp) *excluding* new_point
    new_point: (as_of_date, spread_bp) to evaluate/return z for
    """
    from collections import deque
    from math import sqrt

    ma_q: deque[float] = deque()
    z_q: deque[float] = deque()
    z_sum = 0.0
    z_sumsq = 0.0

    def push(value: Optional[float]) -> Optional[float]:
        nonlocal z_sum, z_sumsq
        if value is None:
            return None
        ma_q.append(float(value))
        if len(ma_q) > ma_window:
            ma_q.popleft()
        if len(ma_q) < ma_window:
            return None
        ma_val = sum(ma_q) / ma_window
        z_q.append(ma_val)
        z_sum += ma_val
        z_sumsq += ma_val * ma_val
        if len(z_q) > z_window:
            oldz = z_q.popleft()
            z_sum -= oldz
            z_sumsq -= oldz * oldz
        return ma_val

    # run through history (ordered)
    for _, spread in history:
        push(spread)

    # compute z for new point
    ma_val = push(new_point[1])
    if ma_val is None:
        return None
    count = len(z_q)
    if count < min_count:
        return None
    mean = z_sum / count
    variance = (z_sumsq / count) - (mean * mean)
    std = sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return None
    z = (ma_val - mean) / std
    return max(clip_low, min(clip_high, z))


def latest_sofr_futures(settings: Settings, root: str) -> List[Dict[str, Any]]:
    writer = BatchWriter(settings=settings)
    with writer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH latest AS (
                  SELECT MAX(date_key) AS date_key FROM rankalpha.fact_sofr_futures WHERE root = %s
                )
                SELECT d.full_date, f.root, f.year_num, f.month_num, f.local_symbol, f.conid, f.last_px, f.settle_px
                FROM rankalpha.fact_sofr_futures f
                JOIN latest l ON l.date_key = f.date_key
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE f.root = %s
                ORDER BY f.year_num, f.month_num
                """,
                (root.upper(), root.upper()),
            )
            rows = cur.fetchall()
    return [
        {
            "as_of_date": r[0],
            "root": r[1],
            "year": int(r[2]),
            "month": int(r[3]),
            "local_symbol": r[4],
            "conid": r[5],
            "last_px": r[6],
            "settle_px": r[7],
        }
        for r in rows
    ]


def history_sofr_contract(
    settings: Settings,
    root: str,
    year: int,
    month: int,
    *,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[Dict[str, Any]]:
    writer = BatchWriter(settings=settings)
    params: List[Any] = [root.upper(), int(year), int(month)]
    where = ["root = %s", "year_num = %s", "month_num = %s"]
    if date_from is not None:
        where.append("d.full_date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("d.full_date <= %s")
        params.append(date_to)
    sql = f"""
        SELECT d.full_date, last_px, settle_px
        FROM rankalpha.fact_sofr_futures f
        JOIN rankalpha.dim_date d ON d.date_key = f.date_key
        WHERE {" AND ".join(where)}
        ORDER BY d.full_date
    """
    with writer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [{"as_of_date": r[0], "last_px": r[1], "settle_px": r[2]} for r in rows]


def upsert_fra_ois(
    settings: Settings,
    as_of: date,
    start_months: int,
    end_months: int,
    fra_source: str,
    *,
    fra_rate: Optional[float],
    ois_forward: Optional[float],
    spread_bp: Optional[float],
    fra_ois_z: Optional[float],
) -> None:
    writer = BatchWriter(settings=settings)
    with writer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rankalpha.fact_fra_ois
                  (date_key, start_months, end_months, fra_source, fra_rate, ois_forward, spread_bp, fra_ois_z)
                SELECT d.date_key, %s, %s, %s, %s, %s, %s, %s
                FROM rankalpha.dim_date d
                WHERE d.full_date = %s
                ON CONFLICT (date_key, start_months, end_months, fra_source) DO UPDATE
                  SET fra_rate    = EXCLUDED.fra_rate,
                      ois_forward = EXCLUDED.ois_forward,
                      spread_bp   = EXCLUDED.spread_bp,
                      fra_ois_z   = EXCLUDED.fra_ois_z,
                      load_ts     = now()
                """,
                (
                    start_months,
                    end_months,
                    fra_source.upper(),
                    fra_rate,
                    ois_forward,
                    spread_bp,
                    fra_ois_z,
                    as_of,
                ),
            )


def latest_fra_ois(
    settings: Settings,
    start_months: int,
    end_months: int,
    fra_source: str,
) -> Optional[Dict[str, Any]]:
    writer = BatchWriter(settings=settings)
    with writer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.full_date, f.fra_rate, f.ois_forward, f.spread_bp, f.fra_ois_z
                FROM rankalpha.fact_fra_ois f
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE f.start_months = %s AND f.end_months = %s AND f.fra_source = %s
                ORDER BY d.full_date DESC
                LIMIT 1
                """,
                (start_months, end_months, fra_source.upper()),
            )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "as_of_date": row[0],
        "fra_rate": row[1],
        "ois_forward": row[2],
        "spread_bp": row[3],
        "fra_ois_z": row[4],
    }


def fetch_fra_ois_history(
    settings: Settings,
    start_months: int,
    end_months: int,
    fra_source: str,
    *,
    limit: int = 800,
) -> list[tuple[date, Optional[float]]]:
    """Fetch recent FRA–OIS spreads ordered ascending."""
    writer = BatchWriter(settings=settings)
    with writer.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.full_date, f.spread_bp
                FROM rankalpha.fact_fra_ois f
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE f.start_months = %s AND f.end_months = %s AND f.fra_source = %s
                ORDER BY d.full_date DESC
                LIMIT %s
                """,
                (start_months, end_months, fra_source.upper(), limit),
            )
            rows = cur.fetchall()
    rows = list(reversed(rows))  # oldest first
    return [(r[0], float(r[1]) if r[1] is not None else None) for r in rows]
