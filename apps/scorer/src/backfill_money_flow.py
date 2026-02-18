from __future__ import annotations

import argparse
import math
import os
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from apps.common.src.settings_base import BaseAppSettings
from apps.scorer.src.services.prices import PriceReader


@dataclass(frozen=True)
class BackfillConfig:
    target_trading_days: int
    warmup_trading_days: int
    min_valid_frac: float
    component_weights: tuple[float, float, float, float]  # (cmf20, cmf5, vol_surp, ret20)
    delete_existing: bool
    dry_run: bool
    page_size: int
    price_dir: str


def _dsn_from_settings(settings: BaseAppSettings) -> str:
    return (
        f"dbname={settings.database_name} "
        f"user={settings.db_username} "
        f"password={settings.password} "
        f"host={settings.host} "
        f"port={settings.port}"
    )


def _weighted_zscore(x: np.ndarray, w: np.ndarray, *, clip: float = 3.0) -> np.ndarray:
    z = np.full(x.shape, np.nan, dtype=float)
    mask = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if int(mask.sum()) < 2:
        return z

    xw = x[mask]
    ww = w[mask]
    w_sum = float(np.sum(ww))
    if (not np.isfinite(w_sum)) or w_sum <= 0:
        return z

    mean = float(np.sum(ww * xw) / w_sum)
    var = float(np.sum(ww * (xw - mean) ** 2) / w_sum)
    std = float(math.sqrt(max(var, 0.0)))
    if std <= 0 or (not np.isfinite(std)):
        return z

    z_vals = (xw - mean) / std
    if clip is not None:
        z_vals = np.clip(z_vals, -clip, clip)
    z[mask] = z_vals
    return z


