from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from sqlalchemy import bindparam, create_engine, text

from apps.common.src.logging import get_logger

DERIVED_SERIES = [
    "US_NYA_HINDENBURG_OMEN_RAW",
    "US_NYA_HINDENBURG_OMEN_CONFIRMED",
    "US_NYSE_HLLI",
    "US_SPX_NET_NEW_HIGHS",
    "US_NDX_NET_NEW_HIGHS",
    "US_SPX_WHALEY_ADT5",
    "US_SPX_WHALEY_ADT5_BULL_FLAG",
    "US_SPX_WHALEY_ADT5_CAPITULATION_FLAG",
    "US_NDX_WHALEY_ADT5",
    "US_NDX_WHALEY_ADT5_BULL_FLAG",
    "US_NDX_WHALEY_ADT5_CAPITULATION_FLAG",
    "US_SPX_BAM10_UP_FLAG",
    "US_SPX_BAM10_DOWN_FLAG",
    "US_NDX_BAM10_UP_FLAG",
    "US_NDX_BAM10_DOWN_FLAG",
    "US_SPX_MCCLELLAN_THRUST_FLAG",
    "US_NDX_MCCLELLAN_THRUST_FLAG",
    "US_SPX_MCCLELLAN_SUM_BREAKDOWN_FLAG",
    "US_NDX_MCCLELLAN_SUM_BREAKDOWN_FLAG",
    "US_NYSE_PERSISTENT_NEW_LOWS_FLAG",
    "US_SPX_PERSISTENT_NEW_LOWS_FLAG",
    "US_NDX_PERSISTENT_NEW_LOWS_FLAG",
    "US_SPX_PCT_ABOVE_200D_THRUST_FLAG",
    "US_SPX_PCT_BELOW_200D_COLLAPSE_FLAG",
    "US_NDX_PCT_ABOVE_200D_THRUST_FLAG",
    "US_NDX_PCT_BELOW_200D_COLLAPSE_FLAG",
    "US_SPX_TRIN_STRESS_FLAG",
    "US_NDX_TRIN_STRESS_FLAG",
    "US_NYSE_TRIN_STRESS_FLAG",
    "US_SPX_AD_BEARISH_DIVERGENCE_FLAG",
    "US_NDX_AD_BEARISH_DIVERGENCE_FLAG",
]


@dataclass(frozen=True)
class UniverseCfg:
    name: str
    hi: str
    lo: str
    adv: str
    dec: str
    unc: Optional[str]
    ad_line: Optional[str]
    mco: Optional[str]
    mcsum: Optional[str]
    trin: Optional[str]
    pct_ma200: Optional[str]
    price_candidates: Sequence[str]


UNIVERSES: List[UniverseCfg] = [
    UniverseCfg(
        name="SPX",
        hi="#SPX52WHI",
        lo="#SPX52WLO",
        adv="#SPXADV",
        dec="#SPXDEC",
        unc="#SPXUNC",
        ad_line="#SPXAD",
        mco="#SPXMCOSC",
        mcsum="#SPXMCSUM",
        trin="#SPXTRIN",
        pct_ma200="#SPX%MA200",
        price_candidates=("S&P 500", "S&P 500 Index", "SPX", "^GSPC", "$SPX"),
    ),
    UniverseCfg(
        name="NDX",
        hi="#NDX52WHI",
        lo="#NDX52WLO",
        adv="#NDXADV",
        dec="#NDXDEC",
        unc="#NDXUNC",
        ad_line="#NDXAD",
        mco="#NDXMCOSC",
        mcsum="#NDXMCSUM",
        trin="#NDXTRIN",
        pct_ma200="#NDX%MA200",
        price_candidates=("Nasdaq 100", "Nasdaq-100", "NDX", "$NDX", "^NDX"),
    ),
]

# Exchange-level inputs (used for Hindenburg, HLLI, TRIN stress, persistent lows)
NYSE_CFG = UniverseCfg(
    name="NYSE",
    hi="#NYSEHI",
    lo="#NYSELO",
    adv="#NYSEADV",
    dec="#NYSEDEC",
    unc="#NYSEUNC",
    ad_line=None,
    mco="#NYAMCOSC",
    mcsum="#NYAMCSUM",
    trin="#NYSETRIN",
    pct_ma200="#NYA%MA200",
    price_candidates=(),
)

