import glob
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd
from opentelemetry.trace import Status, StatusCode
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from sqlalchemy import text

try:
    from apps.common.src.logging import get_logger, setup_logging
except Exception:  # pragma: no cover - unit tests may stub shared logging module
    from apps.common.src.logging import get_logger  # type: ignore

    def setup_logging(_level: str | int | None = None) -> None:  # type: ignore
        return None


from apps.common.src.observability import (
    init_service_observability,
    report_ratio_threshold,
    sleep_for_metrics_flush,
    start_span,
)
from apps.scorer.src.services.alpha_inputs import AlphaInputs
from apps.scorer.src.services.db import ScoreRepository
from apps.scorer.src.services.momentum import MomentumCalculator
from apps.scorer.src.services.money_flow import MoneyFlowCalculator
from apps.scorer.src.services.prices import PriceReader
from apps.scorer.src.services.valuation import ValuationService
from apps.scorer.src.services.vix_term_structure import VixTermStructureService
from apps.scorer.src.services.vol_risk_premium import VolRiskPremiumService
from apps.scorer.src.settings import Settings

# Optional import of weight computation helpers. Keep lazy to avoid heavy deps
# (e.g., SciPy) during light usage and test collection.
compute_hybrid_weights = None
upsert_weights = None
upsert_versioned_weights = None


def _ensure_weights_imported() -> None:
    global compute_hybrid_weights, upsert_weights, upsert_versioned_weights
    if all([compute_hybrid_weights, upsert_weights, upsert_versioned_weights]):
        return
    from apps.scorer.src.weights import (
        compute_hybrid_weights as _ch,
    )
    from apps.scorer.src.weights import (
        upsert_versioned_weights as _uvw,
    )
    from apps.scorer.src.weights import (
        upsert_weights as _uw,
    )

    compute_hybrid_weights = _ch
    upsert_weights = _uw
    upsert_versioned_weights = _uvw


SOURCE_KEY = 1

SCORE_TYPES = {
    "SMA_200": "SMA 200",
    "LINREG_200": "linear regression 200",
    "LINREG_90": "linear regression 90",
    "LINREG_50": "linear regression 50",
    "LINREG_30": "linear regression 30",
}

# Additional score types sourced from AI analysis
AI_FACTOR_SCORE_TYPES = {
    # Note: 'value_score' intentionally excluded. Valuation is now derived from fundamentals.
    "quality_score": "quality score",
    "momentum_score": "ai momentum score",
    "low_vol_score": "low volatility score",
}

SENTIMENT_SCORE_TYPE = "sentiment score"
FUNDAMENTAL_VALUE_SCORE_TYPE = "value score"
MOMENTUM_SCORE_TYPE = "momentum score"


def _get_registered_metric(name: str) -> Any:
    try:
        return getattr(REGISTRY, "_names_to_collectors", {}).get(name)
    except Exception:
        return None


def _counter(name: str, documentation: str, labelnames: list[str] | None = None) -> Any:
    labelnames = labelnames or []
    try:
        return Counter(name, documentation, labelnames)
    except ValueError:
        existing = _get_registered_metric(name) or _get_registered_metric(
            name.removesuffix("_total")
        )
        if existing is None:
            raise
        return existing


def _histogram(
    name: str,
    documentation: str,
    labelnames: list[str] | None = None,
    *,
    buckets: tuple[int, ...] | None = None,
) -> Any:
    labelnames = labelnames or []
    try:
        return Histogram(name, documentation, labelnames, buckets=buckets)
    except ValueError:
        existing = _get_registered_metric(name)
        if existing is None:
            raise
        return existing


def _gauge(name: str, documentation: str) -> Any:
    try:
        return Gauge(name, documentation)
    except ValueError:
        existing = _get_registered_metric(name)
        if existing is None:
            raise
        return existing


SCORER_RUNS = _counter(
    "rankalpha_scorer_runs_total",
    "Total scorer runs grouped by status.",
    ["status"],
)
SCORER_DURATION = _histogram(
    "rankalpha_scorer_run_seconds",
    "Wall clock duration of scorer runs.",
    ["status"],
    buckets=(10, 30, 60, 120, 300, 600, 1200, 2400, 3600),
)
SCORER_SYMBOLS = _gauge(
    "rankalpha_scorer_symbols_processed",
    "Number of symbols evaluated in the current scorer run.",
)
SCORER_REQUIRED_COVERAGE_RATIO = _gauge(
    "rankalpha_scorer_required_score_coverage_ratio",
    "Coverage ratio for required scores (Momentum + Value) over the primary eligible asset-type universe.",
)
SCORER_REQUIRED_MISSING_RATIO = _gauge(
    "rankalpha_scorer_required_score_missing_ratio",
    "Missing ratio for required scores (Momentum + Value) over the primary eligible asset-type universe.",
)
SCORER_REQUIRED_MISSING_SYMBOLS = _gauge(
    "rankalpha_scorer_required_score_missing_symbols",
    "Count of symbols missing required scores (Momentum + Value) over the primary eligible asset-type universe.",
)
SCORER_ELIGIBLE_SYMBOLS = _gauge(
    "rankalpha_scorer_eligible_symbols",
    "Count of eligible symbols selected for the scorer run.",
)
SCORER_ASOF_PASS_SYMBOLS = _gauge(
    "rankalpha_scorer_asof_pass_symbols",
    "Count of eligible symbols that passed the as-of freshness gate.",
)
SCORER_MOMENTUM_VALID_SYMBOLS = _gauge(
    "rankalpha_scorer_momentum_valid_symbols",
    "Count of symbols with a valid blended momentum result.",
)
SCORER_ASOF_PASS_RATIO = _gauge(
    "rankalpha_scorer_asof_pass_ratio",
    "Ratio of as-of passing symbols over eligible symbols.",
)
SCORER_MOMENTUM_VALID_RATIO = _gauge(
    "rankalpha_scorer_momentum_valid_ratio",
    "Ratio of momentum-valid symbols over as-of passing symbols.",
)
SCORER_PARQUET_TO_MOMENTUM_RATIO = _gauge(
    "rankalpha_scorer_parquet_to_momentum_ratio",
    "Ratio of momentum-valid symbols over eligible symbols.",
)
SCORER_DRIFT_VIOLATIONS = _counter(
    "rankalpha_scorer_drift_violations_total",
    "Count of scorer drift guard violations.",
    ["check"],
)


def _safe_ratio(numerator: int, denominator: int) -> float:
    return float(numerator) / float(max(int(denominator), 1))


def _parse_ratio_setting(value: Any, *, default: float) -> float:
    try:
        parsed = float(value if value is not None else default)
    except Exception:
        parsed = float(default)
    return min(max(parsed, 0.0), 1.0)


def evaluate_stage_drift(
    stage_counts: dict[str, int],
    *,
    min_asof_ratio: float,
    min_momentum_ratio: float,
) -> tuple[dict[str, float | int], list[str]]:
    """Compute scorer stage drift metrics and guard violations."""
    eligible = max(int(stage_counts.get("eligible", 0)), 0)
    asof_pass = max(int(stage_counts.get("asof_pass", 0)), 0)
    momentum_valid = max(int(stage_counts.get("momentum_valid", 0)), 0)

    asof_ratio = _safe_ratio(asof_pass, eligible)
    momentum_ratio = _safe_ratio(momentum_valid, asof_pass)
    parquet_to_momentum_ratio = _safe_ratio(momentum_valid, eligible)

    violations: list[str] = []
    if eligible > 0 and asof_ratio < min_asof_ratio:
        violations.append(
            "eligible_to_asof "
            f"(ratio={asof_ratio:.4f} < min_ratio={min_asof_ratio:.4f}; "
            f"asof_pass={asof_pass}, eligible={eligible})"
        )
    if asof_pass > 0 and momentum_ratio < min_momentum_ratio:
        violations.append(
            "asof_to_momentum "
            f"(ratio={momentum_ratio:.4f} < min_ratio={min_momentum_ratio:.4f}; "
            f"momentum_valid={momentum_valid}, asof_pass={asof_pass})"
        )

    summary: dict[str, float | int] = {
        "eligible": eligible,
        "asof_pass": asof_pass,
        "momentum_valid": momentum_valid,
        "asof_ratio": asof_ratio,
        "momentum_ratio": momentum_ratio,
        "parquet_to_momentum_ratio": parquet_to_momentum_ratio,
        "asof_drift_ratio": max(0.0, 1.0 - asof_ratio),
        "momentum_drift_ratio": max(0.0, 1.0 - momentum_ratio),
    }
    return summary, violations


