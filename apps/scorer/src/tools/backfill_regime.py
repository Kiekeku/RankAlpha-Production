"""
Backfill regime series (US): robust per-style Z and composite cores.

Fast, vectorized path that reads mv_style_intensity_us for a date window,
computes Z per style, builds RiskOn/RiskOff cores + EMA10/EMA50 + labels + index,
then upserts into fact_style_z_us and fact_regime_series.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Iterable, List, Tuple

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, text


def _import_modules():
    from apps.scorer.src.services.db import ScoreRepository  # type: ignore
    from apps.scorer.src.settings import Settings  # type: ignore

    return Settings, ScoreRepository


def _dsn_from_settings(settings) -> str:
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=settings.db_username,
        pwd=settings.password,
        host=settings.host,
        port=settings.port,
        db=settings.database_name,
    )


def _refresh_regime_mvs(repo) -> None:
    conn = None
    try:
        conn = psycopg2.connect(repo.dsn)
        conn.autocommit = True
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_universe_regime_us"
                )
            except Exception:
                cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_universe_regime_us")
            try:
                cur.execute(
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY rankalpha.mv_style_intensity_us"
                )
            except Exception:
                cur.execute("REFRESH MATERIALIZED VIEW rankalpha.mv_style_intensity_us")
    finally:
        if conn is not None:
            conn.close()


def _robust_z_series(x: pd.Series, win: int = 252) -> pd.Series:
    x = x.astype(float)
    med = x.rolling(win, min_periods=90).median()

    # MAD
    def _mad(a: pd.Series) -> float:
        arr = a.values.astype(float)
        if arr.size == 0:
            return 0.0
        m = np.median(arr)
        return float(np.median(np.abs(arr - m)))

    mad = x.rolling(win, min_periods=90).apply(_mad, raw=False)
    scale = 1.4826 * mad
    # IQR fallback
    iqr = x.rolling(win, min_periods=90).quantile(0.75) - x.rolling(win, min_periods=90).quantile(
        0.25
    )
    scale = scale.where((scale > 1e-8) & np.isfinite(scale), 0.7413 * iqr)
    # stdev fallback
    st = x.rolling(win, min_periods=2).std()
    scale = scale.where((scale > 1e-8) & np.isfinite(scale), st.clip(lower=1e-6))
    z = (x - med) / scale
    return z.replace([np.inf, -np.inf], 0.0).fillna(0.0).clip(-4, 4)


def _load_intensity(engine, days: int | None, start: date | None, end: date | None) -> pd.DataFrame:
    if days is not None:
        # get last N trading days present in intensity MV
        q = text(
            """
            WITH d AS (
              SELECT DISTINCT date_key
              FROM rankalpha.mv_style_intensity_us
              ORDER BY date_key DESC
              LIMIT :lim
            )
            SELECT d.full_date, i.date_key, i.style_name, i.intensity_raw, i.universe_count
            FROM rankalpha.mv_style_intensity_us i
            JOIN rankalpha.dim_date d ON d.date_key = i.date_key
            WHERE i.date_key IN (SELECT date_key FROM d)
            ORDER BY i.date_key, i.style_name
            """
        )
        return pd.read_sql(q, engine, params={"lim": int(days)}, parse_dates=["full_date"])  # type: ignore
    # explicit window
    params = {"start": start, "end": end}
    q = text(
        """
        SELECT d.full_date, i.date_key, i.style_name, i.intensity_raw, i.universe_count
        FROM rankalpha.mv_style_intensity_us i
        JOIN rankalpha.dim_date d ON d.date_key = i.date_key
        WHERE d.full_date BETWEEN :start AND :end
        ORDER BY i.date_key, i.style_name
        """
    )
    return pd.read_sql(q, engine, params=params, parse_dates=["full_date"])  # type: ignore


def _canonical_styles(engine) -> List[str]:
    df = pd.read_sql(
        "SELECT DISTINCT canonical_name FROM rankalpha.dim_style_regime_map ORDER BY 1", engine
    )
    return [str(x) for x in df["canonical_name"].tolist()]


def _risk_sets(engine) -> Tuple[dict, dict]:
    # Weights live in the mapping; sets are fixed by canonical name
    risk_on = {
        "Momentum": 1.0,
        "Pullback": 0.6,
        "QualityGrowth": 0.9,
        "ValueGARP": 0.4,
        "IPO": 0.5,
        "EarningsPost": 0.6,
        "Squeeze": 0.3,
    }
    risk_off = {
        "Short": 1.0,
        "MeanRev": 0.6,
        "Defensive": 0.5,
        "EarningsPre": 0.3,
    }
    return risk_on, risk_off


def _weights_map(engine) -> dict:
    df = pd.read_sql(
        "SELECT canonical_name, regime_weight FROM rankalpha.dim_style_regime_map", engine
    )
    return {str(r[0]): float(r[1]) for r in df.itertuples(index=False)}


def _upsert_style_z(conn, rows: Iterable[Tuple[int, str, float]], batch: int = 5000) -> None:
    tpl = "INSERT INTO rankalpha.fact_style_z_us(date_key, style_name, z_value) VALUES %s ON CONFLICT (date_key, style_name) DO UPDATE SET z_value = EXCLUDED.z_value"
    cur = conn.cursor()
    rows_list = list(rows)
    for i in range(0, len(rows_list), batch):
        execute_values(cur, tpl, rows_list[i : i + batch])
    conn.commit()


def _upsert_regime_series(
    conn,
    rows: Iterable[Tuple[int, float, float, float, float, float, str, float]],
    batch: int = 5000,
) -> None:
    tpl = (
        "INSERT INTO rankalpha.fact_regime_series(date_key, risk_on_core, risk_off_core, regime_raw, ema10, ema50, regime_label, regime_index) "
        "VALUES %s ON CONFLICT (date_key) DO UPDATE SET risk_on_core=EXCLUDED.risk_on_core, risk_off_core=EXCLUDED.risk_off_core, "
        "regime_raw=EXCLUDED.regime_raw, ema10=EXCLUDED.ema10, ema50=EXCLUDED.ema50, regime_label=EXCLUDED.regime_label, regime_index=EXCLUDED.regime_index"
    )
    cur = conn.cursor()
    rows_list = list(rows)
    for i in range(0, len(rows_list), batch):
        execute_values(cur, tpl, rows_list[i : i + batch])
    conn.commit()


def backfill(
    days: int | None, start: date | None, end: date | None, refresh: bool, batch_size: int
) -> None:
    Settings, ScoreRepository = _import_modules()
    s = Settings()
    dsn = _dsn_from_settings(s)
    engine = create_engine(dsn)
    repo = ScoreRepository(dsn, logger=None)
    if refresh:
        _refresh_regime_mvs(repo)

    df = _load_intensity(engine, days=days, start=start, end=end)
    if df.empty:
        print("No intensity rows found for the requested window")
        return

    # Ensure canonical columns and sort
    canon = _canonical_styles(engine)
    wide = df.pivot_table(
        index="full_date", columns="style_name", values="intensity_raw", aggfunc="first"
    ).sort_index()
    for c in canon:
        if c not in wide.columns:
            wide[c] = 0.0
    wide = wide[canon]

    # Compute robust Z per style
    zwide = wide.apply(_robust_z_series)

    # Regime cores
    risk_on, risk_off = _risk_sets(engine)
    wmap = _weights_map(engine)
    risk_on_core = sum(
        zwide.get(k, 0.0) * float(wmap.get(k, risk_on.get(k, 1.0))) for k in risk_on.keys()
    )
    risk_off_core = sum(
        zwide.get(k, 0.0) * float(wmap.get(k, risk_off.get(k, 1.0))) for k in risk_off.keys()
    )
    regime_raw = risk_on_core - risk_off_core

    # EMA10/EMA50 over the full window
    ema10 = regime_raw.ewm(span=10, adjust=False).mean()
    ema50 = regime_raw.ewm(span=50, adjust=False).mean()

    # 3-day hysteresis label based on EMA10
    e10 = ema10
    last3_up = e10.rolling(3).apply(lambda a: float((a > 0.5).all()))
    last3_dn = e10.rolling(3).apply(lambda a: float((a < -0.5).all()))
    label = np.where(last3_up == 1.0, "Risk-On", np.where(last3_dn == 1.0, "Risk-Off", "Neutral"))

    # UI index: z of EMA10 over trailing 252 (min 20)
    mu = ema10.rolling(252, min_periods=20).mean()
    sd = ema10.rolling(252, min_periods=20).std().replace(0, 1.0)
    zidx = (ema10 - mu) / sd
    regime_index = (50 + 10 * zidx).clip(0, 100)

    # Build rows to upsert
    # Map dates to date_keys
    dkeys = pd.read_sql(
        "SELECT date_key, full_date FROM rankalpha.dim_date", engine, parse_dates=["full_date"]
    )  # type: ignore
    dk_map = {pd.Timestamp(r[1]).date(): int(r[0]) for r in dkeys.itertuples(index=False)}

    # Style Z rows
    zrows: List[Tuple[int, str, float]] = []
    for as_of, row in zwide.iterrows():
        dk = dk_map.get(as_of.date())
        if dk is None:
            continue
        for style, z in row.items():
            zrows.append((dk, str(style), float(z if np.isfinite(z) else 0.0)))

    # Regime series rows
    rrows: List[Tuple[int, float, float, float, float, float, str, float]] = []
    for as_of in wide.index:
        dk = dk_map.get(as_of.date())
        if dk is None:
            continue
        rrows.append(
            (
                dk,
                float(risk_on_core.loc[as_of]),
                float(risk_off_core.loc[as_of]),
                float(regime_raw.loc[as_of]),
                float(ema10.loc[as_of]),
                float(ema50.loc[as_of]),
                str(label[wide.index.get_loc(as_of)]),
                float(regime_index.loc[as_of]),
            )
        )

    # Upsert
    conn = psycopg2.connect(dsn)
    try:
        _upsert_style_z(conn, zrows, batch=batch_size)
        _upsert_regime_series(conn, rrows, batch=batch_size)
        print(f"Upserted {len(zrows)} style-z rows and {len(rrows)} regime rows")
    finally:
        conn.close()


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main():
    ap = argparse.ArgumentParser(description="Backfill regime series (US)")
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--days", type=int, default=600, help="Number of most-recent trading days to backfill"
    )
    g.add_argument(
        "--window",
        nargs=2,
        metavar=("START", "END"),
        help="Explicit date window YYYY-MM-DD YYYY-MM-DD",
    )
    ap.add_argument(
        "--no-refresh", action="store_true", help="Skip MV refresh before reading intensities"
    )
    ap.add_argument("--batch-size", type=int, default=5000, help="Batch size for bulk upserts")
    args = ap.parse_args()

    days = None
    start = end = None
    if args.window:
        start = _parse_date(args.window[0])
        end = _parse_date(args.window[1])
    else:
        days = int(args.days)

    backfill(
        days=days,
        start=start,
        end=end,
        refresh=(not args.no_refresh),
        batch_size=int(args.batch_size),
    )


if __name__ == "__main__":
    main()
