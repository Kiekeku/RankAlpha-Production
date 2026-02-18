from __future__ import annotations

import argparse
import glob
import os
from typing import Dict, Tuple

import pandas as pd


def _import_modules():
    from apps.scorer.src.services.db import ScoreRepository  # type: ignore
    from apps.scorer.src.services.momentum import MomentumCalculator  # type: ignore
    from apps.scorer.src.services.prices import PriceReader  # type: ignore
    from apps.scorer.src.settings import Settings  # type: ignore

    return PriceReader, MomentumCalculator, ScoreRepository, Settings


def _parse_weights(spec: str | None, defaults: Dict[int, float]) -> Dict[int, float]:
    out = dict(defaults)
    if not spec:
        return out
    parts = [p.strip() for p in str(spec).split(",") if p.strip()]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
        elif ":" in p:
            k, v = p.split(":", 1)
        else:
            continue
        try:
            out[int(k.strip())] = float(v.strip())
        except Exception:
            continue
    return out


def _candidate_asof_dates(engine, min_cov: float, limit: int) -> pd.DataFrame:
    q = f"""
        WITH elig AS (
            SELECT COUNT(1) AS n
            FROM rankalpha.dim_stock ds
            JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
            WHERE ds.is_active IS TRUE
        ), cov AS (
            SELECT sp.date_key, d.full_date, COUNT(DISTINCT sp.stock_key) AS have_px
            FROM rankalpha.fact_security_price sp
            JOIN rankalpha.dim_stock s ON s.stock_key = sp.stock_key
            JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = s.symbol AND ue.eligible IS TRUE
            JOIN rankalpha.dim_date d ON d.date_key = sp.date_key
            WHERE s.is_active IS TRUE
            GROUP BY sp.date_key, d.full_date
        )
        SELECT c.date_key, c.full_date, c.have_px,
               CASE WHEN e.n > 0 THEN c.have_px::float / e.n::float ELSE NULL END AS coverage
        FROM cov c CROSS JOIN elig e
        ORDER BY c.date_key DESC
        LIMIT {int(limit)}
    """
    df = pd.read_sql_query(q, engine, parse_dates=["full_date"])
    if df.empty:
        return df
    df["coverage"] = pd.to_numeric(df["coverage"], errors="coerce")
    good = df[df["coverage"] >= float(min_cov)]
    return good if not good.empty else df


def _eligible_symbols(engine) -> set[str]:
    try:
        df = pd.read_sql_query(
            """
            SELECT UPPER(ds.symbol) AS symbol
            FROM rankalpha.dim_stock ds
            JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
            WHERE ds.is_active IS TRUE
            """,
            engine,
        )
        return {str(s).upper() for s in df["symbol"].tolist()}
    except Exception:
        return set()


def _compute_combined_for_date(
    df: pd.DataFrame,
    min_valid_frac: float,
    base_weights: Dict[int, float],
    t_cap: float,
    PriceReader,
    MomentumCalculator,
) -> Tuple[float | None, float | None]:
    # Returns (blended_slope, last_ts) for df (sliced to as-of already)
    try:
        px = PriceReader.select_close(df)
    except Exception:
        px = pd.Series(index=df.index, dtype=float)
    if px.dropna().empty:
        return None, None
    windows = [200, 90, 50, 30]
    pairs = []
    for w in windows:
        s, r2, n = MomentumCalculator.linreg_log_slope_r2(df, w, min_valid_frac=min_valid_frac)
        if s is None or r2 is None or n is None or n <= 2 or r2 <= 0:
            continue
        r = (float(r2) ** 0.5) * (1.0 if float(s) >= 0.0 else -1.0)
        denom = 1.0 - (r * r)
        if denom <= 0.0:
            continue
        t = abs(r) * ((float(n) - 2.0) ** 0.5) / (denom**0.5)
        t_factor = min(1.0, abs(t) / float(max(1e-9, t_cap)))
        eff_w = float(base_weights.get(w, 1.0)) * (t_factor**2)
        pairs.append((float(s), eff_w))
    if not pairs:
        return None, None
    wsum = sum(w for _, w in pairs)
    if wsum <= 0:
        return None, None
    combo = sum(s * w for s, w in pairs) / wsum
    try:
        last_ts = pd.to_datetime(px.dropna().index.max())
    except Exception:
        last_ts = None
    return float(combo), last_ts


