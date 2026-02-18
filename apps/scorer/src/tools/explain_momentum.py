from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Dict, Tuple

import pandas as pd


def _import_services():
    from apps.scorer.src.services.momentum import MomentumCalculator  # type: ignore
    from apps.scorer.src.services.prices import PriceReader  # type: ignore

    return PriceReader, MomentumCalculator


def _try_settings():
    try:
        from apps.scorer.src.settings import Settings  # type: ignore

        return Settings()
    except Exception:
        return None


def _parse_weights(spec: str | None, defaults: Dict[int, float] | None = None) -> Dict[int, float]:
    weights: Dict[int, float] = dict(defaults or {200: 1.0, 90: 1.0, 50: 1.0, 30: 1.0})
    if not spec:
        return weights
    parts = [p.strip() for p in str(spec).split(",") if p.strip()]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
        elif ":" in p:
            k, v = p.split(":", 1)
        else:
            continue
        try:
            k_i = int(k.strip())
            v_f = float(v.strip())
            weights[k_i] = v_f
        except Exception:
            continue
    return weights


def explain_momentum(
    df: pd.DataFrame,
    *,
    base_weights: Dict[int, float] | None = None,
    min_valid_frac: float = 0.8,
    tstat_cap: float = 3.0,
) -> Tuple[pd.DataFrame, float | None]:
    PriceReader, MomentumCalculator = _import_services()

    rows = []
    combo_num = 0.0
    combo_den = 0.0
    for w in (200, 90, 50, 30):
        s, r2, n = MomentumCalculator.linreg_log_slope_r2(df, w, min_valid_frac=min_valid_frac)
        slope_pct = float(s * 100.0) if s is not None else None
        eff_w = 0.0
        used = False
        r = None
        t = None
        t_factor = None
        if s is not None and r2 is not None and n is not None and n > 2:
            r = (float(r2) ** 0.5) * (1.0 if float(s) >= 0.0 else -1.0)
            denom = 1.0 - (r * r)
            if denom > 0.0:
                t = abs(r) * ((float(n) - 2.0) ** 0.5) / (denom**0.5)
                t_factor = min(1.0, abs(t) / float(max(1e-9, tstat_cap)))
                bw = float((base_weights or {}).get(w, 1.0))
                eff_w = bw * (t_factor**2)
                used = (n >= int(w * float(min_valid_frac))) and (eff_w > 0)
                if used:
                    combo_num += float(s) * eff_w
                    combo_den += eff_w
        rows.append(
            {
                "window": int(w),
                "slope_%_per_day": slope_pct,
                "R2": float(r2) if r2 is not None else None,
                "n_valid": int(n or 0),
                "r_sign": float(r) if r is not None else None,
                "t_stat": float(t) if t is not None else None,
                "t_factor": float(t_factor) if t_factor is not None else None,
                "eff_weight": float(eff_w),
                "used": bool(used),
            }
        )
    blend = (combo_num / combo_den) * 100.0 if combo_den > 0 else None
    return pd.DataFrame(rows), (float(blend) if blend is not None else None)


def _load_df_from_parquet(path: str):
    PriceReader, _ = _import_services()
    return PriceReader.read_price_parquet(path, logger=None)


def main():
    ap = argparse.ArgumentParser(
        description="Explain blended momentum for a single symbol and save a trace."
    )
    ap.add_argument(
        "--symbol",
        "-s",
        help="Ticker symbol (used to infer /data/prices/<SYMBOL>.parquet if --parquet not given)",
    )
    ap.add_argument("--parquet", "-p", help="Path to a parquet file with OHLCV (optional)")
    ap.add_argument(
        "--prices-dir",
        default="/data/prices",
        help="Directory containing <SYMBOL>.parquet (default: /data/prices)",
    )
    ap.add_argument(
        "--out",
        "-o",
        help="Output CSV path (if omitted, writes to ./debug/momentum_<SYMBOL>_<YYYYMMDD>.csv)",
    )
    ap.add_argument(
        "--min-valid-frac",
        type=float,
        default=None,
        help="Minimum valid fraction per window (default from env or 0.8)",
    )
    ap.add_argument(
        "--tstat-cap",
        type=float,
        default=None,
        help="t-stat cap for weighting (default from env or 3.0)",
    )
    ap.add_argument(
        "--base-weights",
        default=None,
        help="Comma-separated window=weight pairs (e.g., '200=1,90=1,50=1,30=1')",
    )
    ap.add_argument("--asof", help="Optional YYYY-MM-DD; truncate series to this date (inclusive)")
    args = ap.parse_args()

    # Resolve paths
    parquet_path = args.parquet
    symbol = (args.symbol or "").upper() if args.symbol else None
    if parquet_path is None:
        if not symbol:
            raise SystemExit("Either --parquet or --symbol is required.")
        parquet_path = os.path.join(args.prices_dir, f"{symbol}.parquet")
    if not os.path.exists(parquet_path):
        raise SystemExit(f"Parquet file not found: {parquet_path}")

    df = _load_df_from_parquet(parquet_path)
    if args.asof:
        try:
            asof = pd.to_datetime(args.asof).normalize()
            df = df.loc[:asof]
        except Exception:
            pass

    # Defaults from Settings if available
    settings = _try_settings()
    min_valid_frac = (
        float(args.min_valid_frac)
        if args.min_valid_frac is not None
        else float(getattr(settings, "scoring_momentum_min_valid_frac", 0.8) or 0.8)
    )
    tstat_cap = (
        float(args.tstat_cap)
        if args.tstat_cap is not None
        else float(getattr(settings, "scoring_momentum_tstat_cap", 3.0) or 3.0)
    )
    base_weights = _parse_weights(
        args.base_weights
        if args.base_weights is not None
        else getattr(settings, "scoring_momentum_window_weights", None),
        defaults={200: 1.0, 90: 1.0, 50: 1.0, 30: 1.0},
    )

    rows_df, blend = explain_momentum(
        df,
        base_weights=base_weights,
        min_valid_frac=min_valid_frac,
        tstat_cap=tstat_cap,
    )

    # Output file paths
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    sym = symbol or os.path.splitext(os.path.basename(parquet_path))[0].upper()
    out_csv = args.out or os.path.join("./debug", f"momentum_{sym}_{ts}.csv")
    out_dir = os.path.dirname(out_csv) or "."
    os.makedirs(out_dir, exist_ok=True)
    rows_df.to_csv(out_csv, index=False)

    # Sidecar JSON summary
    out_json = os.path.splitext(out_csv)[0] + ".json"
    last_date = None
    try:
        idx = df.index
        if not isinstance(idx, pd.DatetimeIndex):
            idx = pd.to_datetime(idx, errors="coerce")
        last_date = pd.to_datetime(idx, errors="coerce").max()
        if pd.notna(last_date):
            last_date = str(pd.to_datetime(last_date).date())
        else:
            last_date = None
    except Exception:
        last_date = None

    summary = {
        "symbol": sym,
        "parquet_path": os.path.abspath(parquet_path),
        "asof": args.asof or last_date,
        "base_weights": base_weights,
        "min_valid_frac": min_valid_frac,
        "tstat_cap": tstat_cap,
        "blend_slope_%_per_day": blend,
        "windows_used": int(rows_df[rows_df["used"]].shape[0]),
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"Wrote momentum trace CSV: {out_csv}")
    print(f"Wrote summary JSON: {out_json}")


if __name__ == "__main__":
    main()