# Hindenburg uses NYSE highs/lows plus %MA50 proxy for trend (no price lookup)
NYA_PRICE_CANDIDATES: tuple[str, ...] = ()


class BreadthJob:
    """Computes derived market breadth indicators and persists them."""

    def __init__(
        self,
        settings,
        logger=None,
        db_factory: Callable[[], "psycopg2.extensions.connection"] | None = None,
    ):
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for BreadthJob")
        self._settings = settings
        self._logger = logger or get_logger(__name__)
        self._db_factory = db_factory
        self._engine = create_engine(
            f"postgresql+psycopg2://{settings.db_username}:{settings.password}@{settings.host}:{settings.port}/{settings.database_name}"
        )

    # ------------------------------------------------------------------ public
    def refresh(
        self, *, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> None:
        conn = self._db_factory()
        try:
            source_key = self._ensure_source(conn)
            raw = self._load_raw_series(conn, start_date=start_date, end_date=end_date)
            prices = self._load_price_series(conn, start_date=start_date, end_date=end_date)

            outputs: Dict[str, pd.Series] = {}

            # Hindenburg & HLLI (NYSE / NYA)
            self._compute_hindenburg(raw, prices, outputs)
            self._compute_hlli(raw, outputs)
            self._compute_persistent_new_lows(
                raw, outputs, universe=NYSE_CFG, series_code="US_NYSE_PERSISTENT_NEW_LOWS_FLAG"
            )
            self._compute_trin_stress(
                raw, outputs, universe=NYSE_CFG, series_code="US_NYSE_TRIN_STRESS_FLAG"
            )

            # SPX / NDX families
            for uni in UNIVERSES:
                self._compute_net_new_highs(raw, outputs, uni)
                self._compute_whaley(raw, outputs, uni)
                self._compute_bam(raw, outputs, uni)
                self._compute_mcclellan_thrusts(raw, outputs, uni)
                self._compute_persistent_new_lows(
                    raw,
                    outputs,
                    universe=uni,
                    series_code=f"US_{uni.name}_PERSISTENT_NEW_LOWS_FLAG",
                )
                self._compute_pct_ma_thrusts(raw, outputs, uni)
                self._compute_trin_stress(
                    raw, outputs, universe=uni, series_code=f"US_{uni.name}_TRIN_STRESS_FLAG"
                )
                self._compute_ad_divergence(raw, prices, outputs, uni)

            if not outputs:
                self._logger.info("BreadthJob: no outputs produced (missing inputs?)")
                return

            df_out = pd.DataFrame(outputs)
            df_out.sort_index(inplace=True)
            df_out = df_out.dropna(how="all")
            if df_out.empty:
                self._logger.info("BreadthJob: nothing to write after dropping empty rows")
                return

            # Regime layer (SPX, NDX) – uses existing derived columns and price series
            regime_out = self._compute_regime_layers(df_out, prices)
            if regime_out is not None and not regime_out.empty:
                df_out = df_out.join(regime_out, how="outer")

            self._upsert(conn, df_out, source_key)
            self._logger.info(
                "BreadthJob: upserted %d rows x %d series (dates %s to %s)",
                df_out.shape[0],
                df_out.shape[1],
                df_out.index.min().date()
                if isinstance(df_out.index.min(), pd.Timestamp)
                else df_out.index.min(),
                df_out.index.max().date()
                if isinstance(df_out.index.max(), pd.Timestamp)
                else df_out.index.max(),
            )
        finally:
            conn.close()

    # ----------------------------------------------------------------- loaders
    def _ensure_source(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rankalpha.dim_source (source_name, version, exclude_from_screener, screener_weight) "
                "VALUES (%s, '1', false, 1.0) "
                "ON CONFLICT (source_name) DO NOTHING",
                ("RankAlphaDerived",),
            )
            conn.commit()
            cur.execute(
                "SELECT source_key FROM rankalpha.dim_source WHERE source_name = %s",
                ("RankAlphaDerived",),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Could not resolve source_key for RankAlphaDerived")
            return int(row[0])

    def _load_raw_series(
        self, conn, *, start_date: Optional[date], end_date: Optional[date]
    ) -> pd.DataFrame:
        needed: set[str] = set()
        for uni in UNIVERSES + [NYSE_CFG]:
            needed.update([uni.hi, uni.lo, uni.adv, uni.dec])
            if uni.unc:
                needed.add(uni.unc)
            if uni.ad_line:
                needed.add(uni.ad_line)
            if uni.mco:
                needed.add(uni.mco)
            if uni.mcsum:
                needed.add(uni.mcsum)
            if uni.trin:
                needed.add(uni.trin)
            if uni.pct_ma200:
                needed.add(uni.pct_ma200)
        # For Hindenburg trend proxy (NYA %MA50)
        needed.add("#NYA%MA50")

        stmt = text(
            """
            SELECT d.full_date, m.series_code, f.value
            FROM rankalpha.fact_macro_series f
            JOIN rankalpha.dim_macro_series m ON m.series_key = f.series_key
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE m.series_code IN :codes
            AND (:start_date IS NULL OR d.full_date >= :start_date)
            AND (:end_date IS NULL OR d.full_date <= :end_date)
            ORDER BY d.full_date ASC
            """
        ).bindparams(bindparam("codes", expanding=True))

        params = {
            "codes": list(needed),
            "start_date": start_date,
            "end_date": end_date,
        }
        df = pd.read_sql(stmt, self._engine, params=params, parse_dates=["full_date"])
        if df.empty:
            self._logger.warning("BreadthJob: no raw breadth series found; skipping")
            return pd.DataFrame()
        pivot = df.pivot(index="full_date", columns="series_code", values="value").sort_index()
        return pivot

    def _load_price_series(
        self, conn, *, start_date: Optional[date], end_date: Optional[date]
    ) -> Dict[str, pd.Series]:
        """Return dict of universe name -> price series (pd.Series indexed by date)."""
        out: Dict[str, pd.Series] = {}
        for uni in UNIVERSES:
            ser = self._fetch_price(conn, uni.price_candidates, start_date, end_date)
            if ser is not None:
                out[uni.name] = ser
        # NYA for Hindenburg
        nya_price = self._fetch_price(conn, NYA_PRICE_CANDIDATES, start_date, end_date)
        if nya_price is not None:
            out["NYA"] = nya_price
        return out

    def _fetch_price(
        self,
        conn,
        candidates: Sequence[str],
        start_date: Optional[date],
        end_date: Optional[date],
    ) -> Optional[pd.Series]:
        if not candidates:
            return None
        params = {
            "cands": list(candidates),
            "start_date": start_date,
            "end_date": end_date,
        }
        stmt_bench = text(
            """
            SELECT d.full_date, f.close_px
            FROM rankalpha.fact_benchmark_price f
            JOIN rankalpha.dim_benchmark b ON b.benchmark_key = f.benchmark_key
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE b.benchmark_name IN :cands
            AND (:start_date IS NULL OR d.full_date >= :start_date)
            AND (:end_date IS NULL OR d.full_date <= :end_date)
            ORDER BY d.full_date ASC
            """
        ).bindparams(bindparam("cands", expanding=True))

        df = pd.read_sql(stmt_bench, self._engine, params=params, parse_dates=["full_date"])
        if not df.empty:
            ser = df.set_index("full_date")["close_px"].astype(float)
            return ser

        # Fallback: dim_stock + fact_security_price
        stmt_stock = text(
            """
            SELECT d.full_date, f.close_px
            FROM rankalpha.fact_security_price f
            JOIN rankalpha.dim_stock s ON s.stock_key = f.stock_key
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE s.symbol IN :cands
            AND (:start_date IS NULL OR d.full_date >= :start_date)
            AND (:end_date IS NULL OR d.full_date <= :end_date)
            ORDER BY d.full_date ASC
            """
        ).bindparams(bindparam("cands", expanding=True))

        df2 = pd.read_sql(stmt_stock, self._engine, params=params, parse_dates=["full_date"])
        if df2.empty:
            self._logger.warning("BreadthJob: no price series found for candidates %s", candidates)
            return None
        return df2.set_index("full_date")["close_px"].astype(float)

    # -------------------------------------------------------------- computation
    def _compute_hindenburg(
        self, raw: pd.DataFrame, prices: Dict[str, pd.Series], outputs: Dict[str, pd.Series]
    ) -> None:
        required = ["#NYSEHI", "#NYSELO", "#NYSEADV", "#NYSEDEC", "#NYSEUNC", "#NYAMCOSC"]
        if not set(required).issubset(raw.columns):
            self._logger.warning(
                "BreadthJob: missing inputs for Hindenburg; required=%s missing=%s",
                required,
                set(required) - set(raw.columns),
            )
            return

        df = raw[required].copy()
        df["issues"] = df["#NYSEADV"] + df["#NYSEDEC"] + df["#NYSEUNC"]
        df = df[df["issues"] > 0]
        if df.empty:
            return

        df["pct_hi"] = df["#NYSEHI"] / df["issues"]
        df["pct_lo"] = df["#NYSELO"] / df["issues"]
        df["cond_pct"] = (df["pct_hi"] >= 0.022) & (df["pct_lo"] >= 0.022)
        df["cond_hi_vs_lo"] = df["#NYSEHI"] <= 2 * df["#NYSELO"]
        df["cond_mco"] = df["#NYAMCOSC"] < 0

        # Trend filter: NYA %MA50 proxy (price not ingested)
        if "#NYA%MA50" in raw.columns:
            pct_ma50 = raw["#NYA%MA50"] / 100.0
            cond_pct = (pct_ma50 >= 0.5) & (pct_ma50 - pct_ma50.shift(10) >= 0)
            df["cond_uptrend"] = cond_pct.fillna(False)
        else:
            self._logger.warning(
                "BreadthJob: NYA %%MA50 missing; Hindenburg uptrend filter bypassed"
            )
            df["cond_uptrend"] = True

        df["omen_raw"] = (
            df["cond_pct"] & df["cond_hi_vs_lo"] & df["cond_mco"] & df["cond_uptrend"]
        ).astype(int)

        raw_series = df["omen_raw"]
        # Rolling forward 36 trading days including today: use reverse rolling to simulate forward window
        fwd_count = raw_series.iloc[::-1].rolling(window=36, min_periods=1).sum().iloc[::-1]
        confirmed = ((fwd_count >= 2) & (raw_series > 0)).astype(int)

        outputs["US_NYA_HINDENBURG_OMEN_RAW"] = raw_series
        outputs["US_NYA_HINDENBURG_OMEN_CONFIRMED"] = confirmed

    def _compute_hlli(self, raw: pd.DataFrame, outputs: Dict[str, pd.Series]) -> None:
        if not {"#NYSEHI", "#NYSELO", "#NYSEADV", "#NYSEDEC", "#NYSEUNC"}.issubset(raw.columns):
            self._logger.warning("BreadthJob: missing inputs for HLLI")
            return
        df = raw[["#NYSEHI", "#NYSELO", "#NYSEADV", "#NYSEDEC", "#NYSEUNC"]].copy()
        df["issues"] = df["#NYSEADV"] + df["#NYSEDEC"] + df["#NYSEUNC"]
        df = df[df["issues"] > 0]
        if df.empty:
            return
        df["pct_hi"] = df["#NYSEHI"] / df["issues"]
        df["pct_lo"] = df["#NYSELO"] / df["issues"]
        hlli = df[["pct_hi", "pct_lo"]].min(axis=1) * 100.0
        outputs["US_NYSE_HLLI"] = hlli

    def _compute_net_new_highs(
        self, raw: pd.DataFrame, outputs: Dict[str, pd.Series], uni: UniverseCfg
    ) -> None:
        cols = [uni.hi, uni.lo, uni.adv, uni.dec]
        if not set(cols).issubset(raw.columns):
            self._logger.warning("BreadthJob: missing inputs for net new highs (%s)", uni.name)
            return
        df = raw[[uni.hi, uni.lo, uni.adv, uni.dec]].copy()
        if uni.unc and uni.unc in raw.columns:
            df["unc"] = raw[uni.unc]
        else:
            df["unc"] = 0.0
        df["issues"] = df[uni.adv] + df[uni.dec] + df["unc"]
        df = df[df["issues"] > 0]
        if df.empty:
            return
        net_new = (df[uni.hi] - df[uni.lo]) / df["issues"]
        outputs[f"US_{uni.name}_NET_NEW_HIGHS"] = net_new

    def _compute_whaley(
        self, raw: pd.DataFrame, outputs: Dict[str, pd.Series], uni: UniverseCfg
    ) -> None:
        cols = [uni.adv, uni.dec]
        if not set(cols).issubset(raw.columns):
            self._logger.warning("BreadthJob: missing inputs for Whaley ADT5 (%s)", uni.name)
            return
        df = raw[cols].copy()
        df["sum_adv_dec"] = df[uni.adv] + df[uni.dec]
        df = df[df["sum_adv_dec"] > 0]
        if df.empty:
            return
        adt5 = (
            df[uni.adv].rolling(window=5, min_periods=5).sum()
            / df["sum_adv_dec"].rolling(window=5, min_periods=5).sum()
        )
        outputs[f"US_{uni.name}_WHALEY_ADT5"] = adt5
        outputs[f"US_{uni.name}_WHALEY_ADT5_BULL_FLAG"] = (adt5 >= 0.7366).astype(int)
        outputs[f"US_{uni.name}_WHALEY_ADT5_CAPITULATION_FLAG"] = (adt5 <= 0.1905).astype(int)

    def _compute_bam(
        self, raw: pd.DataFrame, outputs: Dict[str, pd.Series], uni: UniverseCfg
    ) -> None:
        cols = [uni.adv, uni.dec]
        if not set(cols).issubset(raw.columns):
            self._logger.warning("BreadthJob: missing inputs for BAM (%s)", uni.name)
            return
        df = raw[cols].copy()
        adv10 = df[uni.adv].rolling(window=10, min_periods=10).sum()
        dec10 = df[uni.dec].rolling(window=10, min_periods=10).sum()
        outputs[f"US_{uni.name}_BAM10_UP_FLAG"] = (adv10 >= 1.97 * dec10).astype(int)
        outputs[f"US_{uni.name}_BAM10_DOWN_FLAG"] = (dec10 >= 1.97 * adv10).astype(int)

    def _compute_mcclellan_thrusts(
        self, raw: pd.DataFrame, outputs: Dict[str, pd.Series], uni: UniverseCfg
    ) -> None:
        if uni.mco not in raw.columns:
            self._logger.warning("BreadthJob: missing McClellan Oscillator for %s", uni.name)
            return
        mco = raw[uni.mco]
        # Thrust: within 10-day window min<-100 and max>+100
        min10 = mco.rolling(window=10, min_periods=10).min()
        max10 = mco.rolling(window=10, min_periods=10).max()
        thrust = ((min10 < -100) & (max10 > 100)).astype(int)
        outputs[f"US_{uni.name}_MCCLELLAN_THRUST_FLAG"] = thrust

        if uni.mcsum and uni.mcsum in raw.columns:
            mcsum = raw[uni.mcsum]
            breakdown = ((mcsum.shift(1) > 0) & (mcsum <= 0)).astype(int)
            outputs[f"US_{uni.name}_MCCLELLAN_SUM_BREAKDOWN_FLAG"] = breakdown

    def _compute_persistent_new_lows(
        self,
        raw: pd.DataFrame,
        outputs: Dict[str, pd.Series],
        *,
        universe: UniverseCfg,
        series_code: str,
    ) -> None:
        cols = [universe.lo, universe.adv, universe.dec]
        if not set(cols).issubset(raw.columns):
            self._logger.warning(
                "BreadthJob: missing inputs for persistent new lows (%s)", universe.name
            )
            return
        df = raw[[universe.lo, universe.adv, universe.dec]].copy()
        if universe.unc and universe.unc in raw.columns:
            df["unc"] = raw[universe.unc]
        else:
            df["unc"] = 0.0
        df["issues"] = df[universe.adv] + df[universe.dec] + df["unc"]
        df = df[df["issues"] > 0]
        if df.empty:
            return
        pct_lo = df[universe.lo] / df["issues"]
        flag = (pct_lo >= 0.05).astype(int)
        persist = flag.rolling(window=3, min_periods=3).sum() >= 3
        outputs[series_code] = persist.astype(int)

    def _compute_pct_ma_thrusts(
        self, raw: pd.DataFrame, outputs: Dict[str, pd.Series], uni: UniverseCfg
    ) -> None:
        if not uni.pct_ma200 or uni.pct_ma200 not in raw.columns:
            self._logger.warning("BreadthJob: missing %%MA200 for %s", uni.name)
            return
        pct = raw[uni.pct_ma200] / 100.0  # stored as percent (0-100)
        delta10 = pct - pct.shift(10)
        thrust = (delta10 >= 0.20).astype(int)
        collapse = ((1 - pct) - (1 - pct.shift(10)) >= 0.20).astype(int)
        outputs[f"US_{uni.name}_PCT_ABOVE_200D_THRUST_FLAG"] = thrust
        outputs[f"US_{uni.name}_PCT_BELOW_200D_COLLAPSE_FLAG"] = collapse

    def _compute_trin_stress(
        self,
        raw: pd.DataFrame,
        outputs: Dict[str, pd.Series],
        *,
        universe: UniverseCfg,
        series_code: str,
    ) -> None:
        if not universe.trin or universe.trin not in raw.columns:
            self._logger.warning("BreadthJob: missing TRIN for %s", universe.name)
            return
        trin = raw[universe.trin]
        ema = trin.ewm(span=3, adjust=False, min_periods=3).mean()
        stress_raw = ema > 1.2
        stress = stress_raw.rolling(window=3, min_periods=3).sum() == 3
        outputs[series_code] = stress.astype(int)

    def _compute_ad_divergence(
        self,
        raw: pd.DataFrame,
        prices: Dict[str, pd.Series],
        outputs: Dict[str, pd.Series],
        uni: UniverseCfg,
    ) -> None:
        if not uni.ad_line or uni.ad_line not in raw.columns:
            self._logger.warning("BreadthJob: missing A/D line for %s", uni.name)
            return
        price = prices.get(uni.name)
        if price is None:
            self._logger.warning(
                "BreadthJob: missing price series for %s; AD divergence skipped", uni.name
            )
            return

        ad_line = raw[uni.ad_line]
        # align price to ad_line index
        price_aligned = price.reindex(ad_line.index).ffill()
        price_high = price_aligned.rolling(window=60, min_periods=1).max()
        ad_high = ad_line.rolling(window=60, min_periods=1).max()
        flag = ((price_aligned >= price_high) & (ad_line < ad_high)).astype(int)
        outputs[f"US_{uni.name}_AD_BEARISH_DIVERGENCE_FLAG"] = flag

    def _compute_regime_layers(
        self, df: pd.DataFrame, prices: Dict[str, pd.Series]
    ) -> Optional[pd.DataFrame]:
        """Compute thrust/frag/net scores and regime state/exposure for SPX and NDX."""
        cfg = RegimeConfig()

        def regime_for(universe: str) -> Optional[pd.DataFrame]:
            prefix = f"US_{universe}_"
            cols_needed = [
                f"{prefix}WHALEY_ADT5_BULL_FLAG",
                f"{prefix}BAM10_UP_FLAG",
                f"{prefix}MCCLELLAN_THRUST_FLAG",
                f"{prefix}PCT_ABOVE_200D_THRUST_FLAG",
                f"{prefix}NET_NEW_HIGHS",
                f"{prefix}BAM10_DOWN_FLAG",
                f"{prefix}PERSISTENT_NEW_LOWS_FLAG",
                f"{prefix}PCT_BELOW_200D_COLLAPSE_FLAG",
                f"{prefix}MCCLELLAN_SUM_BREAKDOWN_FLAG",
                f"{prefix}TRIN_STRESS_FLAG",
                f"{prefix}AD_BEARISH_DIVERGENCE_FLAG",
            ]
            missing = [c for c in cols_needed if c not in df.columns]
            if missing:
                self._logger.warning(
                    "BreadthJob: regime skipped for %s; missing %s", universe, missing
                )
                return None

            # base signals
            signals = df[cols_needed].copy()
            signals = signals.fillna(0)

            # global / shared signals
            hinden = df.get("US_NYA_HINDENBURG_OMEN_CONFIRMED", 0).fillna(0)
            hlli = df.get("US_NYSE_HLLI", 0)
            hlli_cut = hlli.quantile(cfg.hlli_q) if not hlli.dropna().empty else None
            hlli_extreme = (
                (hlli >= hlli_cut) if hlli_cut is not None else pd.Series(False, index=df.index)
            )
            trin_stress = signals[f"{prefix}TRIN_STRESS_FLAG"].astype(bool)
            if "US_NYSE_TRIN_STRESS_FLAG" in df.columns:
                trin_stress = trin_stress | df["US_NYSE_TRIN_STRESS_FLAG"].astype(bool)

            net_new = df[f"{prefix}NET_NEW_HIGHS"].astype(float)
            nnh_z = _zscore_expanding(net_new.fillna(0.0))

            # trend gate
            trend_up = pd.Series(True, index=df.index)
            price = prices.get(universe)
            if cfg.apply_trend_gate and price is not None:
                px = price.reindex(df.index).ffill()
                ma = px.rolling(cfg.trend_ma_days, min_periods=cfg.trend_ma_days).mean()
                trend_up = px >= ma

            # thrust points
            thrust_pts = (
                cfg.w_adt5_bull * signals[f"{prefix}WHALEY_ADT5_BULL_FLAG"].astype(bool).astype(int)
                + cfg.w_bam10_up * signals[f"{prefix}BAM10_UP_FLAG"].astype(bool).astype(int)
                + cfg.w_mcc_thrust_hi
                * signals[f"{prefix}MCCLELLAN_THRUST_FLAG"].astype(bool).astype(int)
                + cfg.w_pct_gt_200_thrust
                * signals[f"{prefix}PCT_ABOVE_200D_THRUST_FLAG"].astype(bool).astype(int)
                + cfg.w_nnh_pos * (nnh_z >= cfg.nnh_z_hi).astype(int)
            ).astype(float)

            # fragility points
            # A/D divergence weight per universe
            ad_weight = cfg.w_ad_bear_div_spx if universe == "SPX" else cfg.w_ad_bear_div_ndx

            frag_pts = (
                cfg.w_hinden_confirmed * hinden.astype(bool).astype(int)
                + cfg.w_hlli_extreme * hlli_extreme.astype(int)
                + cfg.w_bam10_down * signals[f"{prefix}BAM10_DOWN_FLAG"].astype(bool).astype(int)
                + cfg.w_new_lows_persist
                * signals[f"{prefix}PERSISTENT_NEW_LOWS_FLAG"].astype(bool).astype(int)
                + cfg.w_pct_lt_200_collapse
                * signals[f"{prefix}PCT_BELOW_200D_COLLAPSE_FLAG"].astype(bool).astype(int)
                + cfg.w_mcc_sum_break
                * signals[f"{prefix}MCCLELLAN_SUM_BREAKDOWN_FLAG"].astype(bool).astype(int)
                + cfg.w_trin_stress * trin_stress.astype(int)
                + ad_weight
                * signals[f"{prefix}AD_BEARISH_DIVERGENCE_FLAG"].astype(bool).astype(int)
                + cfg.w_nnh_neg * (nnh_z <= cfg.nnh_z_lo).astype(int)
            ).astype(float)

            thrust_score = _ewm_half_life(thrust_pts, cfg.half_life_days)
            frag_score = _ewm_half_life(frag_pts, cfg.half_life_days)

            thrust_z = pd.to_numeric(
                _zscore_expanding(thrust_score.fillna(0.0)), errors="coerce"
            ).fillna(0.0)
            frag_z = pd.to_numeric(
                _zscore_expanding(frag_score.fillna(0.0)), errors="coerce"
            ).fillna(0.0)
            net_score = (thrust_z - frag_z).fillna(0.0)

            # hysteresis regime
            state_list = []
            cur = 0
            hold = 0
            for idx, val in net_score.items():
                trend_ok = trend_up.loc[idx] if idx in trend_up.index else True
                if cur == 0:
                    if (val >= cfg.enter_on) and trend_ok:
                        cur, hold = 1, cfg.min_state_days
                    elif val <= cfg.enter_off:
                        cur, hold = -1, cfg.min_state_days
                elif cur == 1:
                    if hold > 0:
                        hold -= 1
                    elif (val < cfg.hold_band) or (not trend_ok):
                        cur = 0 if val > 0 else -1 if (val <= cfg.enter_off) else 0
                else:  # cur == -1
                    if hold > 0:
                        hold -= 1
                    elif (val > -cfg.hold_band) and trend_ok:
                        cur = 0 if val < 0 else 1 if (val >= cfg.enter_on and trend_ok) else 0
                state_list.append(cur)

            state = pd.Series(state_list, index=net_score.index)
            exposure = 1 / (1 + np.exp(-net_score.clip(-5, 5)))
            exposure = exposure.where(state >= 0, 0.0)

            return pd.DataFrame(
                {
                    f"US_{universe}_BREADTH_THRUST_SCORE": thrust_score,
                    f"US_{universe}_BREADTH_FRAG_SCORE": frag_score,
                    f"US_{universe}_BREADTH_NET_SCORE": net_score,
                    f"US_{universe}_BREADTH_REGIME_STATE": state,
                    f"US_{universe}_BREADTH_TARGET_EXPOSURE": exposure,
                }
            )

        frames = []
        for uni in ("SPX", "NDX"):
            res = regime_for(uni)
            if res is not None:
                frames.append(res)
        if not frames:
            return None
        return pd.concat(frames, axis=1)

    # --------------------------------------------------------------- persistence
    def _upsert(self, conn, df: pd.DataFrame, source_key: int) -> None:
        if df.empty:
            return
        series_codes = list(df.columns)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT series_code, series_key FROM rankalpha.dim_macro_series WHERE series_code = ANY(%s)",
                (series_codes,),
            )
            mapping = {row[0]: int(row[1]) for row in cur.fetchall()}
        missing = set(series_codes) - set(mapping.keys())
        if missing:
            raise RuntimeError(f"Missing dim_macro_series rows for: {sorted(missing)}")

        # date_key lookup for needed dates
        dates = [d.date() if isinstance(d, pd.Timestamp) else d for d in df.index]
        min_d, max_d = min(dates), max(dates)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT date_key, full_date FROM rankalpha.dim_date WHERE full_date BETWEEN %s AND %s",
                (min_d, max_d),
            )
            date_map = {row[1]: int(row[0]) for row in cur.fetchall()}
        missing_dates = [d for d in set(dates) if d not in date_map]
        if missing_dates:
            raise RuntimeError(f"Missing dim_date rows for: {sorted(missing_dates)}")

        records: List[tuple] = []
        for idx, row in df.iterrows():
            as_of = idx.date() if isinstance(idx, pd.Timestamp) else idx
            date_key = date_map[as_of]
            for series_code, value in row.items():
                if pd.isna(value):
                    continue
                records.append((date_key, mapping[series_code], source_key, float(value)))
        if not records:
            return

        sql = """
            INSERT INTO rankalpha.fact_macro_series (date_key, series_key, source_key, value)
            VALUES %s
            ON CONFLICT (date_key, series_key)
            DO UPDATE SET value = EXCLUDED.value, source_key = EXCLUDED.source_key, load_ts = now()
        """
        with conn.cursor() as cur:
            execute_values(cur, sql, records, page_size=500)
        conn.commit()


