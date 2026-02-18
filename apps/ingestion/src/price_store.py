"""Parquet storage helpers for the ingestion service."""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Optional

import pandas as pd

try:  # pyarrow is an optional dependency for unit tests
    import pyarrow.parquet as pq  # type: ignore
except Exception:  # pragma: no cover
    pq = None

from apps.ingestion.src.settings import Settings
from apps.ingestion.src.utils import (
    CANON_OHLCV_ORDER,
    DATE_INDEX_CANDIDATE_COLUMNS,
    canonicalize_ohlcv,
    history_days,
    set_perms_766,
)


class PriceStore:
    """Handles Parquet IO and retention hygiene."""

    def __init__(self, settings: Settings, logger) -> None:
        default_dir = "/data/prices"
        configured = getattr(settings, "ingestion_price_dir", None)
        self.output_dir = configured or default_dir
        self._logger = logger
        self._history_days = history_days(settings)

    def prepare(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        try:
            os.chmod(self.output_dir, 0o777)
        except Exception:
            pass

    def repair_if_available(self) -> None:
        try:
            from apps.ingestion.src.repair_parquets import main as repair_callable

            self._logger.info("Running Parquet schema repair on startup ...")
            repair_callable(self.output_dir)
        except Exception as exc:
            self._logger.warning("Repair step skipped or failed: %s", exc)

    def path(self, symbol: str) -> str:
        return os.path.join(self.output_dir, f"{symbol.upper()}.parquet")

    def list_existing(self) -> set[str]:
        return {Path(p).stem.upper() for p in glob.glob(os.path.join(self.output_dir, "*.parquet"))}

    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        dest_path = self.path(symbol)
        if not os.path.exists(dest_path):
            return None
        df: Optional[pd.DataFrame] = None
        # Prefer a tail-read to avoid loading decades of history when upstream
        # Parquets are full-history snapshots.
        if pq is not None:
            try:
                df = self._read_parquet_tail(dest_path, rows=self._history_days)
            except Exception as exc:
                self._logger.debug("Tail parquet read failed for %s: %s", symbol, exc)
                df = None
        if df is None:
            try:
                df = pd.read_parquet(dest_path, engine="pyarrow")
            except Exception as exc:
                self._logger.warning("Failed to read parquet for %s: %s", symbol, exc)
                return None
        if df is None or df.empty:
            return None

        raw_df = df
        canonical_df = canonicalize_ohlcv(df)
        if self._needs_on_disk_repair(raw_df):
            repaired = self._repair_file(symbol, dest_path)
            if repaired is not None and not repaired.empty:
                canonical_df = repaired
        return canonical_df.tail(self._history_days)

    def save(self, symbol: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        dest_path = self.path(symbol)
        df = canonicalize_ohlcv(df)
        df = df.tail(self._history_days)
        df.to_parquet(dest_path, engine="pyarrow")
        set_perms_766(dest_path)

    @staticmethod
    def _read_parquet_tail(path: str, *, rows: int) -> pd.DataFrame:
        if pq is None:
            raise RuntimeError("pyarrow is required for tail parquet reads")
        pf = pq.ParquetFile(path)
        if getattr(pf, "num_row_groups", 0) <= 0:
            return pd.DataFrame()

        want = max(int(rows or 0), 1)
        total = 0
        row_groups: list[int] = []
        # Read from the end to capture the most recent history quickly.
        for rg in range(pf.num_row_groups - 1, -1, -1):
            try:
                rg_rows = int(pf.metadata.row_group(rg).num_rows)  # type: ignore[union-attr]
            except Exception:
                rg_rows = 0
            row_groups.append(rg)
            total += rg_rows
            if total >= want:
                break
        row_groups = list(reversed(row_groups))
        table = pf.read_row_groups(row_groups, use_threads=True)
        df = table.to_pandas()
        if len(df.index) > want:
            df = df.tail(want)
        return df

    def delete(self, symbol: str) -> bool:
        path = self.path(symbol)
        try:
            os.remove(path)
            self._logger.info("Deleted parquet for inactive symbol %s", symbol)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            self._logger.warning("Failed to delete parquet for %s: %s", symbol, exc)
            return False

    @staticmethod
    def _needs_on_disk_repair(df: pd.DataFrame) -> bool:
        cols = [str(c).strip() for c in df.columns]
        if tuple(cols) != CANON_OHLCV_ORDER:
            return True
        if any(candidate in cols for candidate in DATE_INDEX_CANDIDATE_COLUMNS):
            return True

        idx = df.index
        if not isinstance(idx, pd.DatetimeIndex):
            try:
                parsed = pd.to_datetime(idx, errors="coerce")
                return bool(pd.notna(parsed).any())
            except Exception:
                return False

        if getattr(idx, "tz", None) is not None:
            return True
        if not idx.is_monotonic_increasing:
            return True
        if idx.has_duplicates:
            return True
        return False

    def _repair_file(self, symbol: str, path: str) -> Optional[pd.DataFrame]:
        try:
            full_df = pd.read_parquet(path, engine="pyarrow")
        except Exception as exc:
            self._logger.warning("Auto-repair skipped for %s (read failed): %s", symbol, exc)
            return None
        if full_df is None or full_df.empty:
            return None

        repaired = canonicalize_ohlcv(full_df)
        try:
            repaired.to_parquet(path, engine="pyarrow")
            set_perms_766(path)
            self._logger.info("Auto-repaired parquet schema/index for %s", symbol)
        except Exception as exc:
            self._logger.warning("Auto-repair write failed for %s: %s", symbol, exc)
        return repaired
