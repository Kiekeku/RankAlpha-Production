from __future__ import annotations

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import bindparam, create_engine, text

DEFAULT_UNDERLYING = "SPX/VIX"
BENCHMARK_NAMES = ["$VIX1D", "$VIX9D", "$VIX", "$VIX3M", "$VIX6M", "$VIX1Y"]
REQUIRED_COLS = ["VIX1D", "VIX9D", "VIX", "VIX3M", "VIX6M", "VIX1Y"]


def _to_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, np.generic):
            return float(value.item())
        return float(value)
    except Exception:
        return None


class VixTermStructureService:
    """Build and persist VIX term structure + regime classification."""

    def __init__(self, dsn: str, logger, settings) -> None:
        self.dsn = dsn
        self.logger = logger
        self.settings = settings
        self.engine = create_engine(dsn)

        self.window = int(getattr(settings, "scoring_vix_window_days", 750) or 750)
        self.calm_pct = float(getattr(settings, "scoring_vix_calm_pct", 0.30) or 0.30)
        self.stress_pct = float(getattr(settings, "scoring_vix_stress_pct", 0.70) or 0.70)
        self.panic_pct = float(getattr(settings, "scoring_vix_panic_pct", 0.90) or 0.90)
        self.ffill_limit = int(getattr(settings, "scoring_vix_ffill_limit", 2) or 0)

    # ---------------------------- Data loading --------------------------- #
    def load_benchmark_prices(self) -> pd.DataFrame:
        """Load the six VIX tenors from fact_benchmark_price -> wide DataFrame."""
        stmt = text(
            """
                SELECT d.full_date, d.date_key, b.benchmark_name, f.close_px
                FROM rankalpha.fact_benchmark_price f
                JOIN rankalpha.dim_benchmark b ON b.benchmark_key = f.benchmark_key
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE b.benchmark_name IN :names
                """
        ).bindparams(bindparam("names", expanding=True))
        df = pd.read_sql_query(
            stmt, self.engine, params={"names": BENCHMARK_NAMES}, parse_dates=["full_date"]
        )
        if df.empty:
            self.logger.warning(
                "VIX term structure: no benchmark prices found for required symbols"
            )
            return pd.DataFrame()

        self.logger.info(
            "VIX term structure: loaded %s rows (%s to %s)",
            len(df),
            df["full_date"].min().date() if not df.empty else None,
            df["full_date"].max().date() if not df.empty else None,
        )

        # Pivot to wide form with one row per date
        wide = (
            df.pivot_table(
                index=["full_date", "date_key"],
                columns="benchmark_name",
                values="close_px",
                aggfunc="last",
            )
            .reset_index()
            .sort_values("full_date")
        )
        # Normalize column names (strip '$')
        wide.columns = [c.lstrip("$") if isinstance(c, str) else c for c in wide.columns]
        wide = wide.set_index("full_date")

        # Preserve date_key separately
        date_key = wide.pop("date_key")

        # Forward-fill short gaps per tenor
        wide = wide.ffill(limit=self.ffill_limit)

        # Require all tenors present after ffill
        wide = wide[REQUIRED_COLS]
        mask = wide.notna().all(axis=1)
        wide = wide.loc[mask]
        date_key = date_key.loc[mask]

        wide["date_key"] = date_key.astype(int)
        return wide

    # ---------------------------- Feature building ----------------------- #
    def build_term_structure(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute levels, slopes, ratios, curve flags."""
        ts = pd.DataFrame(index=df.index)
        ts["date_key"] = df["date_key"]

        ts["vix_1d"] = df["VIX1D"].astype(float)
        ts["vix_9d"] = df["VIX9D"].astype(float)
        ts["vix_1m"] = df["VIX"].astype(float)
        ts["vix_3m"] = df["VIX3M"].astype(float)
        ts["vix_6m"] = df["VIX6M"].astype(float)
        ts["vix_1y"] = df["VIX1Y"].astype(float)

        ts["slope_1d_9d"] = ts["vix_9d"] - ts["vix_1d"]
        ts["slope_9d_1m"] = ts["vix_1m"] - ts["vix_9d"]
        ts["slope_1m_3m"] = ts["vix_3m"] - ts["vix_1m"]
        ts["slope_3m_6m"] = ts["vix_6m"] - ts["vix_3m"]
        ts["slope_6m_1y"] = ts["vix_1y"] - ts["vix_6m"]
        ts["curve_slope"] = ts["vix_1y"] - ts["vix_1d"]

        ts["ratio_1m_3m"] = ts["vix_1m"] / ts["vix_3m"]
        ts["ratio_1m_6m"] = ts["vix_1m"] / ts["vix_6m"]
        ts["ratio_3m_1y"] = ts["vix_3m"] / ts["vix_1y"]

        ts["is_contango_full"] = (
            (ts["vix_1d"] < ts["vix_9d"])
            & (ts["vix_9d"] < ts["vix_1m"])
            & (ts["vix_1m"] < ts["vix_3m"])
            & (ts["vix_3m"] < ts["vix_6m"])
            & (ts["vix_6m"] < ts["vix_1y"])
        )
        front_contango = (ts["vix_1d"] < ts["vix_9d"]) & (ts["vix_9d"] < ts["vix_1m"])
        mid_back_up = (
            (ts["slope_1m_3m"] > 0).astype(int)
            + (ts["slope_3m_6m"] > 0).astype(int)
            + (ts["slope_6m_1y"] > 0).astype(int)
        )
        ts["is_contango"] = front_contango & (mid_back_up >= 2)  # relaxed contango

        ts["is_backwardation_front"] = ts["vix_1m"] > ts["vix_3m"]
        ts["is_backwardation_short"] = ts["vix_9d"] > ts["vix_1m"]

        ts["num_inversions"] = (
            (ts["slope_1d_9d"] <= 0).astype(int)
            + (ts["slope_9d_1m"] <= 0).astype(int)
            + (ts["slope_1m_3m"] <= 0).astype(int)
            + (ts["slope_3m_6m"] <= 0).astype(int)
            + (ts["slope_6m_1y"] <= 0).astype(int)
        )
        return ts

    def classify_regime(self, ts: pd.DataFrame) -> pd.DataFrame:
        """Rolling percentile-based regimes (window defaults to 750 trading days)."""
        vix = ts["vix_1m"]
        hist = vix.shift(1)

        calm_thr = hist.rolling(self.window, min_periods=self.window).quantile(self.calm_pct)
        stress_thr = hist.rolling(self.window, min_periods=self.window).quantile(self.stress_pct)
        panic_thr = hist.rolling(self.window, min_periods=self.window).quantile(self.panic_pct)

        ready = (~calm_thr.isna()) & (~stress_thr.isna()) & (~panic_thr.isna())
        backwardation = ts["is_backwardation_front"] | ts["is_backwardation_short"]

        regime = pd.Series(index=ts.index, dtype=object)
        regime.loc[ready & (vix >= panic_thr) & backwardation] = "panic"
        regime.loc[ready & (regime.isna()) & (vix >= stress_thr) & backwardation] = "stressed"
        regime.loc[ready & (regime.isna()) & (vix <= calm_thr) & ts["is_contango"]] = "calm"
        regime.loc[ready & regime.isna()] = "neutral"
        regime.loc[~ready] = None

        ts["regime"] = regime
        ts["risk_flag"] = regime.map({"panic": 1, "stressed": 1, "calm": 0, "neutral": 0})
        return ts

    # ---------------------------- Persistence --------------------------- #
    def upsert(self, ts: pd.DataFrame, underlying_symbol: str = DEFAULT_UNDERLYING) -> int:
        if ts.empty:
            return 0

        cols = [
            "underlying_symbol",
            "date_key",
            "as_of_date",
            "vix_1d",
            "vix_9d",
            "vix_1m",
            "vix_3m",
            "vix_6m",
            "vix_1y",
            "slope_1d_9d",
            "slope_9d_1m",
            "slope_1m_3m",
            "slope_3m_6m",
            "slope_6m_1y",
            "curve_slope",
            "ratio_1m_3m",
            "ratio_1m_6m",
            "ratio_3m_1y",
            "num_inversions",
            "is_contango",
            "is_contango_full",
            "is_backwardation_front",
            "is_backwardation_short",
            "regime",
            "risk_flag",
        ]

        data = ts.copy()
        data["underlying_symbol"] = underlying_symbol
        data["as_of_date"] = data.index.normalize()

        bool_cols = {
            "is_contango",
            "is_contango_full",
            "is_backwardation_front",
            "is_backwardation_short",
        }

        records = []
        for row in data.reset_index(drop=True).to_dict(orient="records"):
            rec = []
            for c in cols:
                val = row.get(c)
                if c == "risk_flag":
                    rec.append(None if pd.isna(val) else int(val))
                elif c in ("underlying_symbol", "date_key", "as_of_date", "regime"):
                    rec.append(val)
                elif c in bool_cols:
                    rec.append(None if pd.isna(val) else bool(val))
                else:
                    rec.append(_to_float(val))
            records.append(tuple(rec))

        insert_sql = """
            INSERT INTO rankalpha.fact_vix_term_structure (
                underlying_symbol, date_key, as_of_date,
                vix_1d, vix_9d, vix_1m, vix_3m, vix_6m, vix_1y,
                slope_1d_9d, slope_9d_1m, slope_1m_3m, slope_3m_6m, slope_6m_1y, curve_slope,
                ratio_1m_3m, ratio_1m_6m, ratio_3m_1y,
                num_inversions,
                is_contango, is_contango_full, is_backwardation_front, is_backwardation_short,
                regime, risk_flag
            )
            VALUES %s
            ON CONFLICT (underlying_symbol, date_key) DO UPDATE SET
                as_of_date = EXCLUDED.as_of_date,
                vix_1d = EXCLUDED.vix_1d,
                vix_9d = EXCLUDED.vix_9d,
                vix_1m = EXCLUDED.vix_1m,
                vix_3m = EXCLUDED.vix_3m,
                vix_6m = EXCLUDED.vix_6m,
                vix_1y = EXCLUDED.vix_1y,
                slope_1d_9d = EXCLUDED.slope_1d_9d,
                slope_9d_1m = EXCLUDED.slope_9d_1m,
                slope_1m_3m = EXCLUDED.slope_1m_3m,
                slope_3m_6m = EXCLUDED.slope_3m_6m,
                slope_6m_1y = EXCLUDED.slope_6m_1y,
                curve_slope = EXCLUDED.curve_slope,
                ratio_1m_3m = EXCLUDED.ratio_1m_3m,
                ratio_1m_6m = EXCLUDED.ratio_1m_6m,
                ratio_3m_1y = EXCLUDED.ratio_3m_1y,
                num_inversions = EXCLUDED.num_inversions,
                is_contango = EXCLUDED.is_contango,
                is_contango_full = EXCLUDED.is_contango_full,
                is_backwardation_front = EXCLUDED.is_backwardation_front,
                is_backwardation_short = EXCLUDED.is_backwardation_short,
                regime = EXCLUDED.regime,
                risk_flag = EXCLUDED.risk_flag,
                updated_at = now()
        """

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, records, page_size=500)
        return len(records)

    # ---------------------------- Orchestration -------------------------- #
    def run(self, underlying_symbol: str = DEFAULT_UNDERLYING) -> int:
        prices = self.load_benchmark_prices()
        if prices.empty:
            return 0

        ts = self.build_term_structure(prices)
        ts = self.classify_regime(ts)
        upserted = self.upsert(ts, underlying_symbol=underlying_symbol)
        self.logger.info("VIX term structure upserted rows: %s", upserted)
        return upserted