@dataclass(frozen=True)
class RegimeConfig:
    w_adt5_bull: float = 3.0
    w_bam10_up: float = 3.0
    w_mcc_thrust_hi: float = 2.0
    w_pct_gt_200_thrust: float = 2.0
    w_nnh_pos: float = 1.0

    w_hinden_confirmed: float = 3.0
    w_hlli_extreme: float = 2.0
    w_bam10_down: float = 3.0
    w_new_lows_persist: float = 2.0
    w_pct_lt_200_collapse: float = 2.0
    w_mcc_sum_break: float = 2.0
    w_trin_stress: float = 1.5
    w_ad_bear_div_spx: float = 1.0
    w_ad_bear_div_ndx: float = 1.0
    w_nnh_neg: float = 1.0

    mcc_thrust_up: float = 60.0
    nnh_z_hi: float = 1.5
    nnh_z_lo: float = -1.5
    hlli_q: float = 0.95
    trin_persist_days: int = 1

    half_life_days: int = 10
    enter_on: float = 2.0
    enter_off: float = -2.0
    hold_band: float = 0.5
    min_state_days: int = 10
    apply_trend_gate: bool = True
    trend_ma_days: int = 200


def _zscore_expanding(s: pd.Series) -> pd.Series:
    mu = s.expanding().mean()
    sd = s.expanding().std().replace(0, pd.NA)
    return (s - mu) / sd


def _ewm_half_life(series: pd.Series, half_life_days: int) -> pd.Series:
    alpha = 1 - 0.5 ** (1 / max(1, half_life_days))
    return series.ewm(alpha=alpha, adjust=False).mean()