def _enforce_stage_drift_guard(
    stage_counts: dict[str, int],
    *,
    settings: Any,
    logger: Any,
    span: Any,
) -> dict[str, float | int]:
    min_asof_ratio = _parse_ratio_setting(
        getattr(settings, "scoring_asof_pass_min_ratio", None), default=0.5
    )
    min_momentum_ratio = _parse_ratio_setting(
        getattr(settings, "scoring_momentum_valid_min_ratio", None), default=0.5
    )
    drift_summary, drift_violations = evaluate_stage_drift(
        stage_counts,
        min_asof_ratio=min_asof_ratio,
        min_momentum_ratio=min_momentum_ratio,
    )
    try:
        SCORER_ASOF_PASS_SYMBOLS.set(int(drift_summary["asof_pass"]))
        SCORER_MOMENTUM_VALID_SYMBOLS.set(int(drift_summary["momentum_valid"]))
        SCORER_ASOF_PASS_RATIO.set(float(drift_summary["asof_ratio"]))
        SCORER_MOMENTUM_VALID_RATIO.set(float(drift_summary["momentum_ratio"]))
        SCORER_PARQUET_TO_MOMENTUM_RATIO.set(float(drift_summary["parquet_to_momentum_ratio"]))
    except Exception:
        pass
    try:
        span.set_attribute("scorer.drift.eligible", int(drift_summary["eligible"]))
        span.set_attribute("scorer.drift.asof_pass", int(drift_summary["asof_pass"]))
        span.set_attribute("scorer.drift.momentum_valid", int(drift_summary["momentum_valid"]))
        span.set_attribute("scorer.drift.asof_ratio", float(drift_summary["asof_ratio"]))
        span.set_attribute("scorer.drift.momentum_ratio", float(drift_summary["momentum_ratio"]))
        span.set_attribute(
            "scorer.drift.parquet_to_momentum_ratio",
            float(drift_summary["parquet_to_momentum_ratio"]),
        )
    except Exception:
        pass
    logger.info(
        "Scorer drift: eligible=%d asof_pass=%d momentum_valid=%d asof_ratio=%.4f momentum_ratio=%.4f parquet_to_momentum_ratio=%.4f",
        int(drift_summary["eligible"]),
        int(drift_summary["asof_pass"]),
        int(drift_summary["momentum_valid"]),
        float(drift_summary["asof_ratio"]),
        float(drift_summary["momentum_ratio"]),
        float(drift_summary["parquet_to_momentum_ratio"]),
    )
    if int(drift_summary["eligible"]) > 0:
        report_ratio_threshold(
            service="rankalpha-scorer",
            check="eligible_to_asof_drift",
            ratio=float(drift_summary["asof_drift_ratio"]),
            threshold=max(0.0, 1.0 - min_asof_ratio),
            total=int(drift_summary["eligible"]),
            affected=max(
                int(drift_summary["eligible"]) - int(drift_summary["asof_pass"]),
                0,
            ),
            level="error",
        )
    if int(drift_summary["asof_pass"]) > 0:
        report_ratio_threshold(
            service="rankalpha-scorer",
            check="asof_to_momentum_drift",
            ratio=float(drift_summary["momentum_drift_ratio"]),
            threshold=max(0.0, 1.0 - min_momentum_ratio),
            total=int(drift_summary["asof_pass"]),
            affected=max(
                int(drift_summary["asof_pass"]) - int(drift_summary["momentum_valid"]),
                0,
            ),
            level="error",
        )
    if drift_violations:
        try:
            for check in ("eligible_to_asof", "asof_to_momentum"):
                if any(v.startswith(check) for v in drift_violations):
                    SCORER_DRIFT_VIOLATIONS.labels(check=check).inc()
        except Exception:
            pass
        raise RuntimeError("Scorer drift guard triggered: " + "; ".join(drift_violations))
    return drift_summary


def _select_primary_eligible_asset_type(engine, logger) -> str | None:
    """Pick the most common eligible asset_type as the 'primary' universe for required-score checks.

    This prevents false positives when the eligible universe contains a minority of instruments that
    legitimately lack fundamentals-based Value scores (e.g., ETP/ETF-like assets).
    """
    try:
        df = pd.read_sql_query(
            text(
                """
                SELECT ue.asset_type, COUNT(*) AS n
                FROM rankalpha.mv_universe_eligible ue
                JOIN rankalpha.dim_stock ds ON ds.symbol = ue.symbol
                WHERE ds.is_active IS TRUE
                  AND ue.eligible IS TRUE
                GROUP BY ue.asset_type
                ORDER BY n DESC
                LIMIT 10
                """
            ),
            engine,
        )
        if df.empty:
            return None
        primary = str(df.iloc[0]["asset_type"]) if pd.notna(df.iloc[0]["asset_type"]) else None
        if primary:
            try:
                dist = {str(r["asset_type"]): int(r["n"]) for _, r in df.iterrows()}
                logger.info(
                    "Required-score universe asset_type=%s (eligible dist=%s)", primary, dist
                )
            except Exception:
                logger.info("Required-score universe asset_type=%s", primary)
        return primary
    except Exception as exc:
        logger.warning(
            "Could not determine primary eligible asset_type for required-score checks: %s", exc
        )
        return None


def _fetch_required_score_coverage(
    engine, *, primary_asset_type: str | None
) -> tuple[int, int, list[str]]:
    """Return (total, missing, sample_symbols) for required scores (Momentum + Value) in DB."""
    where_asset = ""
    params: dict[str, object] = {}
    if primary_asset_type:
        where_asset = "AND ue.asset_type = :asset_type"
        params["asset_type"] = primary_asset_type

    totals = pd.read_sql_query(
        text(
            f"""
            WITH universe AS (
              SELECT UPPER(ds.symbol) AS symbol
              FROM rankalpha.dim_stock ds
              JOIN rankalpha.mv_universe_eligible ue
                ON ue.symbol = ds.symbol
               AND ue.eligible IS TRUE
              WHERE ds.is_active IS TRUE
              {where_asset}
            )
            SELECT
              COUNT(*) AS total,
              COUNT(*) FILTER (WHERE g.momentum_score IS NOT NULL AND g.value_score IS NOT NULL) AS ok,
              COUNT(*) FILTER (WHERE g.momentum_score IS NULL OR g.value_score IS NULL) AS missing
            FROM universe u
            JOIN rankalpha.mv_latest_grades g ON g.symbol = u.symbol
            """
        ),
        engine,
        params=params,
    )
    total = int(totals.iloc[0]["total"]) if not totals.empty else 0
    missing = int(totals.iloc[0]["missing"]) if not totals.empty else 0

    sample_df = pd.read_sql_query(
        text(
            f"""
            WITH universe AS (
              SELECT UPPER(ds.symbol) AS symbol
              FROM rankalpha.dim_stock ds
              JOIN rankalpha.mv_universe_eligible ue
                ON ue.symbol = ds.symbol
               AND ue.eligible IS TRUE
              WHERE ds.is_active IS TRUE
              {where_asset}
            )
            SELECT u.symbol
            FROM universe u
            JOIN rankalpha.mv_latest_grades g ON g.symbol = u.symbol
            WHERE g.momentum_score IS NULL OR g.value_score IS NULL
            ORDER BY u.symbol
            LIMIT 25
            """
        ),
        engine,
        params=params,
    )
    sample = [str(s).upper() for s in sample_df["symbol"].tolist()] if not sample_df.empty else []
    return total, missing, sample


