import math
from typing import Dict, Optional

import numpy as np
import pandas as pd

from .prices import PriceReader


def _safe_latest(series: pd.Series, min_points: int) -> Optional[float]:
    """Return the latest value if coverage >= min_points and value is finite."""
    if series is None or series.empty:
        return None
    if series.count() < min_points:
        return None
    val = series.iloc[-1]
    if pd.isna(val) or not np.isfinite(val):
        return None
    return float(val)


def _winsorize(series: pd.Series, limit: float = 3.0) -> pd.Series:
    """Clip series to +/- limit; returns same index."""
    return series.clip(lower=-limit, upper=limit)


def _coerce_weights(weights: pd.Series, index: pd.Index) -> pd.Series:
    w = pd.to_numeric(weights, errors="coerce")
    w = w.reindex(index)
    w = w.replace([np.inf, -np.inf], np.nan)
    return w


class MoneyFlowCalculator:
    """Computes money-flow components (CMF, volume surprise, returns) for a single symbol."""

    def __init__(
        self,
        min_valid_frac: float = 0.8,
        windows: Dict[str, int] | None = None,
    ) -> None:
        self.min_valid_frac = float(min_valid_frac)
        self.windows = windows or {"cmf_short": 5, "cmf_med": 20, "vol": 60, "ret": 20}

    def compute_components(self, df: pd.DataFrame) -> Dict[str, Optional[float]]:
        """Return latest per-symbol components or None when insufficient coverage."""
        out: Dict[str, Optional[float]] = {
            "cmf_5": None,
            "cmf_20": None,
            "vol_surp_60": None,
            "ret_20": None,
        }

        if df is None or df.empty:
            return out

        try:
            df = df.sort_index()
        except Exception:
            pass

        # Require OHLCV columns; bail out if missing or non-series
        if "High" not in df.columns or "Low" not in df.columns or "Volume" not in df.columns:
            return out

        high = pd.to_numeric(df["High"], errors="coerce")
        low = pd.to_numeric(df["Low"], errors="coerce")
        # CMF must use a close consistent with the raw high/low range (avoid dividend-adjusted closes).
        close_cmf = pd.to_numeric(df["Close"], errors="coerce") if "Close" in df.columns else None
        if close_cmf is not None and close_cmf.dropna().empty:
            close_cmf = None
        # Returns use adjusted close (total-return semantics) when available.
        close_ret = PriceReader.select_close(df).astype(float)
        volume = pd.to_numeric(df["Volume"], errors="coerce")

        # If any key series is scalar or empty, abort
        for ser in (high, low, close_ret, volume):
            if not hasattr(ser, "index") or ser.empty:
                return out

        # CMF helper
        def cmf(window: int) -> Optional[float]:
            if len(df) < window:
                return None
            if close_cmf is None or getattr(close_cmf, "empty", True):
                return None
            rng = (high - low).replace(0, np.nan)
            mf_mult = (2 * close_cmf - high - low) / rng
            mf_mult = mf_mult.fillna(0.0)
            mf_vol = mf_mult * volume
            roll_vol = volume.rolling(
                window, min_periods=math.ceil(window * self.min_valid_frac)
            ).sum()
            roll_mf = mf_vol.rolling(
                window, min_periods=math.ceil(window * self.min_valid_frac)
            ).sum()
            cmf_series = roll_mf / roll_vol
            return _safe_latest(cmf_series, math.ceil(window * self.min_valid_frac))

        out["cmf_5"] = cmf(self.windows["cmf_short"])
        out["cmf_20"] = cmf(self.windows["cmf_med"])

        # Volume surprise (log(volume / median_60))
        vol_window = self.windows["vol"]
        if len(df) >= vol_window:
            med_vol = volume.rolling(
                vol_window, min_periods=math.ceil(vol_window * self.min_valid_frac)
            ).median()
            vol_surp = np.log(volume / med_vol)
            out["vol_surp_60"] = _safe_latest(vol_surp, math.ceil(vol_window * self.min_valid_frac))

        # 20-day return
        ret_window = self.windows["ret"]
        if len(df) >= ret_window + 1:
            ret_20 = close_ret.pct_change(ret_window)
            out["ret_20"] = _safe_latest(ret_20, math.ceil(ret_window * self.min_valid_frac))

        return out

    @staticmethod
    def zscore(series: pd.Series, clip: float = 3.0) -> pd.Series:
        """Cross-sectional z-score with guard for zero std, then winsorize."""
        mean = series.mean()
        std = series.std(ddof=0)
        if std == 0 or pd.isna(std):
            return pd.Series(index=series.index, dtype=float)
        z = (series - mean) / std
        return _winsorize(z, limit=clip)

    @staticmethod
    def weighted_zscore(series: pd.Series, weights: pd.Series, clip: float = 3.0) -> pd.Series:
        """
        Cross-sectional weighted z-score (population variance, ddof=0), then winsorize.

        Any rows where either value or weight is non-finite are ignored for mean/std
        estimation, but z-scores are returned for all indices (NaN where value is NaN).
        """
        x = pd.to_numeric(series, errors="coerce")
        w = _coerce_weights(weights, x.index)

        mask = (
            (~pd.isna(x))
            & (~pd.isna(w))
            & np.isfinite(x.values)
            & np.isfinite(w.values)
            & (w.values > 0)
        )
        if int(mask.sum()) < 2:
            return pd.Series(index=x.index, dtype=float)

        xw = x.values[mask]
        ww = w.values[mask]
        w_sum = float(np.sum(ww))
        if not np.isfinite(w_sum) or w_sum <= 0:
            return pd.Series(index=x.index, dtype=float)

        mean = float(np.sum(ww * xw) / w_sum)
        var = float(np.sum(ww * (xw - mean) ** 2) / w_sum)
        std = float(np.sqrt(var))
        if std == 0 or (not np.isfinite(std)):
            return pd.Series(index=x.index, dtype=float)

        z = (x - mean) / std
        return _winsorize(z, limit=clip)

    @staticmethod
    def weighted_rank_pct(values: pd.Series, weights: pd.Series) -> pd.Series:
        """
        Weighted percentile rank in [0, 1] using a mid-rank convention per unique value.

        For each distinct value v, let W_before be the total weight of all items with
        value < v, and W_group the total weight where value == v. Then:
            p(v) = (W_before + 0.5 * W_group) / W_total
        """
        x = pd.to_numeric(values, errors="coerce")
        w = _coerce_weights(weights, x.index)

        mask = (
            (~pd.isna(x))
            & (~pd.isna(w))
            & np.isfinite(x.values)
            & np.isfinite(w.values)
            & (w.values > 0)
        )
        if int(mask.sum()) == 0:
            return pd.Series(index=x.index, dtype=float)

        df = pd.DataFrame({"x": x[mask], "w": w[mask]})
        df = df.sort_values("x", kind="mergesort")
        grouped = df.groupby("x", sort=True)["w"].sum()
        total = float(grouped.sum())
        if not np.isfinite(total) or total <= 0:
            return pd.Series(index=x.index, dtype=float)

        w_before = grouped.cumsum().shift(1).fillna(0.0)
        p_by_x = (w_before + 0.5 * grouped) / total

        out = pd.Series(index=x.index, dtype=float)
        out.loc[df.index] = df["x"].map(p_by_x).astype(float).values
        return out
