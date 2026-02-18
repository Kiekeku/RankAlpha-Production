from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass
class HybridWeights:
    as_of_date: pd.Timestamp
    train_start_date: pd.Timestamp
    train_end_date: pd.Timestamp
    window_days: int
    horizon_days: int
    w_m: float
    w_v: float
    w_s: float
    lambda_rp: float
    alpha_shrink: float
    sentiment_coverage: Optional[float] = None


def _ewma_mean_std(x: pd.Series, span: int = 60) -> tuple[float, float]:
    if x.dropna().empty:
        return 0.0, 1.0
    m = x.ewm(span=span, adjust=False).mean().iloc[-1]
    s = x.ewm(span=span, adjust=False).std(bias=False).iloc[-1]
    return float(m if pd.notna(m) else 0.0), float(s if pd.notna(s) and s > 1e-12 else 1.0)


def _cross_sectional_zscore_panel(x: pd.Series) -> pd.Series:
    """Z-score each date's cross-section for a panel Series indexed by (date, symbol).

    pandas 2.x `groupby(...).apply(...)` adds the group key back into the index by
    default, which can duplicate the date level (3-level MultiIndex) and break
    downstream xs/reindex logic. We use group_keys=False to preserve the original
    (date, symbol) index.
    """
    if x is None or x.empty:
        return x

    def _xz(g: pd.Series) -> pd.Series:
        mu = g.mean()
        sd = g.std(ddof=0)
        if sd and sd > 1e-12:
            return (g - mu) / sd
        return g * 0.0

    return x.groupby(level=0, group_keys=False).apply(_xz)


def _select_train_start_date(
    engine: Engine, *, train_end_date: pd.Timestamp, window_days: int
) -> pd.Timestamp:
    """Select the training window start date using trading days when available.

    The scorer docs define `window_days` in trading days. We query `rankalpha.dim_date`
    to pick the trading day that is `window_days` deep (inclusive) from train_end_date.
    Falls back to a calendar-day delta when the calendar query fails.
    """
    fallback = train_end_date - pd.Timedelta(days=int(window_days))
    try:
        offset = max(0, int(window_days) - 1)
        q_start = f"""
            SELECT full_date
            FROM rankalpha.dim_date
            WHERE is_trading_day IS TRUE
              AND full_date <= DATE '{train_end_date.date()}'
            ORDER BY full_date DESC
            OFFSET {offset}
            LIMIT 1
        """
        df = pd.read_sql_query(q_start, engine, parse_dates=["full_date"])
        if not df.empty and pd.notna(df.loc[0, "full_date"]):
            return pd.to_datetime(df.loc[0, "full_date"]).normalize()
    except Exception:
        return fallback
    return fallback


def _daily_ic(series: dict[str, pd.Series], fwd_ret: pd.Series) -> dict[str, pd.Series]:
    # Align on dates and compute Spearman rank IC per day across symbols
    dates = sorted(set(fwd_ret.index.get_level_values(0)))
    out: dict[str, list[float]] = {k: [] for k in series}
    idx_dates: list[pd.Timestamp] = []
    for dt in dates:
        idx_dates.append(dt)
        ret_t = fwd_ret.xs(dt, level=0, drop_level=False)
        sym = ret_t.index.get_level_values(1)
        for k, s in series.items():
            try:
                x = s.xs(dt, level=0).reindex(sym)
                if x.dropna().size >= 20 and ret_t.dropna().size >= 20:
                    ic = spearmanr(x.values, ret_t.values, nan_policy="omit").correlation
                else:
                    ic = np.nan
            except Exception:
                ic = np.nan
            out[k].append(ic)
    return {k: pd.Series(v, index=idx_dates, dtype=float) for k, v in out.items()}


