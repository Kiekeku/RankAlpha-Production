"""Database sync helpers for ingestion price data."""

from __future__ import annotations

from typing import List, Tuple

import pandas as pd
from psycopg2.extras import execute_values

from apps.ingestion.src.utils import (
    DATE_INDEX_CANDIDATE_COLUMNS,
    canonicalize_ohlcv,
    round4,
)


class PriceSyncService:
    """Syncs Parquet OHLCV data into fact_security_price."""

    def __init__(self, conn, history_days: int, *, anchor_check_days: int = 3) -> None:
        self._conn = conn
        self._history_days = history_days
        try:
            self._anchor_check_days = max(1, int(anchor_check_days))
        except Exception:
            self._anchor_check_days = 3

    def sync(
        self,
        symbol: str,
        stock_key: int,
        df: pd.DataFrame,
        *,
        force_full: bool = False,
        use_full_history: bool = False,
    ) -> None:
        if df is None or df.empty:
            return
        df = canonicalize_ohlcv(df)
        if not use_full_history:
            df = df.tail(self._history_days)
        if not isinstance(df.index, pd.DatetimeIndex):
            for candidate in DATE_INDEX_CANDIDATE_COLUMNS:
                if candidate not in df.columns:
                    continue
                parsed = pd.to_datetime(df[candidate], errors="coerce")
                if parsed.notna().any():
                    df = df.set_index(parsed)
                    break
            else:
                if not (
                    isinstance(df.index, pd.RangeIndex)
                    or pd.api.types.is_numeric_dtype(getattr(df.index, "dtype", None))
                ):
                    parsed = pd.to_datetime(df.index, errors="coerce")
                    if parsed.notna().any():
                        df.index = parsed
        df = df.sort_index()

        # Back-adjust detection:
        # - Compare a short rolling window of "already-known" prices (exclude the newest row,
        #   which may be newly appended during the current run) between Parquet and DB.
        # - If stable, only upsert the tail; otherwise, upsert the full retained window.
        check_idx = df.index[:-1] if len(df.index) > 1 else df.index
        if len(check_idx) > self._anchor_check_days:
            check_idx = check_idx[-self._anchor_check_days :]

        check_map: dict[int, float | None] = {}
        check_keys: list[int] = []
        for ts in check_idx:
            try:
                dk = int(pd.Timestamp(ts).date().strftime("%Y%m%d"))
                check_keys.append(dk)
                check_map[dk] = round4(df.at[ts, "Adj Close"])
            except Exception:
                continue

        db_map: dict[int, float | None] = {}
        cur = self._conn.cursor()
        try:
            if check_keys:
                cur.execute(
                    """
                    SELECT sp.date_key, sp.close_px
                    FROM rankalpha.fact_security_price sp
                    WHERE sp.stock_key = %s AND sp.date_key = ANY(%s)
                    """,
                    (stock_key, check_keys),
                )
                for dk, close_px in cur.fetchall() or []:
                    try:
                        db_map[int(dk)] = round4(close_px)
                    except Exception:
                        continue
        finally:
            cur.close()

        recent_match = bool(check_keys)
        for dk in check_keys:
            if dk not in db_map:
                recent_match = False
                break
            left = check_map.get(dk)
            right = db_map.get(dk)
            if left is None or right is None:
                recent_match = False
                break
            if abs(float(left) - float(right)) > 0.0005:
                recent_match = False
                break

        full_resync = bool(force_full or use_full_history or not recent_match)
        start_idx = 0 if full_resync else max(0, len(df.index) - 5)

        rows: List[Tuple] = []
        for ts in df.index[start_idx:]:
            try:
                dk = int(pd.Timestamp(ts).date().strftime("%Y%m%d"))
                o = round4(df.at[ts, "Open"])
                h = round4(df.at[ts, "High"])
                low = round4(df.at[ts, "Low"])
                cpx = round4(df.at[ts, "Adj Close"])
                vol = None
                try:
                    v = df.at[ts, "Volume"]
                    vol = (
                        int(v)
                        if not (isinstance(v, float) and pd.isna(v)) and v is not None
                        else None
                    )
                except Exception:
                    vol = None
                rows.append((dk, stock_key, o, h, low, cpx, vol))
            except Exception:
                continue

        self._bulk_upsert(rows)
        self._prune_old_rows(stock_key, df)

    def _bulk_upsert(self, rows: List[Tuple]) -> None:
        if not rows:
            return
        cur = self._conn.cursor()
        try:
            execute_values(
                cur,
                """
                INSERT INTO rankalpha.fact_security_price
                    (date_key, stock_key, open_px, high_px, low_px, close_px, volume)
                VALUES %s
                ON CONFLICT (date_key, stock_key) DO UPDATE SET
                    open_px = EXCLUDED.open_px,
                    high_px = EXCLUDED.high_px,
                    low_px = EXCLUDED.low_px,
                    close_px = EXCLUDED.close_px,
                    volume = EXCLUDED.volume,
                    load_ts = now()
                """,
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s)",
                page_size=1000,
            )
        finally:
            cur.close()

    def _prune_old_rows(self, stock_key: int, df: pd.DataFrame) -> None:
        try:
            min_keep_key = int(pd.Timestamp(df.index[0]).date().strftime("%Y%m%d"))
        except Exception:
            return
        cur = self._conn.cursor()
        try:
            cur.execute(
                "DELETE FROM rankalpha.fact_security_price WHERE stock_key=%s AND date_key < %s",
                (stock_key, min_keep_key),
            )
        finally:
            cur.close()