def backfill(days: int, min_cov: float, prices_dir: str | None = None, dry_run: bool = False):
    PriceReader, MomentumCalculator, ScoreRepository, Settings = _import_modules()
    settings = Settings()
    dsn = "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=settings.db_username,
        pwd=settings.password,
        host=settings.host,
        port=settings.port,
        db=settings.database_name,
    )
    repo = ScoreRepository(dsn, logger=None)
    engine = repo.engine

    # Determine candidate as-of dates
    cov_df = _candidate_asof_dates(engine, min_cov=min_cov, limit=days)
    if cov_df.empty:
        print("No candidate dates found for backfill")
        return

    # Universe and parquet files
    eligible = _eligible_symbols(engine)
    prices_path = prices_dir or "/data/prices"
    parquet_files = glob.glob(os.path.join(prices_path, "*.parquet"))
    if eligible:
        parquet_files = [
            f for f in parquet_files if os.path.splitext(os.path.basename(f))[0].upper() in eligible
        ]

    base_weights = _parse_weights(
        getattr(settings, "scoring_momentum_window_weights", None),
        {200: 1.0, 90: 1.0, 50: 1.0, 30: 1.0},
    )
    min_valid_frac = float(getattr(settings, "scoring_momentum_min_valid_frac", 0.8) or 0.8)
    t_cap = float(getattr(settings, "scoring_momentum_tstat_cap", 3.0) or 3.0)
    min_group = int(getattr(settings, "scoring_momentum_min_group_size", 5) or 5)
    mode = str(getattr(settings, "scoring_momentum_composite_mode", "blend") or "blend").lower()
    w_resid = float(getattr(settings, "scoring_momentum_residual_weight", 0.7) or 0.7)
    w_raw = float(getattr(settings, "scoring_momentum_raw_weight", 0.3) or 0.3)
    s = w_resid + w_raw
    if s <= 0:
        w_resid, w_raw = 0.7, 0.3
        s = 1.0
    w_resid /= s
    w_raw /= s

    # Ensure score types exist
    conn = repo.connect()
    cur = conn.cursor()
    repo.ensure_score_types(cur)
    type_keys = repo.fetch_score_type_keys(cur)
    key_raw = type_keys.get("momentum raw score")
    key_resid = type_keys.get("momentum residual score")
    key_comp = type_keys.get("momentum score")

    # Sector map
    sec_df = pd.read_sql_query(
        "SELECT UPPER(symbol) AS symbol, sector FROM rankalpha.dim_stock WHERE is_active IS TRUE",
        engine,
    )
    sec_map = {row.symbol: row.sector for _, row in sec_df.iterrows()}

    for _, row in cov_df.iterrows():
        date_key = int(row["date_key"])
        asof = pd.to_datetime(row["full_date"]).normalize()
        print(f"Backfilling as-of {asof.date()} (date_key={date_key}) ...")

        combined: Dict[str, Tuple[int, int | None, float]] = {}
        processed_syms: set[str] = set()
        for file in parquet_files:
            sym = os.path.splitext(os.path.basename(file))[0].upper()
            processed_syms.add(sym)
            try:
                df = PriceReader.read_price_parquet(file, logger=None)
            except Exception:
                continue
            # Truncate to as-of
            try:
                df = df.loc[:asof]
            except Exception:
                pass
            combo, last_ts = _compute_combined_for_date(
                df, min_valid_frac, base_weights, t_cap, PriceReader, MomentumCalculator
            )
            if combo is None or last_ts is None or pd.isna(last_ts) or last_ts.normalize() != asof:
                continue
            stock_key = repo.fetch_stock_key(cur, sym)
            if stock_key is None:
                continue
            combined[sym] = (date_key, stock_key, float(combo))

        if not combined:
            print(f"No symbols to score on {asof.date()}; skipping")
            continue

        ser = pd.Series({sym: val[2] for sym, val in combined.items()}, dtype=float)
        # Raw percentile
        raw_pct = ser.rank(pct=True, ascending=True)
        raw_score = (raw_pct * 99.0 + 1.0).clip(1.0, 100.0)
        # Residual by sector median, fallback to market
        sectors = pd.Series({sym: sec_map.get(sym) for sym in ser.index})
        df_m = pd.DataFrame({"mom": ser, "sector": sectors})
        grp = df_m.groupby("sector", dropna=False)
        sec_median = grp["mom"].transform("median")
        sec_size = grp["mom"].transform("size")
        market_median = float(df_m["mom"].median()) if not df_m["mom"].empty else 0.0
        center = sec_median.where(sec_size >= float(min_group), other=market_median)
        resid = df_m["mom"] - center
        resid_pct = resid.rank(pct=True, ascending=True)
        resid_score = (resid_pct * 99.0 + 1.0).clip(1.0, 100.0)
        # Composite
        comp = (
            resid_score
            if mode == "residual"
            else raw_score
            if mode == "raw"
            else (resid_score * w_resid + raw_score * w_raw)
        )

        inserted_counts = {"raw": 0, "residual": 0, "composite": 0}
        for label, series, key, tag in (
            ("momentum raw score", raw_score, key_raw, "raw"),
            ("momentum residual score", resid_score, key_resid, "residual"),
            ("momentum score", comp, key_comp, "composite"),
        ):
            if key is None:
                print(f"Missing score type for {label}; skipping")
                continue
            for sym, score_val in series.items():
                dk, sk, _ = combined.get(sym, (None, None, None))
                if dk is None or sk is None or pd.isna(score_val):
                    continue
                rounded = PriceReader.round2(score_val)
                if rounded is None:
                    continue
                if dry_run:
                    inserted_counts[tag] += 1
                else:
                    try:
                        repo.insert_score_if_absent(cur, int(dk), int(sk), int(key), float(rounded))
                        inserted_counts[tag] += cur.rowcount or 0
                    except Exception:
                        pass
            if not dry_run:
                conn.commit()
        print(
            f"Inserted {inserted_counts['raw']} raw, {inserted_counts['residual']} residual, {inserted_counts['composite']} composite for {asof.date()}"
        )

    try:
        cur.close()
        conn.close()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(
        description="Backfill momentum raw/residual/composite for recent days with price coverage."
    )
    ap.add_argument(
        "--days", type=int, default=21, help="Number of recent price days to consider (default 21)"
    )
    ap.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="Minimum coverage fraction across eligible symbols (default from env or 0.5)",
    )
    ap.add_argument(
        "--prices-dir", default=None, help="Directory with <SYMBOL>.parquet (default /data/prices)"
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Compute and report counts without inserting"
    )
    args = ap.parse_args()

    PriceReader, MomentumCalculator, ScoreRepository, Settings = _import_modules()
    settings = Settings()
    min_cov = (
        float(args.min_coverage)
        if args.min_coverage is not None
        else float(getattr(settings, "scoring_asof_min_coverage", 0.5) or 0.5)
    )
    backfill(days=args.days, min_cov=min_cov, prices_dir=args.prices_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
