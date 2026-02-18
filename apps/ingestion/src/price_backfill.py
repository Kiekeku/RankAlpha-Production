from __future__ import annotations

import argparse
import logging
from typing import Optional

import pandas as pd
import psycopg2

from apps.common.src.logging import setup_logging
from apps.ingestion.src.price_store import PriceStore
from apps.ingestion.src.price_sync_service import PriceSyncService
from apps.ingestion.src.settings import Settings
from apps.ingestion.src.utils import canonicalize_ohlcv


def _iter_symbols(price_store: PriceStore, symbols: Optional[str]) -> list[str]:
    if symbols:
        return [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return sorted(price_store.list_existing())


def _repair_outliers(
    df: pd.DataFrame,
    *,
    max_ratio: float,
    max_abs: Optional[float],
    logger: logging.Logger,
    symbol: str,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    price_cols = [c for c in ("Open", "High", "Low", "Close", "Adj Close") if c in df.columns]
    if not price_cols:
        return df
    ref_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    ref = pd.to_numeric(df[ref_col], errors="coerce")

    replacements: dict[pd.Timestamp, float] = {}
    null_rows: list[pd.Timestamp] = []
    last_valid: Optional[float] = None
    for idx, val in ref.items():
        if pd.isna(val):
            continue
        try:
            val_f = float(val)
        except Exception:
            continue
        if val_f <= 0:
            if last_valid is not None:
                replacements[idx] = last_valid
            else:
                null_rows.append(idx)
            continue
        if max_abs is not None and abs(val_f) > max_abs:
            if last_valid is not None:
                replacements[idx] = last_valid
            else:
                null_rows.append(idx)
            continue
        if last_valid is None:
            last_valid = val_f
            continue
        if last_valid == 0:
            if val_f != 0 and max_abs is not None and abs(val_f) > max_abs:
                replacements[idx] = last_valid
                continue
        ratio = val_f / last_valid if last_valid else float("inf")
        if ratio > max_ratio or ratio < 1.0 / max_ratio:
            replacements[idx] = last_valid
            continue
        last_valid = val_f

    if not replacements and not null_rows:
        return df
    logger.warning(
        "Repairing %d outlier rows (%d null) for %s (max_ratio=%s, max_abs=%s)",
        len(replacements) + len(null_rows),
        len(null_rows),
        symbol,
        max_ratio,
        max_abs,
    )
    fixed = df.copy()
    idxs = list(replacements.keys())
    vals = [replacements[i] for i in idxs]
    for col in price_cols:
        fixed.loc[idxs, col] = vals
        if null_rows:
            fixed.loc[null_rows, col] = None
    return fixed


def _load_parquet(
    path: str,
    symbol: str,
    logger: logging.Logger,
    *,
    repair_outliers: bool,
    max_ratio: float,
    max_abs: Optional[float],
) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_parquet(path, engine="pyarrow")
    except Exception as exc:
        logger.warning("Failed to read parquet for %s: %s", symbol, exc)
        return None
    if df is None or df.empty:
        return None
    df = canonicalize_ohlcv(df)
    if repair_outliers:
        df = _repair_outliers(
            df, max_ratio=max_ratio, max_abs=max_abs, logger=logger, symbol=symbol
        )
    return df


def _fetch_stock_key(conn, symbol: str) -> Optional[int]:
    cur = conn.cursor()
    try:
        cur.execute("SELECT stock_key FROM dim_stock WHERE symbol = %s", (symbol,))
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        cur.close()


def _sync_symbol(
    conn,
    syncer: PriceSyncService,
    price_store: PriceStore,
    symbol: str,
    *,
    repair_outliers: bool,
    max_ratio: float,
    max_abs: Optional[float],
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    path = price_store.path(symbol)
    df = _load_parquet(
        path,
        symbol,
        logger,
        repair_outliers=repair_outliers,
        max_ratio=max_ratio,
        max_abs=max_abs,
    )
    if df is None or df.empty:
        logger.info("No parquet rows for %s; skipping", symbol)
        return
    stock_key = _fetch_stock_key(conn, symbol)
    if stock_key is None:
        logger.info("Symbol %s not found in dim_stock; skipping", symbol)
        return
    if dry_run:
        logger.info("Dry run: %s has %d parquet rows", symbol, len(df.index))
        return

    syncer.sync(symbol, stock_key, df, force_full=True, use_full_history=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill fact_security_price from Parquet files.")
    parser.add_argument(
        "--symbols",
        help="Comma-separated list of symbols to backfill (default: all parquets).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of symbols processed.",
    )
    parser.add_argument(
        "--price-dir",
        default=None,
        help="Override Parquet directory (default from settings or /data/prices).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List symbols and row counts without writing to the database.",
    )
    parser.add_argument(
        "--repair-outliers",
        action="store_true",
        help="Replace extreme price outliers with the last valid price.",
    )
    parser.add_argument(
        "--max-ratio",
        type=float,
        default=100.0,
        help="Max allowed ratio vs previous valid price before treating as outlier.",
    )
    parser.add_argument(
        "--max-abs",
        type=float,
        default=1.0e7,
        help="Absolute price cap for outlier detection (set 0 to disable).",
    )
    args = parser.parse_args()

    settings = Settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger("ingestion.price_backfill")

    price_store = PriceStore(settings, logger)
    if args.price_dir:
        price_store.output_dir = args.price_dir

    symbols = _iter_symbols(price_store, args.symbols)
    if args.limit:
        symbols = symbols[: max(0, int(args.limit))]

    if not symbols:
        logger.warning("No parquet symbols found in %s", price_store.output_dir)
        return

    conn = psycopg2.connect(
        database=settings.database_name,
        user=settings.db_username,
        password=settings.password,
        host=settings.host,
        port=settings.port,
    )
    conn.autocommit = False
    syncer = PriceSyncService(conn, settings.ingestion_history_days or 760)

    logger.info(
        "Backfilling %d symbols from %s (dry_run=%s)",
        len(symbols),
        price_store.output_dir,
        args.dry_run,
    )
    try:
        max_abs = None if args.max_abs == 0 else args.max_abs
        for symbol in symbols:
            try:
                _sync_symbol(
                    conn,
                    syncer,
                    price_store,
                    symbol,
                    repair_outliers=args.repair_outliers,
                    max_ratio=args.max_ratio,
                    max_abs=max_abs,
                    dry_run=args.dry_run,
                    logger=logger,
                )
                if not args.dry_run:
                    conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.warning("Backfill failed for %s: %s", symbol, exc)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
