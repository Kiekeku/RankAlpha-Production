"""USDX / DXY regime computation and persistence."""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:  # pragma: no cover - align with other ingestion jobs
    psycopg2 = None
    execute_values = None

from apps.common.src.logging import get_logger
from apps.ingestion.src.settings import Settings

SERIES_CODES: Sequence[str] = (
    "US_DXY_LEVEL",
    "US_DXY_MA50",
    "US_DXY_MA100",
    "US_DXY_MA200",
    "US_DXY_ROC_1M",
    "US_DXY_ROC_3M",
    "US_DXY_ROC_6M",
    "US_DXY_Z_3Y",
    "US_DXY_PCTL_5Y",
    "US_DXY_REGIME_STATE",
    "US_DXY_SHOCK_UP_FLAG",
    "US_DXY_SHOCK_DOWN_FLAG",
    "US_DXY_RISK_SCORE",
)


class DxyRegimeJob:
    """Computes DXY regimes and derived features, writes to fact_macro_series."""

    def __init__(self, settings: Settings, logger=None, db_factory=None) -> None:
        if psycopg2 is None or execute_values is None:
            raise RuntimeError("psycopg2 is required for DxyRegimeJob but is not installed")
        self._settings = settings
        self._logger = logger or get_logger(__name__)
        self._db_factory = db_factory
        self._benchmark_name = getattr(settings, "ingestion_dxy_benchmark_name", "$USDX") or "$USDX"
        self._ma_days = int(getattr(settings, "ingestion_dxy_ma_days", 200) or 200)
        self._roc_1m_days = int(getattr(settings, "ingestion_dxy_roc_1m_days", 21) or 21)
        self._roc_3m_days = int(getattr(settings, "ingestion_dxy_roc_3m_days", 63) or 63)
        self._roc_6m_days = int(getattr(settings, "ingestion_dxy_roc_6m_days", 126) or 126)
        self._z_window = int(getattr(settings, "ingestion_dxy_z_window_days", 756) or 756)
        self._pct_window = int(getattr(settings, "ingestion_dxy_pct_window_days", 1260) or 1260)
        self._shock_threshold = float(
            getattr(settings, "ingestion_dxy_shock_threshold_pct", 0.04) or 0.04
        )
        self._risk_w_trend = float(
            getattr(settings, "ingestion_dxy_risk_score_trend_weight", 0.4) or 0.4
        )
        self._risk_w_momo = float(
            getattr(settings, "ingestion_dxy_risk_score_momo_weight", 0.3) or 0.3
        )
        self._risk_w_level = float(
            getattr(settings, "ingestion_dxy_risk_score_level_weight", 0.3) or 0.3
        )

    # ------------------------------------------------------------------ public
    def refresh(self, *, as_of: Optional[date] = None) -> None:
        if not bool(getattr(self._settings, "ingestion_dxy_enabled", True)):
            self._logger.info("DXY regime job disabled via INGESTION_DXY_ENABLED; skipping")
            return

        conn = self._db_factory()
        try:
            benchmark_key = self._lookup_benchmark_key(conn, self._benchmark_name)
            if benchmark_key is None:
                self._logger.warning(
                    "DXY regime: benchmark %s not found in dim_benchmark; skipping",
                    self._benchmark_name,
                )
                return

            px = self._fetch_price_series(conn, benchmark_key, as_of=as_of)
            if px.empty:
                self._logger.info(
                    "DXY regime: no price rows for %s; nothing to do", self._benchmark_name
                )
                return

            df = self._compute_features(px)
            if df.empty:
                self._logger.info("DXY regime: computed frame is empty; nothing to write")
                return

            latest_written = self._latest_fact_date(conn)
            if latest_written is not None:
                df = df[df.index > latest_written]
            if df.empty:
                self._logger.info("DXY regime: no new dates to upsert (last=%s)", latest_written)
                return

            source_key = self._ensure_source(conn)
            self._upsert(conn, df, source_key)
            self._logger.info(
                "DXY regime: upserted %d rows (%s to %s)",
                len(df.index),
                df.index.min().date(),
                df.index.max().date(),
            )
        finally:
            conn.close()

    # ---------------------------------------------------------------- internal
    def _lookup_benchmark_key(self, conn, name: str) -> Optional[int]:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT benchmark_key FROM rankalpha.dim_benchmark WHERE benchmark_name = %s",
                (name,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else None

    def _ensure_source(self, conn) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO rankalpha.dim_source (source_name, version, exclude_from_screener, screener_weight) "
                "VALUES (%s, '1', false, 1.0) ON CONFLICT (source_name) DO NOTHING",
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

    def _fetch_price_series(self, conn, benchmark_key: int, *, as_of: Optional[date]) -> pd.Series:
        params: List[object] = [benchmark_key]
        where = ["f.benchmark_key = %s"]
        if as_of is not None:
            where.append("d.full_date <= %s")
            params.append(as_of)

        sql = f"""
            SELECT d.full_date, f.close_px
            FROM rankalpha.fact_benchmark_price f
            JOIN rankalpha.dim_date d ON d.date_key = f.date_key
            WHERE {" AND ".join(where)}
            ORDER BY d.full_date ASC
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        if not rows:
            return pd.Series(dtype=float)
        dates = pd.to_datetime([r[0] for r in rows])
        values = pd.Series([None if r[1] is None else float(r[1]) for r in rows], index=dates)
        return values.dropna()

    def _latest_fact_date(self, conn) -> Optional[pd.Timestamp]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT MAX(d.full_date)
                FROM rankalpha.fact_macro_series f
                JOIN rankalpha.dim_macro_series m ON m.series_key = f.series_key
                JOIN rankalpha.dim_date d ON d.date_key = f.date_key
                WHERE m.series_code = %s
                """,
                ("US_DXY_LEVEL",),
            )
            row = cur.fetchone()
            return pd.Timestamp(row[0]) if row and row[0] else None

    def _compute_features(self, px: pd.Series) -> pd.DataFrame:
        df = pd.DataFrame({"US_DXY_LEVEL": px})

        df["US_DXY_MA50"] = px.rolling(window=50, min_periods=25).mean()
        df["US_DXY_MA100"] = px.rolling(window=100, min_periods=50).mean()
        df["US_DXY_MA200"] = px.rolling(window=self._ma_days, min_periods=self._ma_days // 2).mean()

        df["US_DXY_ROC_1M"] = px.pct_change(self._roc_1m_days)
        df["US_DXY_ROC_3M"] = px.pct_change(self._roc_3m_days)
        df["US_DXY_ROC_6M"] = px.pct_change(self._roc_6m_days)

        # Rolling z-score vs ~3y
        roll = px.rolling(window=self._z_window, min_periods=self._z_window // 2)
        mu = roll.mean()
        sigma = roll.std()
        df["US_DXY_Z_3Y"] = (px - mu) / sigma.replace(0, np.nan)

        # Rolling percentile vs ~5y
        def _pct_rank(arr: np.ndarray) -> float:
            arr = arr[~np.isnan(arr)]
            if len(arr) == 0:
                return np.nan
            last = arr[-1]
            return np.sum(arr <= last) / len(arr)

        df["US_DXY_PCTL_5Y"] = px.rolling(
            window=self._pct_window, min_periods=self._pct_window // 2
        ).apply(_pct_rank, raw=True)

        # Regime state
        ma = df["US_DXY_MA200"]
        roc6 = df["US_DXY_ROC_6M"]
        roc_hi = 0.03
        roc_lo = -0.03

        raw_state = pd.Series(0, index=px.index, dtype=float)
        raw_state[(px > ma) & (roc6 > roc_hi)] = 1
        raw_state[(px < ma) & (roc6 < roc_lo)] = -1
        df["US_DXY_REGIME_STATE"] = raw_state

        # Shocks
        df["US_DXY_SHOCK_UP_FLAG"] = (df["US_DXY_ROC_1M"] > self._shock_threshold).astype(float)
        df["US_DXY_SHOCK_DOWN_FLAG"] = (df["US_DXY_ROC_1M"] < -self._shock_threshold).astype(float)

        # Risk score (0-1): blend of trend (MA spread), momentum, level percentile
        spread = (px - ma) / ma
        trend_score = ((spread.clip(-0.05, 0.05) + 0.05) / 0.10).clip(0, 1)
        momo_combo = (df["US_DXY_ROC_1M"].fillna(0) + df["US_DXY_ROC_3M"].fillna(0)) / 2
        momo_score = ((momo_combo.clip(-0.10, 0.10) + 0.10) / 0.20).clip(0, 1)
        level_score = df["US_DXY_PCTL_5Y"].clip(0, 1)

        weights_sum = self._risk_w_trend + self._risk_w_momo + self._risk_w_level
        if weights_sum <= 0:
            weights_sum = 1.0
        risk_score = (
            self._risk_w_trend * trend_score
            + self._risk_w_momo * momo_score
            + self._risk_w_level * level_score
        ) / weights_sum
        df["US_DXY_RISK_SCORE"] = risk_score.clip(0, 1)

        df.dropna(how="all", inplace=True)
        return df

    def _upsert(self, conn, df: pd.DataFrame, source_key: int) -> None:
        if df.empty:
            return

        # series key lookup
        with conn.cursor() as cur:
            cur.execute(
                "SELECT series_code, series_key FROM rankalpha.dim_macro_series WHERE series_code = ANY(%s)",
                (list(SERIES_CODES),),
            )
            mapping = {row[0]: int(row[1]) for row in cur.fetchall()}
        missing = set(SERIES_CODES) - set(mapping.keys())
        if missing:
            raise RuntimeError(f"Missing dim_macro_series rows for: {sorted(missing)}")

        # date_key lookup
        dates = [idx.date() for idx in df.index]
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
            as_of = idx.date()
            date_key = date_map[as_of]
            for series_code, value in row.items():
                if value is None or (isinstance(value, float) and np.isnan(value)):
                    continue
                series_key = mapping[series_code]
                records.append((date_key, series_key, source_key, float(value)))

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