def _weighted_rank_pct(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """
    Weighted percentile rank in [0, 1] using a mid-rank convention per unique value.

    Matches apps.scorer.src.services.money_flow.MoneyFlowCalculator.weighted_rank_pct.
    """
    out = np.full(values.shape, np.nan, dtype=float)
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if int(mask.sum()) == 0:
        return out

    idx = np.flatnonzero(mask)
    x = values[idx]
    w = weights[idx]

    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ws = w[order]

    total = float(np.sum(ws))
    if (not np.isfinite(total)) or total <= 0:
        return out

    # Group by unique x (exact match, consistent with current implementation).
    change = np.empty(xs.shape[0], dtype=bool)
    change[0] = True
    change[1:] = xs[1:] != xs[:-1]
    starts = np.flatnonzero(change)
    ends = np.append(starts[1:], xs.shape[0])

    group_w = np.add.reduceat(ws, starts)
    w_before = np.cumsum(group_w) - group_w
    p_by_group = (w_before + 0.5 * group_w) / total

    p_sorted = np.empty(xs.shape[0], dtype=float)
    for i, (s, e) in enumerate(zip(starts, ends, strict=False)):
        p_sorted[s:e] = p_by_group[i]

    # Unsort into output, only for valid rows.
    pct_valid = np.empty_like(p_sorted)
    pct_valid[order] = p_sorted
    out[idx] = pct_valid
    return out


def _iter_chunks(
    rows: Sequence[Sequence[object]], chunk_size: int
) -> Iterable[Sequence[Sequence[object]]]:
    for i in range(0, len(rows), chunk_size):
        yield rows[i : i + chunk_size]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-off backfill for fact_score_history: money flow score."
    )
    parser.add_argument(
        "--days", type=int, default=520, help="Trading days to backfill (default: 520)."
    )
    parser.add_argument(
        "--warmup-days",
        type=int,
        default=80,
        help="Extra trading days of price history for rolling windows (default: 80).",
    )
    parser.add_argument(
        "--min-valid-frac",
        type=float,
        default=0.8,
        help="Rolling window min_valid_frac (default: 0.8).",
    )
    parser.add_argument(
        "--component-weights",
        type=str,
        default="cmf20=0.4,cmf5=0.2,vol_surp=0.3,ret20=0.1",
        help="Weights: cmf20, cmf5, vol_surp, ret20 (default matches scorer).",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not delete existing money flow score rows in the backfill window (default: delete then insert).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write to DB.")
    parser.add_argument(
        "--page-size", type=int, default=5000, help="execute_values page size (default: 5000)."
    )
    parser.add_argument(
        "--price-dir",
        type=str,
        default="/data/prices",
        help="Directory containing canonical Parquets (default: /data/prices).",
    )
    args = parser.parse_args()

    def _parse_weights(raw: str) -> tuple[float, float, float, float]:
        default = (0.4, 0.2, 0.3, 0.1)
        if not raw:
            return default
        weights = dict(cmf20=0.4, cmf5=0.2, vol_surp=0.3, ret20=0.1)
        try:
            parts = [p.strip() for p in str(raw).split(",") if p.strip()]
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                elif ":" in p:
                    k, v = p.split(":", 1)
                else:
                    continue
                k = k.strip().lower()
                v_f = float(v.strip())
                if k in ("cmf20", "cmf_med", "cmf_20"):
                    weights["cmf20"] = v_f
                elif k in ("cmf5", "cmf_short", "cmf_5"):
                    weights["cmf5"] = v_f
                elif k in ("vol_surp", "vol", "vol_surp_60"):
                    weights["vol_surp"] = v_f
                elif k in ("ret20", "ret_20", "return20"):
                    weights["ret20"] = v_f
            total = sum(weights.values())
            if total <= 0:
                return default
            return (
                weights["cmf20"] / total,
                weights["cmf5"] / total,
                weights["vol_surp"] / total,
                weights["ret20"] / total,
            )
        except Exception:
            return default

    cfg = BackfillConfig(
        target_trading_days=max(1, int(args.days)),
        warmup_trading_days=max(0, int(args.warmup_days)),
        min_valid_frac=float(args.min_valid_frac),
        component_weights=_parse_weights(args.component_weights),
        delete_existing=not bool(args.keep_existing),
        dry_run=bool(args.dry_run),
        page_size=max(100, int(args.page_size)),
        price_dir=str(args.price_dir),
    )

    settings = BaseAppSettings()
    dsn = _dsn_from_settings(settings)

    t0 = time.time()
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Resolve score type key
            cur.execute(
                "SELECT score_type_key FROM rankalpha.dim_score_type WHERE score_type_name=%s LIMIT 1",
                ("money flow score",),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("dim_score_type missing: 'money flow score'")
            score_type_key = int(row[0])

            # Latest trading date present in prices (restricted to active equities with known sector)
            cur.execute(
                """
                SELECT MAX(sp.date_key)
                FROM rankalpha.fact_security_price sp
                JOIN rankalpha.dim_stock ds ON ds.stock_key = sp.stock_key
                LEFT JOIN rankalpha.dim_asset_type at ON at.asset_type_key = ds.asset_type_key
                WHERE ds.is_active IS TRUE
                  AND ds.sector IS NOT NULL
                  AND trim(ds.sector) <> ''
                  AND upper(trim(ds.sector)) <> 'UNKNOWN'
                  AND COALESCE(at.asset_type_name, 'equity') ILIKE 'equity'
                """
            )
            latest_date_key = cur.fetchone()[0]
            if latest_date_key is None:
                raise RuntimeError("No price history found for active equities.")
            latest_date_key = int(latest_date_key)

            # Target + fetch date range (trading days)
            cur.execute(
                """
                SELECT dd.date_key
                FROM rankalpha.dim_date dd
                WHERE dd.is_trading_day IS TRUE AND dd.date_key <= %s
                ORDER BY dd.date_key DESC
                LIMIT %s
                """,
                (latest_date_key, cfg.target_trading_days),
            )
            target_date_keys = [int(r[0]) for r in cur.fetchall()][::-1]
            if not target_date_keys:
                raise RuntimeError("Could not resolve target trading days from dim_date.")

            fetch_days = cfg.target_trading_days + cfg.warmup_trading_days
            cur.execute(
                """
                SELECT dd.date_key
                FROM rankalpha.dim_date dd
                WHERE dd.is_trading_day IS TRUE AND dd.date_key <= %s
                ORDER BY dd.date_key DESC
                LIMIT %s
                """,
                (latest_date_key, fetch_days),
            )
            fetch_date_keys = [int(r[0]) for r in cur.fetchall()]
            fetch_start_key = (
                int(fetch_date_keys[-1]) if fetch_date_keys else int(target_date_keys[0])
            )

            print(
                f"[money-flow-backfill] latest_date_key={latest_date_key} "
                f"target_days={len(target_date_keys)} fetch_days={fetch_days} fetch_start_key={fetch_start_key}"
            )

            # Universe + sector filter matches API/migration usage; weights are based on latest mktcap (<= latest_date_key)
            cur.execute(
                """
                WITH metric AS (
                  SELECT metric_key
                  FROM rankalpha.dim_fin_metric
                  WHERE metric_code = 'mktcap'
                  LIMIT 1
                ),
                universe AS (
                  SELECT ds.stock_key, ds.symbol
                  FROM rankalpha.dim_stock ds
                  LEFT JOIN rankalpha.dim_asset_type at ON at.asset_type_key = ds.asset_type_key
                  WHERE ds.is_active IS TRUE
                    AND ds.sector IS NOT NULL
                    AND trim(ds.sector) <> ''
                    AND upper(trim(ds.sector)) <> 'UNKNOWN'
                    AND COALESCE(at.asset_type_name, 'equity') ILIKE 'equity'
                ),
                latest_mktcap AS (
                  SELECT f.stock_key, MAX(f.date_key) AS date_key
                  FROM rankalpha.fact_fin_fundamentals f
                  JOIN metric m ON m.metric_key = f.metric_key
                  JOIN universe u ON u.stock_key = f.stock_key
                  WHERE f.date_key <= %s
                  GROUP BY f.stock_key
                )
                SELECT
                  u.stock_key,
                  u.symbol,
                  f.metric_value AS mktcap_millions
                FROM universe u
                LEFT JOIN latest_mktcap lm ON lm.stock_key = u.stock_key
                LEFT JOIN rankalpha.fact_fin_fundamentals f
                  ON f.stock_key = lm.stock_key AND f.date_key = lm.date_key
                 AND f.metric_key = (SELECT metric_key FROM metric)
                """,
                (latest_date_key,),
            )
            rows = cur.fetchall()
            if not rows:
                raise RuntimeError("No eligible stocks found for money flow backfill.")
            w_by_stock: dict[int, float] = {}
            symbol_by_stock: dict[int, str] = {}
            for stock_key, symbol, mktcap in rows:
                sk = int(stock_key)
                sym = str(symbol).upper().strip() if symbol is not None else ""
                if not sym:
                    continue
                symbol_by_stock[sk] = sym
                if mktcap is None:
                    w_by_stock[sk] = 1.0
                    continue
                try:
                    w = float(math.log1p(max(float(mktcap), 0.0)))
                    w_by_stock[sk] = w if (math.isfinite(w) and w > 0) else 1.0
                except Exception:
                    w_by_stock[sk] = 1.0
            symbols = sorted(set(symbol_by_stock.values()))
            print(
                f"[money-flow-backfill] eligible universe: stocks={len(symbol_by_stock):,} symbols={len(symbols):,} "
                f"price_dir={cfg.price_dir}"
            )
            if not symbols:
                raise RuntimeError("No eligible symbols found for money flow backfill.")

    # Compute in-memory (release DB connection while crunching).
    t_fetch = time.time()
    print(f"[money-flow-backfill] loaded universe + date range in {t_fetch - t0:.1f}s")

    # Read Parquets for the fetch window (CMF uses raw Close; ret_20 uses Adj Close).
    start_dt = pd.to_datetime(str(fetch_start_key), format="%Y%m%d")
    end_dt = pd.to_datetime(str(latest_date_key), format="%Y%m%d")

    frames: list[pd.DataFrame] = []
    missing_files = 0
    read_failures = 0
    empty_files = 0
    for stock_key, symbol in symbol_by_stock.items():
        path = os.path.join(cfg.price_dir, f"{symbol.upper()}.parquet")
        if not os.path.exists(path):
            missing_files += 1
            continue
        try:
            px = PriceReader.read_price_parquet(path, logger=None, prefer_full_ohlcv=True)
        except Exception:
            # Fall back to a direct read if schema normalization fails.
            try:
                px = pd.read_parquet(path, engine="pyarrow")
            except Exception:
                read_failures += 1
                continue
        if px is None or px.empty:
            empty_files += 1
            continue
        try:
            px = px.sort_index()
            px = px.loc[start_dt:end_dt]
        except Exception:
            pass
        if px is None or px.empty:
            continue

        try:
            idx = px.index
            if not isinstance(idx, pd.DatetimeIndex):
                idx = pd.to_datetime(idx, errors="coerce")
            date_key = idx.strftime("%Y%m%d").astype(int)
        except Exception:
            continue

        close_raw = pd.to_numeric(px["Close"], errors="coerce") if "Close" in px.columns else np.nan
        adj_close = PriceReader.select_close(px).astype(float)
        high = pd.to_numeric(px["High"], errors="coerce") if "High" in px.columns else np.nan
        low = pd.to_numeric(px["Low"], errors="coerce") if "Low" in px.columns else np.nan
        volume = pd.to_numeric(px["Volume"], errors="coerce") if "Volume" in px.columns else np.nan

        frames.append(
            pd.DataFrame(
                {
                    "stock_key": int(stock_key),
                    "date_key": date_key,
                    "high": high,
                    "low": low,
                    "close_raw": close_raw,
                    "adj_close": adj_close,
                    "volume": volume,
                }
            )
        )

    if not frames:
        raise RuntimeError(
            f"No Parquet rows loaded from {cfg.price_dir} (missing_files={missing_files}, read_failures={read_failures}, empty_files={empty_files})"
        )

    df = pd.concat(frames, ignore_index=True)
    # Cast to numerics
    df["stock_key"] = pd.to_numeric(df["stock_key"], errors="coerce").astype("int64")
    df["date_key"] = pd.to_numeric(df["date_key"], errors="coerce").astype("int64")
    for col in ("high", "low", "close_raw", "adj_close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["stock_key", "date_key"]).sort_values(["stock_key", "date_key"])

    # Map weights
    df["w"] = df["stock_key"].map(w_by_stock).astype(float).fillna(1.0)
    df["w"] = df["w"].replace([np.inf, -np.inf], np.nan).fillna(1.0)

    # Money flow components (vectorized with groupby-rolling)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mf_mult = (2.0 * df["close_raw"] - df["high"] - df["low"]) / rng
    mf_mult = mf_mult.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mf_vol = mf_mult * df["volume"]
    df["mf_vol"] = mf_vol

    g = df.groupby("stock_key", sort=False)
    min5 = int(math.ceil(5 * cfg.min_valid_frac))
    min20 = int(math.ceil(20 * cfg.min_valid_frac))
    min60 = int(math.ceil(60 * cfg.min_valid_frac))

    df["vol_sum_5"] = g["volume"].rolling(5, min_periods=min5).sum().reset_index(level=0, drop=True)
    df["mf_sum_5"] = g["mf_vol"].rolling(5, min_periods=min5).sum().reset_index(level=0, drop=True)
    df["cmf_5"] = df["mf_sum_5"] / df["vol_sum_5"]

    df["vol_sum_20"] = (
        g["volume"].rolling(20, min_periods=min20).sum().reset_index(level=0, drop=True)
    )
    df["mf_sum_20"] = (
        g["mf_vol"].rolling(20, min_periods=min20).sum().reset_index(level=0, drop=True)
    )
    df["cmf_20"] = df["mf_sum_20"] / df["vol_sum_20"]

    df["vol_med_60"] = (
        g["volume"].rolling(60, min_periods=min60).median().reset_index(level=0, drop=True)
    )
    df["vol_surp_60"] = np.log(df["volume"] / df["vol_med_60"])

    df["ret_20"] = g["adj_close"].pct_change(20)

    # Backfill window mask
    target_set = set(int(k) for k in target_date_keys)
    df_target = df[df["date_key"].isin(target_set)].copy()
    df_target = df_target[
        ["date_key", "stock_key", "w", "cmf_5", "cmf_20", "vol_surp_60", "ret_20"]
    ]
    print(f"[money-flow-backfill] scoring rows: {len(df_target):,} (target window)")

    # Compute scores per date_key
    w_cmf20, w_cmf5, w_vol, w_ret20 = cfg.component_weights
    scored_rows: list[tuple[int, int, int, int, float]] = []
    inserted_total = 0

    for i, (date_key, grp) in enumerate(df_target.groupby("date_key", sort=True), start=1):
        stock_keys = grp["stock_key"].to_numpy(dtype=np.int64, copy=False)
        w = grp["w"].to_numpy(dtype=float, copy=False)

        z20 = _weighted_zscore(grp["cmf_20"].to_numpy(dtype=float, copy=False), w)
        z5 = _weighted_zscore(grp["cmf_5"].to_numpy(dtype=float, copy=False), w)
        zv = _weighted_zscore(grp["vol_surp_60"].to_numpy(dtype=float, copy=False), w)
        zr = _weighted_zscore(grp["ret_20"].to_numpy(dtype=float, copy=False), w)

        # Composite money-flow signal: renormalize over available components (missing is ignored).
        num = (
            np.where(np.isfinite(z20), z20 * w_cmf20, 0.0)
            + np.where(np.isfinite(z5), z5 * w_cmf5, 0.0)
            + np.where(np.isfinite(zv), zv * w_vol, 0.0)
            + np.where(np.isfinite(zr), zr * w_ret20, 0.0)
        )
        den = (
            np.where(np.isfinite(z20), w_cmf20, 0.0)
            + np.where(np.isfinite(z5), w_cmf5, 0.0)
            + np.where(np.isfinite(zv), w_vol, 0.0)
            + np.where(np.isfinite(zr), w_ret20, 0.0)
        ).astype(float)
        mf_raw = np.full(num.shape, np.nan, dtype=float)
        valid = den > 0
        mf_raw[valid] = num[valid] / den[valid]
        pct = _weighted_rank_pct(mf_raw.astype(float, copy=False), w)
        score = np.clip(pct * 99.0 + 1.0, 1.0, 100.0)

        ok = np.isfinite(score)
        if int(ok.sum()) == 0:
            continue

        # Round to 2 decimals to match NUMERIC(14,2)
        rounded = np.round(score[ok].astype(float), 2)
        for sk, val in zip(stock_keys[ok], rounded, strict=False):
            scored_rows.append((int(date_key), int(sk), 1, score_type_key, float(val)))

        if i % 25 == 0:
            print(
                f"[money-flow-backfill] computed {i}/{len(target_date_keys)} dates "
                f"(buffered_rows={len(scored_rows):,})"
            )

    t_compute = time.time()
    print(
        f"[money-flow-backfill] computed scores in {t_compute - t_fetch:.1f}s (rows={len(scored_rows):,})"
    )

    if cfg.dry_run:
        print("[money-flow-backfill] dry-run: skipping DB write")
        return

    settings = BaseAppSettings()
    dsn = _dsn_from_settings(settings)
    with psycopg2.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            start_key = int(min(target_date_keys))
            end_key = int(max(target_date_keys))
            if cfg.delete_existing:
                print(
                    f"[money-flow-backfill] deleting existing rows for score_type_key={score_type_key} "
                    f"date_key in [{start_key}..{end_key}]"
                )
                cur.execute(
                    """
                    DELETE FROM rankalpha.fact_score_history f
                    WHERE f.score_type_key = %s
                      AND f.date_key >= %s AND f.date_key <= %s
                    """,
                    (score_type_key, start_key, end_key),
                )
                print(f"[money-flow-backfill] deleted {cur.rowcount:,} rows")

            insert_sql = """
                INSERT INTO rankalpha.fact_score_history (date_key, stock_key, source_key, score_type_key, score)
                VALUES %s
            """

            for chunk in _iter_chunks(scored_rows, cfg.page_size * 10):
                execute_values(cur, insert_sql, chunk, page_size=cfg.page_size)
                inserted_total += int(cur.rowcount or 0)

            # Refresh latest nowcast snapshot so the Money Flow pillar score is computed immediately.
            cur.execute("SELECT rankalpha.fn_nowcast_snapshot_upsert_latest(%s)", ("nowcast_v2",))

        conn.commit()

    t_done = time.time()
    print(
        f"[money-flow-backfill] inserted {inserted_total:,} rows, recomputed latest nowcast snapshot "
        f"in {t_done - t_compute:.1f}s (total {t_done - t0:.1f}s)"
    )


if __name__ == "__main__":
    main()
