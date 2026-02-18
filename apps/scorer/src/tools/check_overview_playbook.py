"""
Sanity-check the Overview "playbook" mapping.

This is NOT a production-grade backtest. It is a quick diagnostic that joins:
  - rankalpha.vw_nowcast_snapshot_series_with_deltas (Nowcast v2 snapshots)
  - rankalpha.fact_regime_rules (flow-based regime rules label + tags)
  - rankalpha.vw_stock_price_history (proxy market series, e.g. $SPX or SPY)

Then it computes simple forward returns and basic time-series momentum / reversal
proxies to see whether "Trend / Chop / Risk-Off" aligns with the intended
interpretation on average.

Run (from repo root, with DB env configured like the scorer):
  cd apps/scorer && uv run python src/tools/check_overview_playbook.py --symbol '$SPX' --days 750 --horizon 5
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


def _import_modules():
    from apps.scorer.src.settings import Settings  # type: ignore

    return Settings


def _dsn_from_settings(settings) -> str:
    return "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=settings.db_username,
        pwd=settings.password,
        host=settings.host,
        port=settings.port,
        db=settings.database_name,
    )


def _parse_tags(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if x is not None and str(x).strip()]
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") and s.endswith("}"):
            inner = s[1:-1].strip()
            if not inner:
                return []
            return [x.strip() for x in inner.split(",") if x.strip()]
        if not s:
            return []
        return [s]
    return [str(value).strip()]


def _nowcast_band(label: Optional[str], score: Optional[float]) -> str:
    if label in ("risk_off", "risk_on", "neutral"):
        return str(label)
    if score is not None and np.isfinite(score):
        if score >= 65:
            return "risk_off"
        if score <= 35:
            return "risk_on"
    return "neutral"


def _regime_tape(regime_label: Optional[str], tags: Iterable[str]) -> str:
    raw = (regime_label or "").strip()
    if raw == "Risk-Off":
        return "risk_off"
    if raw == "Trend":
        return "trend"
    if raw == "Chop":
        return "chop"
    tagset = {str(t).strip() for t in tags if str(t).strip()}
    if "MeanReversionFavored" in tagset:
        return "chop"
    return "unknown"


@dataclass(frozen=True)
class Playbook:
    bias: str
    low_conviction: bool
    risk_rising_fast: bool
    defensive_drift: bool
    speculative_mania: bool


def compute_playbook(
    nowcast_label: Optional[str],
    overall_risk_off_score: Optional[float],
    confidence: Optional[float],
    coverage: Optional[float],
    delta_1d: Optional[float],
    delta_5d: Optional[float],
    cross_asset_label: Optional[str],
    regime_rules_label: Optional[str],
    regime_rules_tags: List[str],
) -> Playbook:
    tags = [str(t).strip() for t in regime_rules_tags if str(t).strip()]
    tagset = set(tags)
    defensive_drift = "DefensiveDrift" in tagset
    speculative_mania = "SpeculativeMania" in tagset

    band = _nowcast_band(nowcast_label, overall_risk_off_score)
    tape = _regime_tape(regime_rules_label, tags)

    risk_rising_fast = bool(
        (delta_1d is not None and np.isfinite(delta_1d) and delta_1d >= 5)
        or (delta_5d is not None and np.isfinite(delta_5d) and delta_5d >= 10)
    )

    near_neutral = bool(
        overall_risk_off_score is not None
        and np.isfinite(overall_risk_off_score)
        and 47 < float(overall_risk_off_score) < 53
    )

    low_conviction = bool(
        (confidence is not None and np.isfinite(confidence) and float(confidence) < 0.45)
        or (coverage is not None and np.isfinite(coverage) and float(coverage) < 0.7)
        or (band == "neutral" and near_neutral)
    )

    bias = "balanced"
    if band == "risk_off" or tape == "risk_off" or defensive_drift:
        bias = "defensive"
    elif tape == "trend":
        bias = "momentum" if band == "risk_on" and not risk_rising_fast else "balanced"
    elif tape == "chop":
        bias = "balanced" if band == "risk_on" and not risk_rising_fast else "mean_reversion"
    else:
        bias = "balanced"

    if risk_rising_fast and bias == "momentum":
        bias = "balanced"

    # Keep tags in the output even if they don't change the bias; useful in diagnostics.
    _ = cross_asset_label
    return Playbook(
        bias=bias,
        low_conviction=low_conviction,
        risk_rising_fast=risk_rising_fast,
        defensive_drift=defensive_drift,
        speculative_mania=speculative_mania,
    )


def _load_nowcast(engine, model_version: str, days: int) -> pd.DataFrame:
    q = text(
        """
        WITH d AS (
          SELECT date_key
          FROM rankalpha.vw_nowcast_snapshot_series_with_deltas
          WHERE model_version = :mv
          ORDER BY date_key DESC
          LIMIT :lim
        )
        SELECT as_of_date, date_key, model_version,
               overall_risk_off_score, nowcast_label, confidence, coverage,
               delta_1d, delta_5d, cross_asset_label
        FROM rankalpha.vw_nowcast_snapshot_series_with_deltas
        WHERE model_version = :mv AND date_key IN (SELECT date_key FROM d)
        ORDER BY date_key ASC
        """
    )
    df = pd.read_sql(
        q, engine, params={"mv": model_version, "lim": int(days)}, parse_dates=["as_of_date"]
    )  # type: ignore
    for col in ("overall_risk_off_score", "confidence", "coverage", "delta_1d", "delta_5d"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_regime_rules(engine, days: int) -> pd.DataFrame:
    q = text(
        """
        WITH d AS (
          SELECT date_key
          FROM rankalpha.fact_regime_rules
          ORDER BY date_key DESC
          LIMIT :lim
        )
        SELECT dt.full_date AS as_of_date, r.date_key,
               r.label AS regime_rules_label, r.tags AS regime_rules_tags
        FROM rankalpha.fact_regime_rules r
        JOIN rankalpha.dim_date dt ON dt.date_key = r.date_key
        WHERE r.date_key IN (SELECT date_key FROM d)
        ORDER BY r.date_key ASC
        """
    )
    df = pd.read_sql(q, engine, params={"lim": int(days)}, parse_dates=["as_of_date"])  # type: ignore
    if "regime_rules_tags" in df.columns:
        df["regime_rules_tags"] = df["regime_rules_tags"].apply(_parse_tags)
    return df


def _load_prices(engine, symbol: str, days: int) -> pd.DataFrame:
    q = text(
        """
        WITH d AS (
          SELECT price_date
          FROM rankalpha.vw_stock_price_history
          WHERE symbol = :sym AND adj_close_px IS NOT NULL
          ORDER BY price_date DESC
          LIMIT :lim
        )
        SELECT price_date AS as_of_date, adj_close_px
        FROM rankalpha.vw_stock_price_history
        WHERE symbol = :sym AND price_date IN (SELECT price_date FROM d)
        ORDER BY price_date ASC
        """
    )
    df = pd.read_sql(
        q, engine, params={"sym": symbol, "lim": int(days)}, parse_dates=["as_of_date"]
    )  # type: ignore
    df["adj_close_px"] = pd.to_numeric(df["adj_close_px"], errors="coerce")
    return df


def _summarize(df: pd.DataFrame, horizon: int) -> None:
    out = df.copy()
    out = out.dropna(subset=["adj_close_px"]).sort_values("as_of_date")
    out["log_px"] = np.log(out["adj_close_px"].astype(float))
    out["ret_fwd"] = out["log_px"].shift(-horizon) - out["log_px"]
    out["ret_5d"] = out["log_px"] - out["log_px"].shift(5)
    out["ret_20d"] = out["log_px"] - out["log_px"].shift(20)

    # Time-series proxies (not cross-sectional factors).
    out["ts_mom"] = np.sign(out["ret_20d"]) * out["ret_fwd"]
    out["ts_rev"] = -np.sign(out["ret_5d"]) * out["ret_fwd"]

    out = out.dropna(subset=["ret_fwd", "ret_5d", "ret_20d"]).copy()
    if out.empty:
        print("No usable rows after return construction. Try a larger --days value.")
        return

    def _apply(r):
        p = compute_playbook(
            nowcast_label=r.get("nowcast_label"),
            overall_risk_off_score=r.get("overall_risk_off_score"),
            confidence=r.get("confidence"),
            coverage=r.get("coverage"),
            delta_1d=r.get("delta_1d"),
            delta_5d=r.get("delta_5d"),
            cross_asset_label=r.get("cross_asset_label"),
            regime_rules_label=r.get("regime_rules_label"),
            regime_rules_tags=r.get("regime_rules_tags") or [],
        )
        return pd.Series(
            {
                "bias": p.bias,
                "low_conviction": bool(p.low_conviction),
                "risk_rising_fast": bool(p.risk_rising_fast),
                "defensive_drift": bool(p.defensive_drift),
                "speculative_mania": bool(p.speculative_mania),
            }
        )

    playbook_cols = out.apply(_apply, axis=1)
    out = pd.concat([out, playbook_cols], axis=1)

    def _summary(g: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n": int(len(g)),
                "avg_fwd_ret": float(g["ret_fwd"].mean()),
                "med_fwd_ret": float(g["ret_fwd"].median()),
                "win_rate": float((g["ret_fwd"] > 0).mean()),
                "avg_ts_mom": float(g["ts_mom"].mean()),
                "avg_ts_rev": float(g["ts_rev"].mean()),
            }
        )

    print("\nPlaybook bias summary (log returns):")
    summary = out.groupby("bias").apply(_summary).sort_values("n", ascending=False)
    with pd.option_context("display.float_format", "{:.4f}".format):
        print(summary)

    print("\nSignal-mismatch counts (low conviction / rising risk):")
    flags = out.groupby("bias")[["low_conviction", "risk_rising_fast"]].mean().sort_index()
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(flags)

    print("\nNowcast label x regime label counts:")
    ct = pd.crosstab(out["nowcast_label"], out["regime_rules_label"])
    print(ct)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--symbol", default="$SPX", help="Symbol in vw_stock_price_history (e.g. $SPX, SPY)"
    )
    parser.add_argument(
        "--days", type=int, default=750, help="Lookback trading days to pull (default 750)"
    )
    parser.add_argument(
        "--horizon", type=int, default=5, help="Forward return horizon in trading days (default 5)"
    )
    parser.add_argument(
        "--model-version", default="nowcast_v2", help="Nowcast model version (default nowcast_v2)"
    )
    args = parser.parse_args()

    if args.days < 200:
        raise SystemExit("--days should be at least 200 for stable summaries")
    if args.horizon < 1:
        raise SystemExit("--horizon must be >= 1")

    Settings = _import_modules()
    s = Settings()
    engine = create_engine(_dsn_from_settings(s))

    nowcast = _load_nowcast(engine, model_version=args.model_version, days=args.days)
    regime = _load_regime_rules(engine, days=args.days)
    px = _load_prices(engine, symbol=args.symbol, days=args.days + args.horizon + 25)

    df = nowcast.merge(regime, on="as_of_date", how="inner").merge(px, on="as_of_date", how="inner")
    if df.empty:
        print(
            "No overlap across nowcast/regime-rules/price series. Check symbol and data availability."
        )
        return

    _summarize(df, horizon=int(args.horizon))


if __name__ == "__main__":
    main()
