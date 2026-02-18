import glob
import os
import sys

import pandas as pd

from apps.common.src.logging import get_logger
from apps.ingestion.src.utils import DATE_INDEX_CANDIDATE_COLUMNS

logger = get_logger(__name__)


def _normalize_parquet_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = df.columns
    out = df.copy()
    if isinstance(cols, pd.MultiIndex):
        names: list[str] = []
        for tup in cols:
            parts = [str(p) for p in tup if p is not None and str(p) != ""]
            name = "_".join(parts) if parts else ""
            for base in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
                if name.startswith(base):
                    name = base
                    break
            names.append(name or "col")
        out.columns = pd.Index(names, dtype=object)
    else:
        out.columns = pd.Index([str(c).strip() for c in cols], dtype=object)
    if not out.columns.is_unique:
        seen = {}
        uniq = []
        for c in out.columns:
            n = seen.get(c, 0)
            if n:
                uniq.append(f"{c}__{n}")
            else:
                uniq.append(c)
            seen[c] = n + 1
        out.columns = pd.Index(uniq, dtype=object)
    return out


CANON_OHLCV_ORDER = ("Open", "High", "Low", "Close", "Adj Close", "Volume")


def _canonicalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    x = _normalize_parquet_columns(df)
    # Ensure datetime index
    try:
        if not isinstance(x.index, pd.DatetimeIndex):
            for candidate in DATE_INDEX_CANDIDATE_COLUMNS:
                if candidate not in x.columns:
                    continue
                parsed = pd.to_datetime(x[candidate], errors="coerce")
                if parsed.notna().any():
                    x = x.set_index(parsed)
                    break
            else:
                if not (
                    isinstance(x.index, pd.RangeIndex)
                    or pd.api.types.is_numeric_dtype(getattr(x.index, "dtype", None))
                ):
                    parsed = pd.to_datetime(x.index, errors="coerce")
                    if parsed.notna().any():
                        x.index = parsed
        if getattr(x.index, "tz", None) is not None:
            x.index = x.index.tz_localize(None)
        x = x[~x.index.duplicated(keep="last")].sort_index()
    except Exception:
        pass
    # Add missing canonical columns, enforce order and dtype
    try:
        lower_cols = {str(c).lower() for c in x.columns}
    except Exception:
        lower_cols = set()
    had_unadjusted_close = ("unadjusted close" in lower_cols) or ("unadjusted_close" in lower_cols)
    for c in CANON_OHLCV_ORDER:
        if c not in x.columns:
            x[c] = pd.Series(index=x.index, dtype=float)
    x = x.loc[:, list(CANON_OHLCV_ORDER)]
    for c in CANON_OHLCV_ORDER:
        x[c] = pd.to_numeric(x[c], errors="coerce").astype(float)
    # Map adjusted close semantics
    try:
        if had_unadjusted_close and "Close" in x.columns:
            x["Adj Close"] = x["Close"].astype(float)
        elif x["Adj Close"].dropna().empty and "Close" in x.columns:
            x["Adj Close"] = x["Close"].astype(float)
    except Exception:
        pass
    return x


def repair_one(path: str) -> bool:
    # Try full read first
    df = None
    try:
        df = pd.read_parquet(path, engine="pyarrow")
    except Exception:
        # Fallbacks: select canonical OHLCV set, then minimal Close-only
        for cols in (["Open", "High", "Low", "Close", "Volume", "Adj Close"], ["Close"]):
            try:
                df = pd.read_parquet(path, engine="pyarrow", columns=cols)
                break
            except Exception:
                continue
    if df is None or df.empty:
        return False
    # Ensure datetime index
    try:
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
    except Exception:
        pass
    df = _canonicalize_ohlcv(df)
    tmp = f"{path}.tmp"
    df.to_parquet(tmp, engine="pyarrow")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o766)
    except Exception:
        pass
    return True


def main(directory: str = "/data/prices") -> int:
    files = sorted(glob.glob(os.path.join(directory, "*.parquet")))
    if not files:
        logger.warning("No parquet files found under %s", directory)
        return 0
    ok = 0
    fail = 0
    for f in files:
        try:
            if repair_one(f):
                ok += 1
                # logger.info("Repaired %s", os.path.basename(f))
            else:
                fail += 1
                logger.info("Skipped (empty/unreadable): %s", os.path.basename(f))
        except Exception as exc:
            fail += 1
            logger.warning(
                "Failed to repair %s: %s",
                os.path.basename(f),
                exc,
            )
    logger.info(
        "Repair summary: ok=%s failed=%s total=%s",
        ok,
        fail,
        len(files),
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else "/data/prices"
    raise SystemExit(main(directory))