def _factor_returns(exposures: dict[str, pd.Series], next_ret: pd.Series) -> dict[str, pd.Series]:
    # Long-short factor return proxy per day: demeaned rank weights * next-day return
    out: dict[str, list[float]] = {k: [] for k in exposures}
    idx_dates: list[pd.Timestamp] = []
    dates = sorted(set(next_ret.index.get_level_values(0)))
    for dt in dates:
        idx_dates.append(dt)
        r = next_ret.xs(dt, level=0)
        for k, ex in exposures.items():
            try:
                x = ex.xs(dt, level=0).reindex(r.index)
                x = x.rank(pct=True)  # 0..1
                w = x - x.mean()  # zero-sum weights
                fr = float(np.nansum(w.values * r.values))
            except Exception:
                fr = np.nan
            out[k].append(fr)
    return {k: pd.Series(v, index=idx_dates, dtype=float) for k, v in out.items()}


def compute_hybrid_weights(
    engine: Engine,
    *,
    window_days: int = 504,
    horizon_days: int = 21,
    lambda_rp: float = 0.4,
    alpha_cap: float = 0.6,
) -> HybridWeights | None:
    # Get latest trading date
    q_latest = """
        SELECT MAX(d.full_date) AS as_of_date
        FROM rankalpha.dim_date d
        JOIN rankalpha.fact_score_history f ON f.date_key = d.date_key
    """
    dt = pd.read_sql_query(q_latest, engine)
    if dt.empty or pd.isna(dt.loc[0, "as_of_date"]):
        return None
    as_of_date = pd.to_datetime(dt.loc[0, "as_of_date"]).normalize()
    # Define training window [train_start_date .. train_end_date] where
    # train_end_date is the latest trading date and train_start_date is window_days back.
    train_end_date = as_of_date
    train_start_date = _select_train_start_date(
        engine, train_end_date=train_end_date, window_days=window_days
    )

    # Load scores (0..100) for M, V, S
    q_scores = f"""
        SELECT d.full_date AS as_of_date, s.symbol,
               MAX(CASE WHEN t.score_type_name = 'momentum score' THEN f.score END) AS m,
               MAX(CASE WHEN t.score_type_name = 'value score'    THEN f.score END) AS v,
               MAX(CASE WHEN t.score_type_name = 'sentiment score'THEN f.score END) AS s
        FROM rankalpha.fact_score_history f
        JOIN rankalpha.dim_score_type t ON t.score_type_key = f.score_type_key
        JOIN rankalpha.dim_date d ON d.date_key = f.date_key
        JOIN rankalpha.dim_stock s ON s.stock_key = f.stock_key
        WHERE d.full_date BETWEEN DATE '{train_start_date.date()}' AND DATE '{train_end_date.date()}'
        GROUP BY d.full_date, s.symbol
    """
    df = pd.read_sql_query(q_scores, engine, parse_dates=["as_of_date"])
    if df.empty:
        return None

    # Load prices, compute daily and forward returns
    q_px = f"""
        SELECT d.full_date AS as_of_date, s.symbol, sp.close_px
        FROM rankalpha.fact_security_price sp
        JOIN rankalpha.dim_date d   ON d.date_key = sp.date_key
        JOIN rankalpha.dim_stock s  ON s.stock_key = sp.stock_key
        WHERE d.full_date BETWEEN DATE '{train_start_date.date()}' AND DATE '{train_end_date.date()}'
    """
    px = pd.read_sql_query(q_px, engine, parse_dates=["as_of_date"])
    if px.empty:
        return None

    px = px.sort_values(["symbol", "as_of_date"])
    # Explicitly disable implicit ffill to avoid pandas deprecation warning
    px["ret1"] = px.groupby("symbol")["close_px"].pct_change(fill_method=None)
    # True forward K‑day return from t to t+K, aligned at t
    px["fwdK"] = px.groupby("symbol")["close_px"].shift(-horizon_days) / px["close_px"] - 1.0

    # Convert scores to panel Series indexed by (date, symbol)
    df = df.set_index(["as_of_date", "symbol"]).sort_index()
    m = df["m"]
    v = df["v"]
    s = df["s"]

    # Standardize scores cross-sectionally per day (z-score)
    m_z = _cross_sectional_zscore_panel(m)
    v_z = _cross_sectional_zscore_panel(v)
    s_z = _cross_sectional_zscore_panel(s)

    # Build forward return series aligned on t (use fwdK at t vs exposure at t)
    rK = px.set_index(["as_of_date", "symbol"])["fwdK"].sort_index()

    # Coverage metric for sentiment
    s_cov = (
        float(s.groupby(level=0).apply(lambda x: x.notna().mean()).mean())
        if not s.dropna().empty
        else 0.0
    )

    # IC series per factor
    ic = _daily_ic({"M": m_z, "V": v_z, "S": s_z}, rK)
    # EWMA mean/std
    mu_M, sd_M = _ewma_mean_std(ic["M"])
    mu_V, sd_V = _ewma_mean_std(ic["V"])
    mu_S, sd_S = _ewma_mean_std(ic["S"])
    eps = 1e-6
    w_ic_raw = {
        "M": max(0.0, mu_M) / (sd_M + eps),
        "V": max(0.0, mu_V) / (sd_V + eps),
        "S": max(0.0, mu_S) / (sd_S + eps),
    }
    # Normalize IC weights
    s_ic = sum(w_ic_raw.values()) or 1.0
    w_ic = {k: v / s_ic for k, v in w_ic_raw.items()}

    # Factor-mimicking returns and risk-parity weights (inverse vol)
    fr = _factor_returns(
        {"M": m_z, "V": v_z, "S": s_z},
        px.set_index(["as_of_date", "symbol"]).sort_index()["ret1"].groupby(level=1).shift(-1),
    )
    vol = {k: float(fr[k].std(ddof=0)) if not fr[k].dropna().empty else np.nan for k in fr}
    inv_vol = {k: (1.0 / v if (v and v > 1e-6) else 0.0) for k, v in vol.items()}
    s_rp = sum(inv_vol.values()) or 1.0
    w_rp = {k: v / s_rp for k, v in inv_vol.items()}

    # Blend IC and RP, then shrink to baseline
    w_est = {
        k: (1.0 - lambda_rp) * w_ic.get(k, 0.0) + lambda_rp * w_rp.get(k, 0.0)
        for k in ["M", "V", "S"]
    }
    # Shrinkage toward baseline 0.4/0.4/0.2; alpha based on sample size
    # Approx effective days = count of non-null ICs
    eff_n = int(pd.concat([ic["M"], ic["V"]]).dropna().size / 2) or 1
    alpha = min(alpha_cap, 50.0 / max(30.0, eff_n))
    base = {"M": 0.4, "V": 0.4, "S": 0.2}
    w_final = {k: (1.0 - alpha) * w_est[k] + alpha * base[k] for k in w_est}
    # Normalize to sum 1
    s_final = sum(w_final.values()) or 1.0
    w_final = {k: max(0.0, v / s_final) for k, v in w_final.items()}

    return HybridWeights(
        as_of_date=as_of_date,
        train_start_date=train_start_date,
        train_end_date=train_end_date,
        window_days=window_days,
        horizon_days=horizon_days,
        w_m=float(w_final["M"]),
        w_v=float(w_final["V"]),
        w_s=float(w_final["S"]),
        lambda_rp=float(lambda_rp),
        alpha_shrink=float(alpha),
        sentiment_coverage=float(s_cov),
    )


