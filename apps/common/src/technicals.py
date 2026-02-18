from __future__ import annotations

import numpy as np
import pandas as pd


def _ensure_1d_series(x, index: pd.Index | None = None) -> pd.Series:
    """Return a 1D float Series from Series/DataFrame/ndarray/scalar.

    - If DataFrame, use first numeric column (or first column).
    - If ndarray with shape (N, 1), ravel to (N,).
    - Cast to float dtype; preserve index when available.
    """
    # Unwrap DataFrame to a single column Series
    if isinstance(x, pd.DataFrame):
        # Prefer first numeric column
        col = None
        for c in x.columns:
            if pd.api.types.is_numeric_dtype(x[c].dtype):
                col = c
                break
        if col is None:
            col = x.columns[0]
        x = x[col]
    # Convert ndarray to Series
    if isinstance(x, np.ndarray):
        arr = x
        if arr.ndim > 1:
            arr = arr.reshape(-1)
        return pd.Series(arr, index=index, dtype=float)
    # Already a Series
    if isinstance(x, pd.Series):
        try:
            return x.astype(float)
        except Exception:
            return pd.to_numeric(x, errors="coerce")
    # Fallback: scalar or other iterable
    try:
        arr = np.asarray(x)
        if arr.ndim > 1:
            arr = arr.reshape(-1)
        return pd.Series(arr, index=index, dtype=float)
    except Exception:
        return pd.Series(x, index=index, dtype=float)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi_wilder(close: pd.Series, period: int = 14) -> float | None:
    close = _ensure_1d_series(close)
    if len(close) < period + 1:
        return None
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    up = pd.Series(up, index=close.index)
    down = pd.Series(down, index=close.index)
    roll_up = up.ewm(alpha=1 / period, adjust=False).mean()
    roll_down = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = roll_up.iloc[-1] / (roll_down.iloc[-1] + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    high = _ensure_1d_series(high)
    low = _ensure_1d_series(low)
    close = _ensure_1d_series(close)
    if len(close) < period + 1:
        return None
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    # Avoid FutureWarning: float() on 1‑element Series; coerce scalar first
    val = tr.rolling(period).mean().iloc[-1]
    try:
        val = val.item()  # numpy scalar -> Python float
    except Exception:
        pass
    return float(val)


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0):
    close = _ensure_1d_series(close)
    if len(close) < period:
        return None, None, None
    mid = close.rolling(period).mean().iloc[-1]
    std = close.rolling(period).std(ddof=0).iloc[-1]
    upper = mid + num_std * std
    lower = mid - num_std * std
    # Values are scalars, but coerce defensively to avoid pandas deprecation warnings
    try:
        upper = upper.item()
    except Exception:
        pass
    try:
        mid = mid.item()
    except Exception:
        pass
    try:
        lower = lower.item()
    except Exception:
        pass
    return float(upper), float(mid), float(lower)


def macd_vals(close: pd.Series, f: int = 12, s: int = 26, sig: int = 9):
    close = _ensure_1d_series(close)
    if len(close) < s + sig:
        return None, None, None
    ema_fast = ema(close, f)
    ema_slow = ema(close, s)
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=sig, adjust=False).mean()
    hist = macd - signal
    mv = macd.iloc[-1]
    sv = signal.iloc[-1]
    hv = hist.iloc[-1]
    try:
        mv = mv.item()
    except Exception:
        pass
    try:
        sv = sv.item()
    except Exception:
        pass
    try:
        hv = hv.item()
    except Exception:
        pass
    return float(mv), float(sv), float(hv)


def rolling_return(close: pd.Series, days: int) -> float | None:
    close = _ensure_1d_series(close)
    if len(close) <= days:
        return None
    return float((close.iloc[-1] / close.iloc[-days] - 1) * 100)


def vol_zscore(volume: pd.Series, period: int = 20) -> float | None:
    volume = _ensure_1d_series(volume)
    if len(volume) < period:
        return None
    mean = volume.rolling(period).mean().iloc[-1]
    std = volume.rolling(period).std(ddof=0).iloc[-1]
    if std == 0 or np.isnan(std):
        return None
    return float((volume.iloc[-1] - mean) / std)


def dist_52w_high(close: pd.Series, days: int = 252) -> float | None:
    close = _ensure_1d_series(close)
    if len(close) < days:
        return None
    high = close.rolling(days).max().iloc[-1]
    if high == 0 or np.isnan(high):
        return None
    return float((close.iloc[-1] / high - 1) * 100)


def compute_technicals(df: pd.DataFrame) -> dict[str, float]:
    """Compute a standard set of daily technical indicators from OHLCV DataFrame.

    Expects columns: Open, High, Low, Close, Volume; index datetime-like.
    Returns a mapping of indicator_code -> value.
    """
    out: dict[str, float] = {}
    # Support both single-level and MultiIndex columns; coerce to 1D Series
    cols = df.columns
    if isinstance(cols, pd.MultiIndex):

        def get_mi(col_name: str):
            try:
                cand = df.xs(col_name, axis=1, level=-1, drop_level=False)
            except Exception:
                cand = df.filter(like=col_name, axis=1)
            return _ensure_1d_series(cand, df.index)

        close = get_mi("Close")
        high = get_mi("High")
        low = get_mi("Low")
        vol = get_mi("Volume")
    else:
        close = (
            _ensure_1d_series(df["Close"]) if "Close" in df else _ensure_1d_series(df.iloc[:, 0])
        )
        high = _ensure_1d_series(df.get("High", close))
        low = _ensure_1d_series(df.get("Low", close))
        vol = _ensure_1d_series(df.get("Volume", pd.Series(index=df.index, dtype=float)))

    # SMAs
    if len(close) >= 20:
        v = close.rolling(20).mean().iloc[-1]
        try:
            v = v.item()
        except Exception:
            pass
        out["SMA20"] = float(v)
    if len(close) >= 50:
        v = close.rolling(50).mean().iloc[-1]
        try:
            v = v.item()
        except Exception:
            pass
        out["SMA50"] = float(v)
    if len(close) >= 200:
        v = close.rolling(200).mean().iloc[-1]
        try:
            v = v.item()
        except Exception:
            pass
        out["SMA200"] = float(v)
    # EMAs
    if len(close) >= 12:
        v = ema(close, 12).iloc[-1]
        try:
            v = v.item()
        except Exception:
            pass
        out["EMA12"] = float(v)
    if len(close) >= 26:
        v = ema(close, 26).iloc[-1]
        try:
            v = v.item()
        except Exception:
            pass
        out["EMA26"] = float(v)
    # RSI
    r = rsi_wilder(close, 14)
    if r is not None:
        out["RSI14"] = r
    # ATR
    a = atr(high, low, close, 14)
    if a is not None:
        out["ATR14"] = a
    # Bollinger
    upper, mid, lower = bollinger(close, 20, 2.0)
    if upper is not None:
        out["BB_UPPER"], out["BB_MIDDLE"], out["BB_LOWER"] = upper, mid, lower
    # MACD
    m, s, h = macd_vals(close, 12, 26, 9)
    if m is not None:
        out["MACD"], out["MACD_SIGNAL"], out["MACD_HIST"] = m, s, h
    # Rolling returns
    for d in (5, 20, 60, 120):
        rr = rolling_return(close, d)
        if rr is not None:
            out[f"RET_{d}D"] = rr
    # Volume z-score
    vz = vol_zscore(vol, 20)
    if vz is not None:
        out["VOL_Z20"] = vz
    # Distance to 52w high
    dh = dist_52w_high(close, 252)
    if dh is not None:
        out["DIST_52W_HIGH"] = dh
    return out
