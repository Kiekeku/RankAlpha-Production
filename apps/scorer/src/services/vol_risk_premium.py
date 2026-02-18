from __future__ import annotations

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, text

DEFAULT_UNDERLYING = "SPX/VIX"


def _to_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, np.generic):
            return float(value.item())
        return float(value)
    except Exception:
        return None


class VolRiskPremiumService:
    """Compute and persist SPX realized vs VIX implied variance premium + regime."""

    def __init__(self, dsn: str, logger, settings) -> None:
        self.dsn = dsn
        self.logger = logger
        self.settings = settings
        self.engine = create_engine(dsn)

        self.trading_days = int(getattr(settings, "scoring_vrp_trading_days", 21) or 21)
        self.lookback = int(getattr(settings, "scoring_vrp_lookback_days", 252 * 3) or 252 * 3)
        self.vrp_low_pct = float(getattr(settings, "scoring_vrp_vrp_low_pct", 0.20) or 0.20)
        self.vrp_high_pct = float(getattr(settings, "scoring_vrp_vrp_high_pct", 0.80) or 0.80)
        self.vix_low_pct = float(getattr(settings, "scoring_vrp_vix_low_pct", 0.33) or 0.33)
        self.vix_high_pct = float(getattr(settings, "scoring_vrp_vix_high_pct", 0.66) or 0.66)
        self.ffill_limit = int(getattr(settings, "scoring_vix_ffill_limit", 2) or 0)

    # ---------------------------- Data loading --------------------------- #
    def load_spx_and_vix(self) -> pd.DataFrame:
        """Load SPX closes and VIX levels aligned by full_date."""
        spx_sql = text(
            """
            SELECT
                d.full_date,
                d.date_key,
                sp.open_px AS spx_open,
                sp.high_px AS spx_high,
                sp.low_px  AS spx_low,
                sp.close_px AS spx_close
            FROM rankalpha.fact_security_price sp
            JOIN rankalpha.dim_stock s ON s.stock_key = sp.stock_key
            JOIN rankalpha.dim_date d ON d.date_key = sp.date_key
            WHERE s.symbol = '$SPX'
            """
        )
        vix_sql = text(
            """
            SELECT d.full_date, d.date_key, f.close_px AS vix_close
            FROM rankalpha.fact_benchmark_price f
            JOIN rankalpha.dim_benchmark b ON b.benchmark_key = f.benchmark_key
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE b.benchmark_name = '$VIX'
            """
        )

        spx = pd.read_sql_query(spx_sql, self.engine, parse_dates=["full_date"])
        vix = pd.read_sql_query(vix_sql, self.engine, parse_dates=["full_date"])

        if spx.empty or vix.empty:
            self.logger.warning(
                "VRP: missing input data (spx=%s rows, vix=%s rows)", len(spx), len(vix)
            )
            return pd.DataFrame()

        spx = spx.sort_values("full_date").set_index("full_date")
        vix = vix.sort_values("full_date").set_index("full_date")

        # Keep date_key from SPX, align VIX by date
        df = spx[["date_key", "spx_open", "spx_high", "spx_low", "spx_close"]].join(
            vix[["vix_close"]], how="left"
        )

        # Forward-fill VIX up to configured limit
        if self.ffill_limit > 0:
            df["vix_close"] = df["vix_close"].ffill(limit=self.ffill_limit)

        # Drop rows with missing or non-positive closes. Some index inputs may not
        # have full OHLC available; compute_vrp() will fall back to close-to-close
        # variance in that case.
        df = df.dropna(subset=["spx_close", "vix_close"])
        df = df[(df[["spx_close", "vix_close"]] > 0).all(axis=1)]
        df["date_key"] = df["date_key"].astype(int)
        return df

    # ---------------------------- Computation --------------------------- #
    def compute_vrp(self, df: pd.DataFrame) -> pd.DataFrame:
        ts = df.copy()

        # Realized variance: prefer Rogers–Satchell when full OHLC is available,
        # otherwise fall back to close-to-close log-return variance so the VRP
        # table stays populated for index inputs that only provide closes.
        ts["rv_daily_var"] = np.nan

        ohlc_ok = ts[["spx_open", "spx_high", "spx_low", "spx_close"]].notna().all(axis=1)
        if bool(ohlc_ok.any()):
            log_ho = np.log(ts["spx_high"] / ts["spx_open"])
            log_hc = np.log(ts["spx_high"] / ts["spx_close"])
            log_lo = np.log(ts["spx_low"] / ts["spx_open"])
            log_lc = np.log(ts["spx_low"] / ts["spx_close"])
            ts.loc[ohlc_ok, "rv_daily_var"] = (log_ho * log_hc + log_lo * log_lc).loc[ohlc_ok]

        # Close-to-close fallback (uses prior close, so first row will be NaN)
        log_ret = np.log(ts["spx_close"] / ts["spx_close"].shift(1))
        ts.loc[~ohlc_ok, "rv_daily_var"] = (log_ret**2).loc[~ohlc_ok]

        ts["rv_30d_var"] = ts["rv_daily_var"].rolling(self.trading_days).sum()
        ts["iv_30d_var"] = (ts["vix_close"] / 100.0) ** 2 * (30.0 / 365.0)
        ts["vrp_30d"] = ts["iv_30d_var"] - ts["rv_30d_var"]

        ts = ts.dropna(subset=["rv_30d_var", "iv_30d_var", "vrp_30d"])
        return ts

    def classify_regime(self, ts: pd.DataFrame) -> pd.DataFrame:
        vrp = ts["vrp_30d"]
        vix = ts["vix_close"]

        ts["vrp_p20"] = vrp.rolling(self.lookback).quantile(self.vrp_low_pct)
        ts["vrp_p80"] = vrp.rolling(self.lookback).quantile(self.vrp_high_pct)
        ts["vix_p33"] = vix.rolling(self.lookback).quantile(self.vix_low_pct)
        ts["vix_p66"] = vix.rolling(self.lookback).quantile(self.vix_high_pct)

        def _label(row):
            vrp_val, vrp20, vrp80, vix_now, v33, v66 = row
            if pd.isna(vrp20) or pd.isna(vrp80) or pd.isna(v33) or pd.isna(v66):
                return None, None, None

            if vrp_val < vrp20:
                vrp_state = "low/negative"
            elif vrp_val > vrp80:
                vrp_state = "high/positive"
            else:
                vrp_state = "normal"

            if vix_now < v33:
                vol_state = "low"
            elif vix_now > v66:
                vol_state = "high"
            else:
                vol_state = "normal"

            if vol_state == "high" and vrp_state == "low/negative":
                regime = "crisis / panic"
            elif vol_state == "high" and vrp_state == "high/positive":
                regime = "stressed but hedged"
            elif vol_state == "low" and vrp_state == "high/positive":
                regime = "carry / complacency"
            elif vol_state == "low" and vrp_state == "low/negative":
                regime = "calm but fragile"
            else:
                regime = "neutral"

            return vrp_state, vol_state, regime

        labels = ts[["vrp_30d", "vrp_p20", "vrp_p80", "vix_close", "vix_p33", "vix_p66"]].apply(
            lambda r: _label(r), axis=1
        )
        ts["vrp_state"] = labels.apply(lambda t: t[0])
        ts["vol_state"] = labels.apply(lambda t: t[1])
        ts["vrp_regime"] = labels.apply(lambda t: t[2])
        return ts

    # ---------------------------- Persistence --------------------------- #
    def upsert(self, ts: pd.DataFrame, underlying_symbol: str = DEFAULT_UNDERLYING) -> int:
        if ts.empty:
            return 0

        cols = [
            "underlying_symbol",
            "date_key",
            "spx_close",
            "vix_close",
            "rv_30d_var",
            "iv_30d_var",
            "vrp_30d",
            "vrp_p20",
            "vrp_p80",
            "vix_p33",
            "vix_p66",
            "vrp_state",
            "vol_state",
            "vrp_regime",
        ]

        records = []
        data = ts.copy()
        data["underlying_symbol"] = underlying_symbol

        for row in data.reset_index(drop=True).to_dict(orient="records"):
            rec = []
            for c in cols:
                val = row.get(c)
                if c in {"underlying_symbol", "vrp_state", "vol_state", "vrp_regime"}:
                    rec.append(val)
                elif c == "date_key":
                    rec.append(int(val))
                else:
                    rec.append(_to_float(val))
            records.append(tuple(rec))

        insert_sql = """
            INSERT INTO rankalpha.fact_spx_vix_vrp (
                underlying_symbol, date_key,
                spx_close, vix_close,
                rv_30d_var, iv_30d_var, vrp_30d,
                vrp_p20, vrp_p80, vix_p33, vix_p66,
                vrp_state, vol_state, vrp_regime
            )
            VALUES %s
            ON CONFLICT (underlying_symbol, date_key) DO UPDATE SET
                spx_close   = EXCLUDED.spx_close,
                vix_close   = EXCLUDED.vix_close,
                rv_30d_var  = EXCLUDED.rv_30d_var,
                iv_30d_var  = EXCLUDED.iv_30d_var,
                vrp_30d     = EXCLUDED.vrp_30d,
                vrp_p20     = EXCLUDED.vrp_p20,
                vrp_p80     = EXCLUDED.vrp_p80,
                vix_p33     = EXCLUDED.vix_p33,
                vix_p66     = EXCLUDED.vix_p66,
                vrp_state   = EXCLUDED.vrp_state,
                vol_state   = EXCLUDED.vol_state,
                vrp_regime  = EXCLUDED.vrp_regime,
                updated_at  = now()
        """

        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, records, page_size=500)
        return len(records)

    # ---------------------------- Orchestration ------------------------- #
    def run(self, underlying_symbol: str = DEFAULT_UNDERLYING) -> int:
        df = self.load_spx_and_vix()
        if df.empty:
            return 0

        ts = self.compute_vrp(df)
        ts = self.classify_regime(ts)
        upserted = self.upsert(ts, underlying_symbol=underlying_symbol)
        self.logger.info("VRP %s upserted rows: %s", underlying_symbol, upserted)
        return upserted
