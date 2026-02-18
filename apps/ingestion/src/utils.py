"""Shared utilities for the ingestion service."""

from __future__ import annotations

import os
import re
from datetime import datetime

import pandas as pd

CANON_OHLCV_ORDER: tuple[str, ...] = (
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
)

DATE_INDEX_CANDIDATE_COLUMNS: tuple[str, ...] = (
    "Date",
    "__index_level_0__",
    "Datetime",
    "Timestamp",
)


def _is_numeric_index(idx: pd.Index) -> bool:
    if isinstance(idx, pd.RangeIndex):
        return True
    try:
        return bool(pd.api.types.is_numeric_dtype(getattr(idx, "dtype", None)))
    except Exception:
        return False


def _looks_like_integer_strings(idx: pd.Index) -> bool:
    try:
        values = idx.astype(str)
    except Exception:
        return False
    if len(values) == 0:
        return False
    pat = re.compile(r"^-?\d+$")
    try:
        return bool(all(pat.match(v) for v in values))
    except Exception:
        return False


def _coerce_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    x = df
    if isinstance(x.index, pd.DatetimeIndex):
        return x

    for candidate in DATE_INDEX_CANDIDATE_COLUMNS:
        if candidate not in x.columns:
            continue
        try:
            parsed = pd.to_datetime(x[candidate], errors="coerce")
            if parsed.notna().any():
                x = x.set_index(parsed)
                return x
        except Exception:
            continue

    # Never coerce a numeric/range index into epoch timestamps.
    if _is_numeric_index(x.index) or _looks_like_integer_strings(x.index):
        return x

    try:
        parsed = pd.to_datetime(x.index, errors="coerce")
        if parsed.notna().any():
            x.index = parsed
    except Exception:
        pass
    return x


def normalize_parquet_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with Parquet-safe, string column names."""
    cols = df.columns
    out = df.copy()
    if isinstance(cols, pd.MultiIndex):
        new_cols: list[str] = []
        for tup in cols:
            parts = [str(p) for p in tup if p is not None and str(p) != ""]
            name = "_".join(parts) if parts else ""
            for base in CANON_OHLCV_ORDER:
                if name.startswith(base):
                    name = base
                    break
            new_cols.append(name or "col")
        out.columns = pd.Index(new_cols, dtype=object)
    else:
        out.columns = pd.Index([str(c).strip() for c in cols], dtype=object)
    if not out.columns.is_unique:
        seen: dict[str, int] = {}
        uniq: list[str] = []
        for c in out.columns:
            if c not in seen:
                seen[c] = 0
                uniq.append(c)
            else:
                seen[c] += 1
                uniq.append(f"{c}__{seen[c]}")
        out.columns = pd.Index(uniq, dtype=object)
    return out


def canonicalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return a Parquet-safe OHLCV DataFrame with a consistent schema."""
    x = normalize_parquet_columns(df)
    try:
        x = _coerce_datetime_index(x)
        if getattr(x.index, "tz", None) is not None:
            x.index = x.index.tz_localize(None)
        x = x[~x.index.duplicated(keep="last")].sort_index()
    except Exception:
        pass

    try:
        lower_cols = {str(c).lower() for c in x.columns}
    except Exception:
        lower_cols = set()
    had_unadjusted_close = ("unadjusted close" in lower_cols) or ("unadjusted_close" in lower_cols)

    cols_present = [c for c in CANON_OHLCV_ORDER if c in x.columns]
    x = x.reindex(columns=list(CANON_OHLCV_ORDER)) if cols_present else x
    for c in CANON_OHLCV_ORDER:
        if c not in x.columns:
            x[c] = pd.Series(index=x.index, dtype=float)
    x = x.loc[:, list(CANON_OHLCV_ORDER)]
    for c in CANON_OHLCV_ORDER:
        x[c] = pd.to_numeric(x[c], errors="coerce").astype(float)
    try:
        if had_unadjusted_close and "Close" in x.columns:
            x["Adj Close"] = x["Close"].astype(float)
        elif x["Adj Close"].dropna().empty and "Close" in x.columns:
            x["Adj Close"] = x["Close"].astype(float)
    except Exception:
        pass
    return x


def to_naive_ts(ts: pd.Timestamp | datetime | str) -> pd.Timestamp:
    try:
        t = pd.Timestamp(ts)
        if getattr(t, "tz", None) is not None:
            t = t.tz_localize(None)
        return t
    except Exception:
        return pd.Timestamp(ts)


def to_naive_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    try:
        if getattr(idx, "tz", None) is not None:
            return idx.tz_localize(None)
        return idx
    except Exception:
        return idx


def round4(x: float | int | None) -> float | None:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return round(float(x), 4)
    except Exception:
        return None


def set_perms_766(path: str) -> None:
    try:
        os.chmod(path, 0o766)
    except Exception:
        pass


def history_days(settings, default: int = 760) -> int:
    try:
        return int(getattr(settings, "ingestion_history_days", default) or default)
    except Exception:
        return default


__all__ = [
    "CANON_OHLCV_ORDER",
    "DATE_INDEX_CANDIDATE_COLUMNS",
    "canonicalize_ohlcv",
    "history_days",
    "normalize_parquet_columns",
    "round4",
    "set_perms_766",
    "to_naive_index",
    "to_naive_ts",
]