def upsert_weights(engine: Engine, hw: HybridWeights) -> None:
    # Upsert into dim_model_weight (as_of_date, method) unique
    sql = """
        INSERT INTO rankalpha.dim_model_weight (
            as_of_date, method, window_days, horizon_days,
            w_momentum, w_value, w_sentiment,
            lambda_rp, alpha_shrink, sentiment_coverage
        ) VALUES (:as_of_date, :method, :window_days, :horizon_days,
                  :w_m, :w_v, :w_s,
                  :lambda_rp, :alpha_shrink, :sentiment_coverage)
        ON CONFLICT (as_of_date, method)
        DO UPDATE SET
            window_days = EXCLUDED.window_days,
            horizon_days = EXCLUDED.horizon_days,
            w_momentum = EXCLUDED.w_momentum,
            w_value    = EXCLUDED.w_value,
            w_sentiment= EXCLUDED.w_sentiment,
            lambda_rp  = EXCLUDED.lambda_rp,
            alpha_shrink = EXCLUDED.alpha_shrink,
            sentiment_coverage = EXCLUDED.sentiment_coverage,
            created_at = now()
    """
    params = {
        "as_of_date": hw.as_of_date.date(),
        "method": "HYBRID_IC_RP",
        "window_days": hw.window_days,
        "horizon_days": hw.horizon_days,
        "w_m": hw.w_m,
        "w_v": hw.w_v,
        "w_s": hw.w_s,
        "lambda_rp": hw.lambda_rp,
        "alpha_shrink": hw.alpha_shrink,
        "sentiment_coverage": hw.sentiment_coverage,
    }
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def upsert_versioned_weights(
    engine: Engine, hw: HybridWeights, *, model_code: str = "default"
) -> None:
    """Insert a new weight version effective from the next trading day after train_end_date.
    Closes the prior open-ended version in a single transaction. Also stores per-factor items.
    """
    sql_next_trading = """
        SELECT MIN(full_date) AS next_date
        FROM rankalpha.dim_date
        WHERE full_date > :end_date AND is_trading_day IS TRUE
    """
    with engine.begin() as conn:
        # Determine effective_from as next trading day
        res = conn.execute(text(sql_next_trading), {"end_date": hw.train_end_date.date()}).one()
        # Ensure effective_from > train_end_date to satisfy DB constraint even if calendar is incomplete
        eff_from = res.next_date or (hw.train_end_date.date() + pd.Timedelta(days=1)).date()

        # Close previous open-ended version first to avoid violating the validity exclusion constraint
        conn.execute(
            text(
                """
            UPDATE rankalpha.dim_model_weight_version
            SET effective_to = :eff_from
            WHERE model_code = :model_code
              AND effective_to IS NULL
              AND effective_from < :eff_from
            """
            ),
            {"eff_from": eff_from, "model_code": model_code},
        )

        # Insert new header version (or update the existing row for this effective_from)
        vid = conn.execute(
            text(
                """
            INSERT INTO rankalpha.dim_model_weight_version (
              model_code, effective_from, train_start_date, train_end_date,
              window_days, horizon_days, lambda_rp, alpha_shrink, sentiment_coverage, computed_by
            ) VALUES (
              :model_code, :effective_from, :train_start_date, :train_end_date,
              :window_days, :horizon_days, :lambda_rp, :alpha_shrink, :sent_cov, :computed_by
            )
            ON CONFLICT (model_code, effective_from)
            DO UPDATE SET
              window_days = EXCLUDED.window_days,
              horizon_days = EXCLUDED.horizon_days,
              lambda_rp = EXCLUDED.lambda_rp,
              alpha_shrink = EXCLUDED.alpha_shrink,
              sentiment_coverage = EXCLUDED.sentiment_coverage
            RETURNING id
            """
            ),
            {
                "model_code": model_code,
                "effective_from": eff_from,
                "train_start_date": hw.train_start_date.date(),
                "train_end_date": hw.train_end_date.date(),
                "window_days": hw.window_days,
                "horizon_days": hw.horizon_days,
                "lambda_rp": hw.lambda_rp,
                "alpha_shrink": hw.alpha_shrink,
                "sent_cov": hw.sentiment_coverage,
                "computed_by": None,
            },
        ).scalar_one()

        # Upsert factor items for this version
        conn.execute(
            text(
                """
            INSERT INTO rankalpha.dim_model_weight_item (version_id, factor_code, weight)
            VALUES
              (:vid, 'Momentum',  :w_m),
              (:vid, 'Value',     :w_v),
              (:vid, 'Sentiment', :w_s)
            ON CONFLICT (version_id, factor_code)
            DO UPDATE SET weight = EXCLUDED.weight
            """
            ),
            {"vid": vid, "w_m": hw.w_m, "w_v": hw.w_v, "w_s": hw.w_s},
        )