def _normalize_parquet_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure columns are simple strings and include canonical OHLCV names.

    - Flattens MultiIndex by joining parts with '_' then collapses to base name
      for common OHLCV fields (e.g., 'Close_ABT' -> 'Close').
    - Coerces all labels to str and makes names unique when necessary.
    """
    cols = df.columns
    out = df.copy()
    if isinstance(cols, pd.MultiIndex):
        flat: list[str] = []
        for tup in cols:
            parts = [str(p) for p in tup if p is not None and str(p) != ""]
            name = "_".join(parts) if parts else ""
            for base in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
                if name.startswith(base):
                    name = base
                    break
            flat.append(name or "col")
        out.columns = pd.Index(flat, dtype=object)
    else:
        out.columns = pd.Index([str(c).strip() for c in cols], dtype=object)
    if not out.columns.is_unique:
        seen = {}
        uniq = []
        for c in out.columns:
            if c in seen:
                seen[c] += 1
                uniq.append(f"{c}__{seen[c]}")
            else:
                seen[c] = 0
                uniq.append(c)
        out.columns = pd.Index(uniq, dtype=object)
    return out


def _read_price_parquet(path: str, logger) -> pd.DataFrame:
    """Robustly read a price parquet file.

    Many legacy files were written with mixed/duplicate column names (e.g.,
    both 'Close' and ('Close','TICKER')). Reading the full table can fail in
    pyarrow with ArrowInvalid: Multiple matches for FieldRef. To avoid this,
    read only the needed 'Close' column, then normalize columns and index.
    """
    last_exc = None
    df = None
    # Minimal sets for scorer computations (prefer Adj Close)
    for cols in (
        ["Adj Close"],
        ["Adj Close", "Close"],
        ["Adj Close", "Close", "Open", "High", "Low", "Volume"],
        ["Close"],
        ["Close", "Open", "High", "Low", "Volume"],
    ):
        try:
            df = pd.read_parquet(path, engine="pyarrow", columns=cols)
            break
        except Exception as exc:
            last_exc = exc
            continue
    else:
        # As a last resort, try a plain read to capture a clearer error,
        # but still fall through to normalization before returning.
        try:
            df = pd.read_parquet(path, engine="pyarrow")
        except Exception:
            # Re-raise the earlier, likely more informative exception
            raise last_exc

    # Ensure datetime index
    try:
        if not isinstance(df.index, pd.DatetimeIndex):
            df_full = None
            try:
                df_full = pd.read_parquet(path, engine="pyarrow")
            except Exception:
                df_full = None

            if df_full is not None and isinstance(df_full.index, pd.DatetimeIndex):
                df = df_full
            else:
                for frame in (df, df_full):
                    if frame is None:
                        continue
                    for candidate in ("Date", "__index_level_0__", "Datetime", "Timestamp"):
                        if candidate not in frame.columns:
                            continue
                        parsed = pd.to_datetime(frame[candidate], errors="coerce")
                        if parsed.notna().any() and len(parsed) == len(df.index):
                            df = df.copy()
                            df.index = parsed
                            break
                    if isinstance(df.index, pd.DatetimeIndex):
                        break

                if not isinstance(df.index, pd.DatetimeIndex):
                    if not (
                        isinstance(df.index, pd.RangeIndex)
                        or pd.api.types.is_numeric_dtype(getattr(df.index, "dtype", None))
                    ):
                        idx = pd.to_datetime(df.index, errors="coerce")
                        if not pd.isna(idx).all():
                            df.index = idx
    except Exception:
        pass
    # Normalize column names (collapse MI like 'Close_ABT' -> 'Close')
    df = _normalize_parquet_columns(df)
    # Robust hygiene: tz-naive index, drop duplicates, sort ascending
    try:
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df = df[~df.index.duplicated(keep="last")].sort_index()
    except Exception:
        pass
    return df


def _select_close(df: pd.DataFrame) -> pd.Series:
    """Return adjusted close series if available, else close, coerced to float.

    When neither price column is populated, returns an empty float Series so
    downstream callers skip score generation instead of using the wrong field
    (e.g., Volume).
    """
    if "Adj Close" in df.columns:
        s = pd.to_numeric(df["Adj Close"], errors="coerce")
        if not s.dropna().empty:
            return s.astype(float)
    if "Close" in df.columns:
        s = pd.to_numeric(df["Close"], errors="coerce")
        if not s.dropna().empty:
            return s.astype(float)
    # No usable price column available
    return pd.Series(index=df.index, dtype=float)


def _round2(value, max_abs: float = 9_999_999_999.99) -> float | None:
    """Round to 2 decimals with guards for NaN/overflow.

    Returns None when the input cannot be coerced to a scalar float, is NaN,
    or falls outside the configured absolute bound (default matches
    NUMERIC(14,2)).
    """
    if value is None:
        return None
    # Reduce common pandas wrappers to a scalar
    try:
        # pandas/numpy scalar
        if hasattr(value, "item") and not isinstance(value, (pd.Series, pd.DataFrame)):
            value = value.item()
        # 1-element Series/DataFrame -> take last
        if isinstance(value, pd.Series):
            if value.empty:
                return None
            value = value.iloc[-1]
        if isinstance(value, pd.DataFrame):
            if value.empty:
                return None
            # take last cell
            value = value.iloc[-1].iloc[-1]
        v = float(value)
    except Exception:
        return None
    if pd.isna(v):
        return None
    if abs(v) > max_abs:
        return None
    return float(f"{v:.2f}")


def _normalize_series(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series([None] * len(values), index=values.index)
    numeric = pd.to_numeric(values, errors="coerce")
    data = numeric.dropna().astype(float)
    if data.empty:
        return pd.Series([None] * len(values), index=values.index)
    p05 = data.quantile(0.05)
    p95 = data.quantile(0.95)
    if pd.isna(p05) or pd.isna(p95) or abs(p95 - p05) < 1e-9:
        return pd.Series([50.0] * len(values), index=values.index)

    def _scale(x):
        if pd.isna(x):
            return None
        norm = (float(x) - p05) / (p95 - p05)
        return max(0.0, min(100.0, norm * 100.0))

    return numeric.apply(_scale)


def _parse_mf_weights(raw: str | None) -> tuple[float, float, float, float]:
    """Parse SCORING_MF_COMPONENT_WEIGHTS into weight tuple (cmf20, cmf5, vol_surp, ret20)."""
    default = (0.4, 0.2, 0.3, 0.1)
    if not raw:
        return default
    weights = dict(cmf20=0.4, cmf5=0.2, vol_surp=0.3, ret20=0.1)
    try:
        parts = [p.strip() for p in str(raw).split(",") if p.strip()]
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
            elif ":" in p:
                k, v = p.split(":", 1)
            else:
                continue
            k = k.strip().lower()
            v = float(v.strip())
            if k in ("cmf20", "cmf_med", "cmf_20"):
                weights["cmf20"] = v
            elif k in ("cmf5", "cmf_short", "cmf_5"):
                weights["cmf5"] = v
            elif k in ("vol_surp", "vol", "vol_surp_60"):
                weights["vol_surp"] = v
            elif k in ("ret20", "ret_20", "return20"):
                weights["ret20"] = v
        total = sum(weights.values())
        if total <= 0:
            return default
        return (
            weights["cmf20"],
            weights["cmf5"],
            weights["vol_surp"],
            weights["ret20"],
        )
    except Exception:
        return default


def _select_asof_date_with_coverage(
    engine, settings, logger, active_symbols: set[str] | None = None
):
    """Pick latest as-of date using price coverage across the eligible universe.

    Returns (as_of_date: Timestamp|None, as_of_date_key: int|None, coverage: float|None,
             have_px: int|None, n_elig: int|None).
    """
    try:
        min_cov = float(getattr(settings, "scoring_asof_min_coverage", 0.5) or 0.5)
        q_elig = """
            SELECT COUNT(1) AS n
            FROM rankalpha.dim_stock ds
            JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
            WHERE ds.is_active IS TRUE
            """
        elig_df = pd.read_sql_query(q_elig, engine)
        n_elig = int(elig_df.loc[0, "n"]) if not elig_df.empty else 0
        if (not n_elig) and active_symbols:
            n_elig = int(len(active_symbols))

        q_cov = """
            SELECT sp.date_key, d.full_date, COUNT(DISTINCT sp.stock_key) AS have_px
            FROM rankalpha.fact_security_price sp
            JOIN rankalpha.dim_stock s ON s.stock_key = sp.stock_key
            JOIN rankalpha.mv_universe_eligible ue ON ue.symbol = s.symbol AND ue.eligible IS TRUE
            JOIN rankalpha.dim_date d ON d.date_key = sp.date_key
            WHERE s.is_active IS TRUE
            GROUP BY sp.date_key, d.full_date
            ORDER BY sp.date_key DESC
            LIMIT 120
            """
        cov_df = pd.read_sql_query(q_cov, engine, parse_dates=["full_date"]).sort_values(
            "date_key", ascending=False
        )
        chosen = None
        cov_note = ""
        if n_elig > 0 and not cov_df.empty:
            cov_df["coverage"] = cov_df["have_px"].astype(float) / float(n_elig)
            meets = cov_df[cov_df["coverage"] >= min_cov]
            chosen = meets.iloc[0] if not meets.empty else cov_df.iloc[0]
            cov_note = (
                f"coverage={float(chosen['coverage']):.2%} (eligible={n_elig}, have_px={int(chosen['have_px'])})"
                if "coverage" in chosen
                else ""
            )
        elif not cov_df.empty:
            chosen = cov_df.iloc[0]
            cov_note = f"have_px={int(chosen['have_px'])} (eligible unknown)"

        if chosen is None or pd.isna(chosen["full_date"]):
            return None, None, None, None, None
        as_of_date = pd.to_datetime(chosen["full_date"]).normalize()
        as_of_date_key = int(chosen["date_key"])  # e.g., 20250131
        if cov_note:
            logger and getattr(logger, "info", lambda *a, **k: None)(
                "As-of trading day (from prices): %s (date_key=%s) %s",
                as_of_date.date(),
                as_of_date_key,
                cov_note,
            )
        return (
            as_of_date,
            as_of_date_key,
            float(chosen.get("coverage") or 0.0),
            int(chosen.get("have_px") or 0),
            n_elig,
        )
    except Exception:
        return None, None, None, None, None


def _blend_momentum_series(
    raw_score: pd.Series, resid_score: pd.Series, settings
) -> tuple[pd.Series, str, float, float]:
    """Return composite momentum series and effective config used.

    Applies mode and weights from settings, with renormalization and fallback defaults.
    """
    mode = (
        str(getattr(settings, "scoring_momentum_composite_mode", "blend") or "blend")
        .strip()
        .lower()
    )

    # Honor zero weights: only fall back when value is None or empty string
    def _get_weight(attr_name: str, default: float) -> float:
        val = getattr(settings, attr_name, None)
        if val is None:
            return float(default)
        # Allow strings from env; treat blank as missing
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return float(default)
            try:
                return float(s)
            except Exception:
                return float(default)
        try:
            return float(val)
        except Exception:
            return float(default)

    w_resid = _get_weight("scoring_momentum_residual_weight", 0.7)
    w_raw = _get_weight("scoring_momentum_raw_weight", 0.3)
    s = w_resid + w_raw
    if s <= 0:
        w_resid, w_raw = 0.7, 0.3
        s = 1.0
    w_resid /= s
    w_raw /= s
    if mode == "residual":
        return resid_score, mode, w_resid, w_raw
    if mode == "raw":
        return raw_score, mode, w_resid, w_raw
    comp = resid_score * w_resid + raw_score * w_raw
    return comp, mode, w_resid, w_raw


def fetch_score_type_keys(cursor):
    # Backward-compat wrapper to keep minimal diffs in main
    cursor.execute("SELECT score_type_key, score_type_name FROM dim_score_type")
    return {name.lower(): key for key, name in cursor.fetchall()}


def _flush_score_rows(repo: ScoreRepository, cursor, rows, logger, label: str) -> int:
    if not rows:
        return 0
    started = time.perf_counter()
    try:
        inserted = repo.insert_scores(cursor, rows)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if inserted != len(rows):
            logger.warning(
                "Scorer batch %s: inserted %d/%d rows in %.1f ms (some rows were skipped in fallback mode)",
                label,
                inserted,
                len(rows),
                elapsed_ms,
            )
        else:
            logger.info(
                "Scorer batch %s: inserted %d rows in %.1f ms",
                label,
                inserted,
                elapsed_ms,
            )
        return inserted
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.warning(
            "Failed to insert %s rows after %.1f ms: %s",
            label,
            elapsed_ms,
            exc,
        )
        return 0


def _execute_scorer(span: Any, settings: Settings) -> None:
    input_dir = "/data/prices"
    parquet_files = glob.glob(os.path.join(input_dir, "*.parquet"))
    try:
        span.set_attribute("scorer.input_dir", input_dir)
        span.set_attribute("scorer.parquet_files_initial", len(parquet_files))
    except Exception:
        pass

    logger = get_logger(__name__)
    logger.info("Starting scoring run")
    logger.info(f"Price files directory: {input_dir}")
    logger.info(f"Found {len(parquet_files)} parquet file(s)")
    parquet_files_initial = len(parquet_files)

    dsn = "postgresql://{user}:{pwd}@{host}:{port}/{db}".format(
        user=settings.db_username,
        pwd=settings.password,
        host=settings.host,
        port=settings.port,
        db=settings.database_name,
    )

    logger.info("Connecting to Postgres ...")
    repo = ScoreRepository(dsn, logger)
    engine = repo.engine
    conn = repo.connect()
    cursor = conn.cursor()
    logger.info("Connected to Postgres")

    # Compute and upsert hybrid weights monthly (or when forced)
    try:
        import pandas as _pd

        latest_df = _pd.read_sql_query(
            """
            SELECT MAX(d.full_date) AS as_of_date
            FROM rankalpha.dim_date d
            JOIN rankalpha.fact_score_history f ON f.date_key = d.date_key
            """,
            engine,
        )
        if not latest_df.empty and _pd.notna(latest_df.loc[0, "as_of_date"]):
            latest_dt = _pd.to_datetime(latest_df.loc[0, "as_of_date"]).normalize()
            y, m = int(latest_dt.year), int(latest_dt.month)
            exist = _pd.read_sql_query(
                f"""
                SELECT 1 FROM rankalpha.dim_model_weight
                WHERE method = 'HYBRID_IC_RP'
                  AND EXTRACT(YEAR  FROM as_of_date) = {y}
                  AND EXTRACT(MONTH FROM as_of_date) = {m}
                LIMIT 1
                """,
                engine,
            )
            # Force recompute via env or admin flag
            force_env = bool(settings.scoring_weight_force)
            force_flag_df = _pd.read_sql_query(
                """
                SELECT flag_value FROM rankalpha.admin_flag
                WHERE flag_name = 'force_recompute_weights'
                LIMIT 1
                """,
                engine,
            )
            force_flag = (
                bool(force_flag_df.iloc[0]["flag_value"]) if not force_flag_df.empty else False
            )
            do_force = force_env or force_flag
            if exist.empty or do_force:
                lambda_rp = float(settings.scoring_weight_lambda_rp or 0.4)
                window_days = int(settings.scoring_weight_window_days or 504)
                horizon_days = int(settings.scoring_weight_horizon_days or 21)
                _ensure_weights_imported()
                hw = compute_hybrid_weights(
                    engine,
                    window_days=window_days,
                    horizon_days=horizon_days,
                    lambda_rp=lambda_rp,
                )
                if hw is not None:
                    upsert_weights(engine, hw)
                    # Also persist time-versioned weights (SCD-2) for as-of queries
                    try:
                        upsert_versioned_weights(engine, hw)
                    except Exception as _exc:
                        logger.warning(f"Versioned weight upsert failed (non-fatal): {_exc}")
                    logger.info(
                        f"Hybrid weights upserted: wM={hw.w_m:.2f}, wV={hw.w_v:.2f}, wS={hw.w_s:.2f}, lambda={hw.lambda_rp:.2f}, alpha={hw.alpha_shrink:.2f}"
                    )
                    if force_flag:
                        from sqlalchemy import text as _text

                        with engine.begin() as conn2:
                            conn2.execute(
                                _text(
                                    "UPDATE rankalpha.admin_flag SET flag_value=FALSE, updated_at=now() WHERE flag_name='force_recompute_weights'"
                                )
                            )
            else:
                logger.info(f"Weights already computed for {y}-{m:02d}; skipping recompute.")
        else:
            logger.warning("Could not determine latest trading date; skipping weight recompute.")
    except Exception as exc:
        logger.warning(f"Hybrid weight monthly check failed: {exc}")

    # Restrict scoring universe to active AND eligible stocks (price/liquidity policy; ETFs included).
    try:
        cursor.execute(
            """
            SELECT UPPER(ds.symbol)
            FROM dim_stock ds
            JOIN mv_universe_eligible ue ON ue.symbol = ds.symbol AND ue.eligible IS TRUE
            WHERE ds.is_active IS TRUE
            """
        )
        active_symbols = {str(r[0]).upper() for r in cursor.fetchall()}
    except Exception as exc:
        logger.warning(
            f"Could not load active symbols; proceeding with all parquets. Reason: {exc}"
        )
        active_symbols = set()
    if active_symbols:
        before = len(parquet_files)
        parquet_files = [
            f
            for f in parquet_files
            if os.path.splitext(os.path.basename(f))[0].upper() in active_symbols
        ]
        logger.info(f"Filtered parquet files by active symbols: {before} -> {len(parquet_files)}")
    parquet_files_eligible = len(parquet_files)
    SCORER_SYMBOLS.set(len(parquet_files))
    SCORER_ELIGIBLE_SYMBOLS.set(parquet_files_eligible)
    try:
        span.set_attribute("scorer.parquet_files_final", len(parquet_files))
        span.add_event("scorer.symbols_selected", {"count": len(parquet_files)})
    except Exception:
        pass

    repo.ensure_score_types(cursor)
    score_type_map = repo.fetch_score_type_keys(cursor)
    logger.info(f"Registered score types: {sorted(list(score_type_map.keys()))}")
    alpha_inputs = AlphaInputs(engine, logger)
    valuation = ValuationService(engine, logger)
    mf_calc = (
        MoneyFlowCalculator(min_valid_frac=float(settings.scoring_mf_min_valid_frac or 0.8))
        if MoneyFlowCalculator
        else None
    )
    as_of_date, as_of_date_key, _cov, _have_px, _n_elig = _select_asof_date_with_coverage(
        engine, settings, logger, active_symbols
    )
    if as_of_date is None or as_of_date_key is None:
        logger.warning(
            "Could not determine as-of date from price coverage; cross-sectional momentum will be skipped"
        )
    # Look up previous trading day for relaxed acceptance window
    prev_trading_date = None
    if as_of_date is not None:
        try:
            # Grace window: previous N trading days (default 1)
            try:
                grace_days = int(getattr(settings, "scoring_asof_grace_trading_days", 1) or 1)
            except Exception:
                grace_days = 1
            if grace_days <= 0:
                prev_trading_date = as_of_date
            else:
                cursor.execute(
                    """
                    SELECT full_date
                    FROM rankalpha.dim_date
                    WHERE is_trading_day AND full_date < %s
                    ORDER BY full_date DESC
                    LIMIT %s
                    """,
                    (as_of_date.date(), grace_days),
                )
                dates = [pd.to_datetime(r[0]).normalize() for r in cursor.fetchall() if r and r[0]]
                prev_trading_date = dates[-1] if dates else as_of_date
        except Exception:
            prev_trading_date = None
    # Load optional inputs (AI, fundamentals) best-effort
    try:
        ai_scores = alpha_inputs.load_ai_scores()
        logger.info(f"Loaded AI scores for {len(ai_scores)} symbol(s)")
    except Exception as exc:
        logger.warning(f"AI scores unavailable: {exc}")
        ai_scores = {}

    try:
        fundamental_value = valuation.compute_valuation_scores(
            sector_weight=float(settings.scoring_valuation_sector_weight or 0.7),
            market_weight=float(settings.scoring_valuation_market_weight or 0.3),
            min_sector_size=int(settings.scoring_valuation_min_sector_size or 5),
        )
        logger.info(f"Computed fundamentals valuation for {len(fundamental_value)} symbol(s)")
    except Exception as exc:
        logger.warning(f"Fundamentals valuation unavailable: {exc}")
        fundamental_value = {}

    # Money-flow eligibility: symbols must have a non-empty, non-UNKNOWN sector.
    sector_map: dict[str, str | None] = {}
    mf_candidates: set[str] = set()
    if mf_calc:
        try:
            sec_df = pd.read_sql_query(
                "SELECT UPPER(symbol) AS symbol, sector FROM rankalpha.dim_stock WHERE is_active IS TRUE",
                engine,
            )
            sector_map = {row.symbol: row.sector for _, row in sec_df.iterrows()}
            for sym, sec in sector_map.items():
                if sec is None:
                    continue
                sec_trim = str(sec).strip()
                if sec_trim == "" or sec_trim.upper() == "UNKNOWN":
                    continue
                mf_candidates.add(sym)
        except Exception as exc:
            logger.warning(
                f"Could not build sector map for money flow; skipping money-flow scoring. Reason: {exc}"
            )
            mf_candidates = set()
    else:
        mf_candidates = set()

    processed_tickers: set[str] = set()

    inserted_counts = {
        "technicals": 0,
        "ai_factors": 0,
        "sentiment": 0,
        "valuation": 0,
        "momentum": 0,
        "money_flow": 0,
    }
    value_symbols: set[str] = set()
    momentum_symbols: set[str] = set()
    technical_rows: list[tuple[int, int, int, float]] = []
    ai_factor_rows: list[tuple[int, int, int, float]] = []
    sentiment_rows: list[tuple[int, int, int, float]] = []
    valuation_rows: list[tuple[int, int, int, float]] = []

    if len(parquet_files) == 0:
        logger.info("No price files found; skipping technical momentum inserts")

    # Collect per-ticker momentum (blended across windows, R^2-weighted). We compute
    # both raw and sector-neutral residual legs and use a 70/30 blend for the composite.
    combined_momentum: dict[str, tuple[int, int | None, float]] = {}
    stage_counts = {
        "parquet_total": int(parquet_files_initial),
        "eligible": int(parquet_files_eligible),
        "unreadable_parquet": 0,
        "processed": 0,
        "asof_pass": 0,
        "asof_skip_no_latest": 0,
        "asof_skip_stale": 0,
        "missing_price": 0,
        "momentum_valid": 0,
    }
    mf_components: dict[str, dict[str, float | int | None]] = {}
    mf_stats = {
        "candidates": len(mf_candidates),
        "attempted": 0,
        "added": 0,
        "miss_cmf20": 0,
        "miss_vol": 0,
        "no_price": 0,
    }

    # Parse base weights for momentum windows from env, default 1.0
    base_weights: dict[int, float] = {200: 1.0, 90: 1.0, 50: 1.0, 30: 1.0}
    try:
        conf = settings.scoring_momentum_window_weights
        if conf:
            parts = [p.strip() for p in str(conf).split(",") if p.strip()]
            for p in parts:
                if "=" in p:
                    k, v = p.split("=", 1)
                elif ":" in p:
                    k, v = p.split(":", 1)
                else:
                    continue
                k = int(k.strip())
                v = float(v.strip())
                base_weights[k] = v
    except Exception as exc:
        logger.warning(f"Could not parse SCORING_MOMENTUM_WINDOW_WEIGHTS: {exc}")

    logger.info(
        "Momentum config: base_weights=%s, min_valid_frac=%s, tstat_cap=%s (blend residual/raw=70/30)",
        base_weights,
        (settings.scoring_momentum_min_valid_frac or 0.8),
        (settings.scoring_momentum_tstat_cap or 3.0),
    )

    for file in parquet_files:
        ticker = os.path.splitext(os.path.basename(file))[0]
        try:
            prefer_full = bool(mf_calc and ticker.upper() in mf_candidates)
            df = PriceReader.read_price_parquet(file, logger, prefer_full_ohlcv=prefer_full)
        except Exception as exc:
            stage_counts["unreadable_parquet"] += 1
            logger.warning(
                f"Skipping {os.path.basename(file)} due to unreadable Parquet schema (likely mixed/duplicate columns). "
                f"Reason: {exc}"
            )
            continue
        stage_counts["processed"] += 1
        processed_tickers.add(ticker.upper())

        # Enforce single as-of trading day with relaxed acceptance:
        # - Accept when the ticker's latest price date >= as_of_date (we will truncate to as_of_date)
        # - Also accept when the latest price date equals the previous trading day
        #   (one-day behind tolerance), to avoid dropping otherwise-eligible symbols.
        # - Skip only if the latest price date is older than the prev trading day.
        date_key = None
        if as_of_date is not None:
            try:
                px = PriceReader.select_close(df)
                last_ts = pd.to_datetime(px.dropna().index.max()) if not px.dropna().empty else None
            except Exception:
                last_ts = None
            allowed_min = prev_trading_date or as_of_date
            if last_ts is None or pd.isna(last_ts):
                stage_counts["asof_skip_no_latest"] += 1
                logger.info(
                    f"Skipping {ticker}: no latest price to compare against as-of {as_of_date.date()}"
                )
                continue
            last_day = last_ts.normalize()
            if last_day < allowed_min:
                stage_counts["asof_skip_stale"] += 1
                logger.info(
                    f"Skipping {ticker}: latest price date {last_day.date()} older than allowed window [{allowed_min.date()}..{as_of_date.date()}]"
                )
                continue
            # Truncate to as-of date for computation
            try:
                df = df.loc[:as_of_date]
            except Exception:
                pass
            date_key = int(as_of_date_key) if as_of_date_key is not None else None
        else:
            # Fallback: use per-ticker latest date_key if as-of date not available
            date_key = PriceReader.get_latest_date_key(df)
        stage_counts["asof_pass"] += 1
        stock_key = repo.fetch_stock_key(cursor, ticker)

        if stock_key is None:
            print(f"Ticker {ticker} not found in dim_stock.")
            continue

        # Ensure we actually have price data before attempting technical scores.
        has_price = False
        for col in ("Adj Close", "Close"):
            if col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce")
                if not series.dropna().empty:
                    has_price = True
                    break
        if not has_price:
            stage_counts["missing_price"] += 1
            logger.warning(
                f"Skipping technical scores for {ticker}: missing usable Close/Adj Close data"
            )

        # Money flow components (only for symbols with valid sector and eligible universe)
        if mf_calc and ticker.upper() in mf_candidates:
            if not has_price:
                mf_stats["no_price"] += 1
            else:
                mf_stats["attempted"] += 1
                comps = mf_calc.compute_components(df)
                if comps.get("cmf_20") is None:
                    mf_stats["miss_cmf20"] += 1
                if comps.get("vol_surp_60") is None:
                    mf_stats["miss_vol"] += 1
                if (
                    comps.get("cmf_20") is not None
                    and comps.get("vol_surp_60") is not None
                    and date_key is not None
                    and stock_key is not None
                ):
                    mf_components[ticker.upper()] = {
                        "date_key": int(date_key),
                        "stock_key": int(stock_key),
                        "cmf_5": comps.get("cmf_5"),
                        "cmf_20": comps.get("cmf_20"),
                        "vol_surp_60": comps.get("vol_surp_60"),
                        "ret_20": comps.get("ret_20"),
                    }
                    mf_stats["added"] += 1

        # Technicals: use log-price slope for LINREG_* to express per-day log return (%/day)
        scores = {
            "SMA_200": MomentumCalculator.sma200_raw(df),
        }
        min_valid_frac_run = float(settings.scoring_momentum_min_valid_frac or 0.8)
        for w in (200, 90, 50, 30):
            s, _r2, _n = MomentumCalculator.linreg_log_slope_r2(
                df, w, min_valid_frac=min_valid_frac_run
            )
            scores[f"LINREG_{w}"] = (s * 100.0) if s is not None else None

        for score_label, value in scores.items():
            if value is None:
                continue
            score_name = SCORE_TYPES[score_label].lower()
            score_type_key = score_type_map.get(score_name)
            if score_type_key is None:
                print(f"Score type '{score_name}' not found in dim_score_type.")
                continue
            if date_key is None:
                logger.warning(
                    f"Insert skipped for {ticker} {score_label}: unknown latest date_key (bad index)"
                )
                continue
            rounded = PriceReader.round2(value)
            if rounded is None:
                print(
                    f"Insert skipped for {ticker} {score_label}: value {value} cannot be stored in NUMERIC(14,2)"
                )
                continue
            technical_rows.append(
                (int(date_key), int(stock_key), int(score_type_key), float(rounded))
            )

        # Technical indicators are now computed during ingestion.
        # Scorer only writes momentum/linear-regression style scores to fact_score_history.

        # Compute blended momentum using R^2-weighted log-price slope across windows
        try:
            windows = [200, 90, 50, 30]
            pairs = []
            # Read momentum knobs from settings
            min_valid_frac = float(settings.scoring_momentum_min_valid_frac or 0.8)
            t_cap = float(settings.scoring_momentum_tstat_cap or 3.0)
            for w in windows:
                s, r2, n = MomentumCalculator.linreg_log_slope_r2(
                    df, w, min_valid_frac=min_valid_frac
                )
                if s is None or r2 is None or r2 <= 0 or n is None or n <= 2:
                    continue
                bw = float(base_weights.get(w, 1.0))
                # Compute correlation sign from slope and magnitude from r^2
                r = (float(r2) ** 0.5) * (1.0 if float(s) >= 0.0 else -1.0)
                denom = 1.0 - (r * r)
                if denom <= 0.0:
                    continue
                t = abs(r) * ((float(n) - 2.0) ** 0.5) / (denom**0.5)
                # Bound and square the t-stat factor (cap at ~3-sigma)
                t_factor = min(1.0, abs(t) / float(max(1e-9, t_cap)))
                eff_w = bw * (t_factor**2)
                pairs.append((s, eff_w))
            if pairs:
                wsum = sum(w for _, w in pairs)
                if wsum > 0:
                    combo = sum(s * w for s, w in pairs) / wsum
                    # Store using the unified as-of date_key if available
                    unified_dk = int(date_key) if date_key is not None else None
                    combined_momentum[ticker.upper()] = (unified_dk, stock_key, float(combo))
                    stage_counts["momentum_valid"] += 1
        except Exception:
            # Non-fatal
            pass

        ai_row = ai_scores.get(ticker.upper())
        if ai_row:
            ai_date_key = ai_row.get("date_key") or date_key
            for field, score_label in AI_FACTOR_SCORE_TYPES.items():
                score_value = ai_row.get(field)
                if score_value is None:
                    continue
                score_type_key = score_type_map.get(score_label.lower())
                if score_type_key is None:
                    print(f"Score type '{score_label}' not found in dim_score_type.")
                    continue
                rounded_ai_score = PriceReader.round2(score_value)
                if rounded_ai_score is None:
                    print(
                        f"Insert skipped for {ticker} {score_label}: value {score_value} cannot be stored in NUMERIC(14,2)"
                    )
                    continue
                ai_factor_rows.append(
                    (int(ai_date_key), int(stock_key), int(score_type_key), float(rounded_ai_score))
                )

            sentiment_score = ai_row.get("sentiment_score")
            if sentiment_score is not None:
                score_type_key = score_type_map.get(SENTIMENT_SCORE_TYPE.lower())
                if score_type_key is None:
                    print(f"Score type '{SENTIMENT_SCORE_TYPE}' not found in dim_score_type.")
                else:
                    rounded_sentiment = PriceReader.round2(sentiment_score)
                    if rounded_sentiment is None:
                        print(
                            f"Insert skipped for {ticker} {SENTIMENT_SCORE_TYPE}: value {sentiment_score} cannot be stored in NUMERIC(14,2)"
                        )
                        continue
                    s_date_key = ai_row.get("sentiment_date_key") or ai_date_key
                    sentiment_rows.append(
                        (
                            int(s_date_key),
                            int(stock_key),
                            int(score_type_key),
                            float(rounded_sentiment),
                        )
                    )

        # Fundamentals-based valuation score (if available for this ticker)
        f_row = fundamental_value.get(ticker.upper())
        if f_row and f_row.get("value_score") is not None:
            score_type_key = score_type_map.get(FUNDAMENTAL_VALUE_SCORE_TYPE)
            if score_type_key is None:
                print(f"Score type '{FUNDAMENTAL_VALUE_SCORE_TYPE}' not found in dim_score_type.")
            else:
                rounded_value = PriceReader.round2(f_row["value_score"])
                if rounded_value is None:
                    print(
                        f"Insert skipped for {ticker} {FUNDAMENTAL_VALUE_SCORE_TYPE}: value {f_row['value_score']} cannot be stored in NUMERIC(14,2)"
                    )
                else:
                    valuation_rows.append(
                        (
                            int(f_row.get("date_key") or date_key),
                            int(stock_key),
                            int(score_type_key),
                            float(rounded_value),
                        )
                    )
                    value_symbols.add(ticker.upper())

    momentum_invalid = max(int(stage_counts["asof_pass"]) - int(stage_counts["momentum_valid"]), 0)
    logger.info(
        "Scorer universe stages: parquet_total=%d eligible=%d unreadable=%d processed=%d asof_pass=%d asof_skip_no_latest=%d asof_skip_stale=%d missing_price=%d momentum_valid=%d momentum_invalid=%d",
        stage_counts["parquet_total"],
        stage_counts["eligible"],
        stage_counts["unreadable_parquet"],
        stage_counts["processed"],
        stage_counts["asof_pass"],
        stage_counts["asof_skip_no_latest"],
        stage_counts["asof_skip_stale"],
        stage_counts["missing_price"],
        stage_counts["momentum_valid"],
        momentum_invalid,
    )
    logger.info(
        "Momentum-valid means symbols with at least one usable weighted regression window (200/90/50/30 by config) that produced a composite momentum value."
    )
    _enforce_stage_drift_guard(stage_counts, settings=settings, logger=logger, span=span)

    inserted_counts["technicals"] += _flush_score_rows(
        repo, cursor, technical_rows, logger, "technical"
    )
    inserted_counts["ai_factors"] += _flush_score_rows(
        repo, cursor, ai_factor_rows, logger, "ai_factors"
    )
    inserted_counts["sentiment"] += _flush_score_rows(
        repo, cursor, sentiment_rows, logger, "sentiment"
    )
    inserted_counts["valuation"] += _flush_score_rows(
        repo, cursor, valuation_rows, logger, "valuation"
    )
    conn.commit()
    # Convert blended momentum into Raw and Residual (sector-neutral) 1..100 scores, then persist composite
    if combined_momentum:
        ser = pd.Series({sym: val[2] for sym, val in combined_momentum.items()}, dtype=float)
        # Load sector mapping (grouping start: Sector; robust median; fallback to market median if group small)
        try:
            map_df = pd.read_sql_query(
                "SELECT UPPER(symbol) AS symbol, sector FROM rankalpha.dim_stock WHERE is_active IS TRUE",
                engine,
            )
            sec_map = {row.symbol: row.sector for _, row in map_df.iterrows()}
            sectors = pd.Series({sym: sec_map.get(sym) for sym in ser.index})
        except Exception as exc:
            logger.warning(f"Could not load sector map; treating all as one group. Reason: {exc}")
            sectors = pd.Series({sym: None for sym in ser.index})

        df_m = pd.DataFrame({"mom": ser, "sector": sectors})
        # Raw percentile 1..100
        raw_pct = df_m["mom"].rank(pct=True, ascending=True)
        raw_score = (raw_pct * 99.0 + 1.0).clip(1.0, 100.0)

        # Residual: subtract group median if group size >= min_group_size; else subtract market median
        min_group = int(settings.scoring_momentum_min_group_size or 5)
        try:
            grp = df_m.groupby("sector", dropna=False)
            sec_median = grp["mom"].transform("median")
            sec_size = grp["mom"].transform("size")
            market_median = float(df_m["mom"].median()) if not df_m["mom"].empty else 0.0
            # Where group too small or sector missing, use market median
            effective_center = sec_median.where(sec_size >= float(min_group), other=market_median)
            resid = df_m["mom"] - effective_center
        except Exception as exc:
            logger.warning(f"Residual neutralization failed; using market-demeaned. Reason: {exc}")
            market_median = float(df_m["mom"].median()) if not df_m["mom"].empty else 0.0
            resid = df_m["mom"] - market_median

        resid_pct = resid.rank(pct=True, ascending=True)
        resid_score = (resid_pct * 99.0 + 1.0).clip(1.0, 100.0)

        # Persist Raw and Residual
        type_keys = repo.fetch_score_type_keys(cursor)
        for label, series, counter_key in (
            ("momentum raw score", raw_score, "momentum_raw"),
            ("momentum residual score", resid_score, "momentum_residual"),
        ):
            st_key = type_keys.get(label)
            if st_key is None:
                repo.ensure_score_types(cursor)
                type_keys = repo.fetch_score_type_keys(cursor)
                st_key = type_keys.get(label)
            if st_key is None:
                logger.warning(f"Score type missing; skipping inserts for {label}")
                continue
            score_rows: list[tuple[int, int, int, float]] = []
            for sym, score_val in series.items():
                dk, sk, _ = combined_momentum.get(sym, (None, None, None))
                if dk is None or sk is None or score_val is None or pd.isna(score_val):
                    continue
                rounded_score = PriceReader.round2(score_val)
                if rounded_score is None:
                    continue
                score_rows.append((int(dk), int(sk), int(st_key), float(rounded_score)))
            inserted = _flush_score_rows(repo, cursor, score_rows, logger, label)
            if inserted:
                conn.commit()
            inserted_counts[counter_key] = inserted_counts.get(counter_key, 0) + inserted

        # Persist composite 'momentum score' (70/30 blend by default)
        comp, mode, w_resid, w_raw = _blend_momentum_series(raw_score, resid_score, settings)

        st_key = type_keys.get(MOMENTUM_SCORE_TYPE)
        if st_key is None:
            repo.ensure_score_types(cursor)
            type_keys = repo.fetch_score_type_keys(cursor)
            st_key = type_keys.get(MOMENTUM_SCORE_TYPE)
        if st_key is not None:
            comp_rows: list[tuple[int, int, int, float]] = []
            comp_symbols: set[str] = set()
            for sym, score_val in comp.items():
                dk, sk, _ = combined_momentum.get(sym, (None, None, None))
                if dk is None or sk is None or score_val is None or pd.isna(score_val):
                    continue
                rounded_score = PriceReader.round2(score_val)
                if rounded_score is None:
                    continue
                comp_rows.append((int(dk), int(sk), int(st_key), float(rounded_score)))
                comp_symbols.add(sym.upper())
            inserted = _flush_score_rows(repo, cursor, comp_rows, logger, MOMENTUM_SCORE_TYPE)
            if inserted:
                conn.commit()
                momentum_symbols.update(comp_symbols)
            inserted_counts["momentum"] += inserted

        logger.info(
            "Momentum: computed blended slopes for %d symbols; inserted raw=%d residual=%d composite=%d (mode=%s, w_resid=%.2f, w_raw=%.2f)",
            len(ser),
            inserted_counts.get("momentum_raw", 0),
            inserted_counts.get("momentum_residual", 0),
            inserted_counts.get("momentum", 0),
            mode,
            w_resid,
            w_raw,
        )
    # Money flow cross-sectional score (price x volume), equities with known sector only
    if mf_components:
        mf_df = pd.DataFrame.from_dict(mf_components, orient="index")
        num_cols = ["cmf_5", "cmf_20", "vol_surp_60", "ret_20"]
        for col in num_cols:
            mf_df[col] = pd.to_numeric(mf_df[col], errors="coerce")

        # Market-cap weights (to let large caps drive the cross-sectional distribution).
        # Pull latest mktcap (<= as_of date_key) from fundamentals; units are "Millions" in the metric registry.
        mf_df["mktcap"] = np.nan
        try:
            as_of_key = int(pd.to_numeric(mf_df.get("date_key"), errors="coerce").max())
        except Exception:
            as_of_key = None
        try:
            stock_keys = (
                pd.to_numeric(mf_df.get("stock_key"), errors="coerce")
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
        except Exception:
            stock_keys = []

        if as_of_key and stock_keys:
            try:
                cursor.execute(
                    """
                    WITH metric AS (
                        SELECT metric_key
                        FROM rankalpha.dim_fin_metric
                        WHERE metric_code = 'mktcap'
                        LIMIT 1
                    ),
                    latest AS (
                        SELECT f.stock_key, MAX(f.date_key) AS date_key
                        FROM rankalpha.fact_fin_fundamentals f
                        JOIN metric m ON m.metric_key = f.metric_key
                        WHERE f.stock_key = ANY(%s)
                          AND f.date_key <= %s
                        GROUP BY f.stock_key
                    )
                    SELECT l.stock_key, f.metric_value
                    FROM latest l
                    JOIN rankalpha.fact_fin_fundamentals f
                      ON f.stock_key = l.stock_key AND f.date_key = l.date_key
                    JOIN metric m ON m.metric_key = f.metric_key
                    """,
                    (stock_keys, as_of_key),
                )
                rows = cursor.fetchall() or []
                cap_map = {
                    int(sk): float(val) for sk, val in rows if sk is not None and val is not None
                }
                mf_df["mktcap"] = pd.to_numeric(mf_df["stock_key"], errors="coerce").map(cap_map)
            except Exception as exc:
                logger.warning(
                    f"Money flow: could not load mktcap weights; falling back to unweighted z-scores. Reason: {exc}"
                )

        # Weight transform: damp mega-cap dominance while still letting large caps drive
        # mean/std and percentile thresholds.
        mktcap = pd.to_numeric(mf_df["mktcap"], errors="coerce")
        mf_df["mf_weight"] = (
            np.log1p(mktcap.clip(lower=0)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
        )

        # Weighted z-scores + weighted percentile rank
        mf_df["z_cmf_5"] = MoneyFlowCalculator.weighted_zscore(mf_df["cmf_5"], mf_df["mf_weight"])
        mf_df["z_cmf_20"] = MoneyFlowCalculator.weighted_zscore(mf_df["cmf_20"], mf_df["mf_weight"])
        mf_df["z_vol_surp"] = MoneyFlowCalculator.weighted_zscore(
            mf_df["vol_surp_60"], mf_df["mf_weight"]
        )
        mf_df["z_ret_20"] = MoneyFlowCalculator.weighted_zscore(mf_df["ret_20"], mf_df["mf_weight"])
        w_cmf20, w_cmf5, w_vol, w_ret20 = _parse_mf_weights(
            getattr(settings, "scoring_mf_component_weights", None)
        )
        # Composite money-flow signal: renormalize over available components (missing is ignored, not neutralized).
        z_weights = {
            "z_cmf_20": float(w_cmf20),
            "z_cmf_5": float(w_cmf5),
            "z_vol_surp": float(w_vol),
            "z_ret_20": float(w_ret20),
        }
        numerator = pd.Series(0.0, index=mf_df.index, dtype=float)
        denom = pd.Series(0.0, index=mf_df.index, dtype=float)
        for col, w in z_weights.items():
            if not w:
                continue
            z = pd.to_numeric(mf_df[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
            numerator = numerator + z.fillna(0.0) * w
            denom = denom + z.notna().astype(float) * w
        mf_df["mf_raw"] = numerator / denom.replace(0.0, np.nan)
        pct = MoneyFlowCalculator.weighted_rank_pct(mf_df["mf_raw"], mf_df["mf_weight"])
        mf_df["mf_score"] = (pct * 99.0 + 1.0).clip(1.0, 100.0)

        type_keys = repo.fetch_score_type_keys(cursor)
        st_key = type_keys.get("money flow score")
        if st_key is None:
            repo.ensure_score_types(cursor)
            type_keys = repo.fetch_score_type_keys(cursor)
            st_key = type_keys.get("money flow score")
        inserted_mf = 0
        if st_key is not None:
            mf_rows: list[tuple[int, int, int, float]] = []
            for sym, row in mf_df.iterrows():
                dk = row.get("date_key")
                sk = row.get("stock_key")
                val = row.get("mf_score")
                if dk is None or sk is None or val is None or pd.isna(val):
                    continue
                rounded = PriceReader.round2(val)
                if rounded is None:
                    continue
                mf_rows.append((int(dk), int(sk), int(st_key), float(rounded)))
            inserted_mf = _flush_score_rows(repo, cursor, mf_rows, logger, "money_flow")
            if inserted_mf:
                conn.commit()
        inserted_counts["money_flow"] = inserted_mf
        logger.info(
            "Money flow: candidates=%d, scored=%d, inserted=%d, weights=(cmf20=%.2f, cmf5=%.2f, vol=%.2f, ret20=%.2f)",
            mf_stats.get("candidates", 0),
            mf_df["mf_score"].notna().sum(),
            inserted_mf,
            w_cmf20,
            w_cmf5,
            w_vol,
            w_ret20,
        )
    else:
        logger.info(
            "Money flow: skipped (candidates=%d, attempted=%d, added=%d, miss_cmf20=%d, miss_vol=%d, no_price=%d)",
            mf_stats.get("candidates", 0),
            mf_stats.get("attempted", 0),
            mf_stats.get("added", 0),
            mf_stats.get("miss_cmf20", 0),
            mf_stats.get("miss_vol", 0),
            mf_stats.get("no_price", 0),
        )

    logger.info(
        "Insert summary: technicals=%d ai_factors=%d sentiment=%d valuation=%d momentum=%d money_flow=%d",
        inserted_counts["technicals"],
        inserted_counts["ai_factors"],
        inserted_counts["sentiment"],
        inserted_counts["valuation"],
        inserted_counts["momentum"],
        inserted_counts["money_flow"],
    )
    # Insert fundamentals-based valuation for any remaining symbols not covered by price loop
    try:
        value_type_key = repo.fetch_score_type_keys(cursor).get(FUNDAMENTAL_VALUE_SCORE_TYPE)
        if value_type_key is None:
            # refresh mapping if needed
            repo.ensure_score_types(cursor)
            value_type_key = repo.fetch_score_type_keys(cursor).get(FUNDAMENTAL_VALUE_SCORE_TYPE)
        if value_type_key is not None:
            extra_value_rows: list[tuple[int, int, int, float]] = []
            for sym, row in fundamental_value.items():
                if sym in processed_tickers:
                    continue
                vs = row.get("value_score")
                if vs is None:
                    continue
                stock_key = repo.fetch_stock_key(cursor, sym)
                if stock_key is None:
                    continue
                date_key = row.get("date_key")
                rounded_value = PriceReader.round2(vs)
                if date_key is None or rounded_value is None:
                    continue
                extra_value_rows.append(
                    (
                        int(date_key),
                        int(stock_key),
                        int(value_type_key),
                        float(rounded_value),
                    )
                )
            _flush_score_rows(repo, cursor, extra_value_rows, logger, "valuation_nonpriced")
            conn.commit()
    except Exception:
        # Non-fatal; valuation inserts for non-priced symbols best-effort
        pass
    cursor.close()
    conn.close()
    logger.info("Scoring completed; capturing screener change events ...")
    repo.capture_screener_changes()
    logger.info("Updating screener presence streaks and refreshing scores MV ...")
    repo.update_screener_presence()
    logger.info("Screener change capture done; refreshing materialized views ...")
    repo.refresh_materialized_views()
    logger.info("Materialized views refresh done")

    # Post-refresh tail jobs run in parallel (each opens its own DB connection)
    def _ms_int(val, default):
        return default if val is None else int(val)

    def _ms_float(val, default):
        return default if val is None else float(val)

    ms_kwargs = {
        "lookback_days": _ms_int(settings.scoring_market_structure_lookback_days, 320),
        "trend_window": _ms_int(settings.scoring_market_structure_trend_window, 50),
        "rv_window": _ms_int(settings.scoring_market_structure_rv_window, 20),
        "corr_window": _ms_int(settings.scoring_market_structure_corr_window, 20),
        "z_window": _ms_int(settings.scoring_market_structure_z_window, 252),
        "trend_up_z": _ms_float(settings.scoring_market_structure_trend_up_z, 0.5),
        "trend_down_z": _ms_float(settings.scoring_market_structure_trend_down_z, -0.5),
        "vol_threshold": _ms_float(settings.scoring_market_structure_vol_threshold, 0.0),
        "corr_threshold": _ms_float(settings.scoring_market_structure_corr_threshold, 0.0),
        "disp_threshold": _ms_float(settings.scoring_market_structure_disp_threshold, 0.0),
    }

    def job_regime_series():
        logger.info("Computing US regime series for latest day ...")
        repo.update_regime_series_us()
        logger.info("Regime series update done")

    def job_regime_rules():
        logger.info("Computing flow-based regime rules for latest day ...")
        repo.update_regime_rules_us()
        logger.info("Regime rules update done")

    def job_market_structure():
        logger.info("Computing Market Structure regime components (CVD-style) ...")
        repo.update_market_structure_us(**ms_kwargs)
        logger.info("Market Structure update done")

    def job_rank_regime():
        logger.info("Refreshing rank-based Momentum↔Value regime MV ...")
        repo.refresh_rank_regime_daily()
        logger.info("Rank regime MV refresh done")

    def job_vix_term_structure():
        if not VixTermStructureService:
            logger.warning("VIX term structure service unavailable; import failed")
            return
        logger.info("Computing VIX term structure and regime ...")
        vix_service = VixTermStructureService(dsn, logger, settings)
        updated_rows = vix_service.run()
        logger.info("VIX term structure update done (rows=%s)", updated_rows)

    def job_vrp():
        if not VolRiskPremiumService:
            logger.warning("VRP service unavailable; import failed")
            return
        logger.info("Computing SPX/VIX variance risk premium and regime ...")
        vrp_service = VolRiskPremiumService(dsn, logger, settings)
        updated_rows = vrp_service.run()
        logger.info("VRP update done (rows=%s)", updated_rows)

    tail_jobs = [
        ("regime_series", job_regime_series),
        ("regime_rules", job_regime_rules),
        ("market_structure", job_market_structure),
        ("rank_regime", job_rank_regime),
        ("vix_term_structure", job_vix_term_structure),
        ("vrp", job_vrp),
    ]

    max_workers = min(4, len(tail_jobs))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futs = {executor.submit(fn): name for name, fn in tail_jobs}
        for fut in as_completed(futs):
            name = futs[fut]
            try:
                fut.result()
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning("Tail job %s raised: %s", name, exc, exc_info=True)
    try:
        span.add_event(
            "scorer.insert_summary",
            {
                "technicals": inserted_counts["technicals"],
                "ai_factors": inserted_counts["ai_factors"],
                "sentiment": inserted_counts["sentiment"],
                "valuation": inserted_counts["valuation"],
                "momentum": inserted_counts["momentum"],
                "money_flow": inserted_counts.get("money_flow", 0),
            },
        )
    except Exception:
        pass

    # Data-quality: required scores (Momentum + Value) should be present for most of the *primary* eligible universe.
    #
    # Important: do not rely on in-run insertion sets for this check. Value scores are often sourced from fundamentals
    # (or AI fallbacks) and may not be inserted in the same code path as momentum; using in-run sets can produce
    # false 100% missing alerts even when DB coverage is healthy.
    coverage_source = "local"
    primary_asset_type = None
    if active_symbols:
        try:
            primary_asset_type = _select_primary_eligible_asset_type(engine, logger)
            total_symbols, missing_count, missing_required = _fetch_required_score_coverage(
                engine, primary_asset_type=primary_asset_type
            )
            ok_count = max(total_symbols - missing_count, 0)
            coverage_ratio = float(ok_count) / float(max(total_symbols, 1))
            missing_ratio = float(missing_count) / float(max(total_symbols, 1))
            coverage_source = "db"
        except Exception as exc:
            # Never fail the scorer run due to a data-quality metric query.
            logger.warning(
                "Required-score coverage query failed; falling back to local bookkeeping: %s",
                exc,
            )
            coverage_source = "local_fallback"

    if coverage_source != "db":
        # Best-effort fallback (no paging): use local bookkeeping.
        universe_symbols = (
            set(active_symbols)
            if active_symbols
            else {os.path.splitext(os.path.basename(f))[0].upper() for f in parquet_files or []}
        )
        total_symbols = len(universe_symbols)
        required_ok = momentum_symbols.intersection(value_symbols)
        missing_required = sorted(list(universe_symbols - required_ok))
        missing_count = len(missing_required)
        coverage_ratio = float(len(required_ok)) / float(max(total_symbols, 1))
        missing_ratio = float(missing_count) / float(max(total_symbols, 1))
    try:
        SCORER_REQUIRED_COVERAGE_RATIO.set(coverage_ratio)
        SCORER_REQUIRED_MISSING_RATIO.set(missing_ratio)
        SCORER_REQUIRED_MISSING_SYMBOLS.set(missing_count)
    except Exception:
        pass
    try:
        span.set_attribute("scorer.required.coverage_ratio", coverage_ratio)
        span.set_attribute("scorer.required.missing_ratio", missing_ratio)
        span.set_attribute("scorer.required.missing_symbols", missing_count)
        span.set_attribute("scorer.required.coverage_source", coverage_source)
        if primary_asset_type:
            span.set_attribute("scorer.required.primary_asset_type", primary_asset_type)
    except Exception:
        pass
    try:
        threshold = float(settings.scoring_missing_required_ratio_alert_threshold or 0.05)
    except Exception:
        threshold = 0.05
    # Only page from Sentry when we successfully loaded the active universe from DB
    # AND computed coverage from DB (avoids false positives from local bookkeeping).
    if active_symbols and coverage_source == "db":
        report_ratio_threshold(
            service="rankalpha-scorer",
            check="missing_required_scores",
            ratio=missing_ratio,
            threshold=threshold,
            total=total_symbols,
            affected=missing_count,
            sample=missing_required[:25] if missing_required else None,
            level="error",
        )

    repo.dispose()


def main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)
    init_service_observability("rankalpha-scorer")
    for run_status in ("success", "error"):
        SCORER_DURATION.labels(status=run_status)
        SCORER_RUNS.labels(status=run_status)
    status = "success"
    start_time = time.perf_counter()
    with start_span("scorer.run") as span:
        try:
            _execute_scorer(span, settings)
        except Exception as exc:
            status = "error"
            try:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
            except Exception:
                pass
            raise
        finally:
            duration = time.perf_counter() - start_time
            try:
                span.set_attribute("scorer.duration_seconds", duration)
                span.set_attribute("scorer.status", status)
            except Exception:
                pass
            SCORER_DURATION.labels(status=status).observe(duration)
            SCORER_RUNS.labels(status=status).inc()
            sleep_for_metrics_flush("rankalpha-scorer")


if __name__ == "__main__":
    main()
