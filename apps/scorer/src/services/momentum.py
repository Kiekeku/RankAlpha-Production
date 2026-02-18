import numpy as np
import pandas as pd

from .prices import PriceReader

# Prefer SciPy's linregress; fall back to a lightweight numpy-based solver
try:  # pragma: no cover
    from scipy.stats import linregress as _linregress
except Exception:  # SciPy unavailable – define a small compatible shim

    def _linregress(x, y):
        x = np.asarray(list(x), dtype=float)
        y = np.asarray(list(y), dtype=float)
        n = x.size
        if n < 2 or y.size != n:
            return type("LR", (), {"slope": float("nan"), "rvalue": 0.0})()
        slope, _intercept = np.polyfit(x, y, 1)
        with np.errstate(all="ignore"):
            r = float(np.corrcoef(x, y)[0, 1]) if n > 1 else 0.0
        return type("LR", (), {"slope": float(slope), "rvalue": r})()


linregress = _linregress


class MomentumCalculator:
    @staticmethod
    def sma200_raw(df: pd.DataFrame) -> float | None:
        try:
            df = df.sort_index()
        except Exception:
            pass
        if df.shape[0] < 200:
            return None
        close = PriceReader.select_close(df)
        sma200 = close.rolling(200).mean().iloc[-1]
        return PriceReader.round2(sma200)

    # Removed raw-price slope helpers after migrating technicals and momentum
    # to log-price slopes. If needed in the future, reintroduce with explicit
    # call sites and tests.

    @staticmethod
    def linreg_log_slope_r2(
        df: pd.DataFrame,
        window: int,
        min_valid_frac: float = 0.8,
    ) -> tuple[float | None, float | None, int]:
        """Log-price linear regression slope and R^2 with coverage guard.

        Returns (slope_per_step, r2, n_valid). If coverage within the window is
        insufficient (n_valid < window * min_valid_frac) or fewer than 2 points
        remain after filtering, returns (None, None, n_valid).
        """
        try:
            df = df.sort_index()
        except Exception:
            pass
        if df.shape[0] < window:
            return None, None, 0
        seg = df.tail(window)
        y = PriceReader.select_close(seg).astype(float).values.ravel()
        mask = (~np.isnan(y)) & (y > 0)
        y = y[mask]
        n = int(y.size)
        if n < 2 or n < int(window * float(min_valid_frac)):
            return None, None, n
        # Optionally use actual day deltas if index has gaps; for now, equally spaced
        x = np.arange(n, dtype=float)
        y_log = np.log(y)
        res = linregress(x, y_log)
        r2 = float(res.rvalue * res.rvalue)
        return float(res.slope), r2, n
