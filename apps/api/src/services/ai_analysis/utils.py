from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import case, desc, func, literal, or_, select
from sqlalchemy.orm import Session

from apps.api.src.utils.coerce import coerce_float, coerce_int
from apps.common.src.models import (
    DimDate,
    DimStock,
    FactAiPriceScenario,
    FactSecurityPrice,
    MvAiAnalysisLatestList,
    MvAiScenarioProximity,
    VwAiAnalysisFull,
    VwAiAnalysisLatest,
    VwAiScenarioProximity,
)


def preview_map_for_symbols(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Return lightweight AI preview data for the latest analysis per symbol.

    Output shape:
      { "AAPL": { "events_count": 3, "base_price_target": 210.0, "has_thesis": True }, ... }
    """
    norm = [(s or "").strip().upper() for s in (symbols or []) if isinstance(s, str)]
    uniq = list(dict.fromkeys([s for s in norm if s]))
    if not uniq:
        return {}

    events_count_expr = case(
        (VwAiAnalysisLatest.events.is_(None), literal(0)),
        (
            func.jsonb_typeof(VwAiAnalysisLatest.events) == literal("array"),
            func.jsonb_array_length(VwAiAnalysisLatest.events),
        ),
        else_=literal(1),
    ).label("events_count")

    def _has_text(col: Any) -> Any:
        return func.nullif(func.trim(col), literal("")).isnot(None)

    has_thesis_expr = case(
        (
            or_(
                _has_text(VwAiAnalysisLatest.analyst_bull_case),
                _has_text(VwAiAnalysisLatest.analyst_bear_case),
                _has_text(VwAiAnalysisLatest.analyst_valuation_check),
            ),
            literal(True),
        ),
        else_=literal(False),
    ).label("has_thesis")

    q = select(
        VwAiAnalysisLatest.symbol,
        VwAiAnalysisLatest.base_price_target,
        events_count_expr,
        has_thesis_expr,
    ).where(VwAiAnalysisLatest.symbol.in_(uniq))

    out: dict[str, dict[str, Any]] = {}
    for sym, bpt, events_count, has_thesis in db.execute(q).all():
        out[str(sym)] = {
            "events_count": int(events_count) if events_count is not None else None,
            "base_price_target": float(bpt) if bpt is not None else None,
            "has_thesis": bool(has_thesis),
        }
    return out


def _coerce_json_array(value: Any) -> list[dict[str, Any]] | None:
    """Coerce a DB/API JSON field into a JSON array (list of dicts) or None."""
    if value is None:
        return None
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, str):
        s = value.strip()
        if not s or s in ("[]", "{}"):
            return []
        try:
            parsed = json.loads(s)
        except Exception:
            return None
        if isinstance(parsed, list):
            return [v for v in parsed if isinstance(v, dict)]
        return None
    return None


def _extract_usd_amounts_from_text(text: Any) -> list[float]:
    try:
        t = str(text or "")
    except Exception:
        return []
    if not t:
        return []
    # Prefer explicit currency markers to avoid accidentally capturing things like "5 years" or "10 analysts".
    currency_matches = []
    currency_matches.extend(re.findall(r"(?i)\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d+)?)", t))
    currency_matches.extend(re.findall(r"(?i)(\d{1,4}(?:,\d{3})*(?:\.\d+)?)\s*usd", t))
    matches = currency_matches
    out: list[float] = []
    for m in matches:
        try:
            v = float(str(m).replace(",", ""))
            if v <= 1.0 or v >= 200_000.0:
                continue
            out.append(v)
        except Exception:
            continue
    # De-dupe while preserving order
    deduped: list[float] = []
    seen: set[str] = set()
    for v in out:
        k = f"{v:.6f}"
        if k in seen:
            continue
        seen.add(k)
        deduped.append(v)
    return deduped[:24]


def _fallback_human_analyst_targets_summary(
    organic: Any, *, reference_price: Optional[float]
) -> dict[str, Any] | None:
    if isinstance(organic, str):
        try:
            organic = json.loads(organic)
        except Exception:
            organic = None
    if not isinstance(organic, list) or not organic:
        return None
    amounts: list[float] = []
    for item in organic:
        if not isinstance(item, dict):
            continue
        vals = item.get("amounts_usd")
        if isinstance(vals, list) and vals:
            for v in vals:
                try:
                    amounts.append(float(v))
                except Exception:
                    continue
            continue
        amounts.extend(_extract_usd_amounts_from_text(item.get("snippet")))
        amounts.extend(_extract_usd_amounts_from_text(item.get("title")))
    if not amounts:
        return None

    try:
        ref = float(reference_price) if reference_price is not None else None
        if ref is not None and not (ref > 0):
            ref = None
    except Exception:
        ref = None

    if ref is not None:
        lo = ref * 0.25
        hi = ref * 4.0
        filtered = [v for v in amounts if v >= lo and v <= hi]
        amounts = filtered if filtered else amounts
    if not amounts:
        return None

    uniq = sorted({round(v, 6) for v in amounts})
    n = len(uniq)
    if n <= 0:
        return None
    low = float(uniq[0])
    high = float(uniq[-1])
    median = float(uniq[n // 2]) if (n % 2 == 1) else float((uniq[n // 2 - 1] + uniq[n // 2]) / 2.0)
    mean = float(sum(uniq) / n)
    return {
        "human_analyst_target_count": n,
        "human_analyst_target_low_usd": low,
        "human_analyst_target_high_usd": high,
        "human_analyst_target_median_usd": median,
        "human_analyst_target_mean_usd": mean,
    }


def row_to_dict(row: VwAiAnalysisFull | VwAiAnalysisLatest) -> Dict[str, Any]:
    """Convert AI analysis ORM row into a JSON-serializable dict."""
    out: Dict[str, Any] = {
        "analysis_id": getattr(row, "analysis_id", None),
        "as_of_date": getattr(row, "as_of_date", None),
        "symbol": getattr(row, "symbol", None),
        "company_name": getattr(row, "company_name", None),
        "asset_type": getattr(row, "asset_type", None),
        "source_name": getattr(row, "source_name", None),
        "market_cap_usd": coerce_float(getattr(row, "market_cap_usd", None)),
        "revenue_cagr_3y_pct": coerce_float(getattr(row, "revenue_cagr_3y_pct", None)),
        "gross_margin_trend": getattr(row, "gross_margin_trend", None),
        "net_margin_trend": getattr(row, "net_margin_trend", None),
        "free_cash_flow_trend": getattr(row, "free_cash_flow_trend", None),
        "insider_activity": getattr(row, "insider_activity", None),
        "beta_sp500": coerce_float(getattr(row, "beta_sp500", None)),
        "rate_sensitivity_bps": coerce_float(getattr(row, "rate_sensitivity_bps", None)),
        "fx_sensitivity": getattr(row, "fx_sensitivity", None),
        "commodity_exposure": getattr(row, "commodity_exposure", None),
        "news_sentiment_30d": coerce_float(getattr(row, "news_sentiment_30d", None)),
        "social_sentiment_7d": coerce_float(getattr(row, "social_sentiment_7d", None)),
        "options_skew_30d": coerce_float(getattr(row, "options_skew_30d", None)),
        "short_interest_pct_float": coerce_float(getattr(row, "short_interest_pct_float", None)),
        "employee_glassdoor_score": coerce_float(getattr(row, "employee_glassdoor_score", None)),
        "headline_buzz_score": getattr(row, "headline_buzz_score", None),
        "commentary": getattr(row, "commentary", None),
        "overall_rating": getattr(row, "overall_rating", None),
        "confidence": getattr(row, "confidence", None),
        "recommendation_timeframe": getattr(row, "recommendation_timeframe", None),
        "pe_forward": coerce_float(getattr(row, "pe_forward", None)),
        "ev_ebitda_forward": coerce_float(getattr(row, "ev_ebitda_forward", None)),
        "pe_percentile_in_sector": coerce_float(getattr(row, "pe_percentile_in_sector", None)),
        "value_score": coerce_float(getattr(row, "value_score", None)),
        "quality_score": coerce_float(getattr(row, "quality_score", None)),
        "momentum_score": coerce_float(getattr(row, "momentum_score", None)),
        "low_vol_score": coerce_float(getattr(row, "low_vol_score", None)),
        "bull_price_target": coerce_float(getattr(row, "bull_price_target", None)),
        "bull_probability_pct": coerce_float(getattr(row, "bull_probability_pct", None)),
        "base_price_target": coerce_float(getattr(row, "base_price_target", None)),
        "base_probability_pct": coerce_float(getattr(row, "base_probability_pct", None)),
        "bear_price_target": coerce_float(getattr(row, "bear_price_target", None)),
        "bear_probability_pct": coerce_float(getattr(row, "bear_probability_pct", None)),
        "short_catalysts": getattr(row, "short_catalysts", None),
        "long_catalysts": getattr(row, "long_catalysts", None),
        "events": getattr(row, "events", None),
        "macro_risks": getattr(row, "macro_risks", None),
        "headline_risks": getattr(row, "headline_risks", None),
        "data_gaps": getattr(row, "data_gaps", None),
        "peers": getattr(row, "peers", None),
        "human_analyst_targets_provider": getattr(row, "human_analyst_targets_provider", None),
        "human_analyst_targets_query": getattr(row, "human_analyst_targets_query", None),
        "human_analyst_targets_organic": _coerce_json_array(
            getattr(row, "human_analyst_targets_organic", None)
        ),
        "human_analyst_target_low_usd": coerce_float(
            getattr(row, "human_analyst_target_low_usd", None)
        ),
        "human_analyst_target_high_usd": coerce_float(
            getattr(row, "human_analyst_target_high_usd", None)
        ),
        "human_analyst_target_median_usd": coerce_float(
            getattr(row, "human_analyst_target_median_usd", None)
        ),
        "human_analyst_target_mean_usd": coerce_float(
            getattr(row, "human_analyst_target_mean_usd", None)
        ),
        "human_analyst_target_count": coerce_int(getattr(row, "human_analyst_target_count", None)),
    }

    # If DB summary columns are missing but we have organic results, compute a best-effort summary.
    try:
        if out.get("human_analyst_target_count") is None and out.get(
            "human_analyst_targets_organic"
        ):
            ref = coerce_float(getattr(row, "base_price_target", None))
            derived = _fallback_human_analyst_targets_summary(
                out.get("human_analyst_targets_organic"), reference_price=ref
            )
            if isinstance(derived, dict):
                out.update(derived)
    except Exception:
        pass

    # Attach analyst summary fields if present
    bull = getattr(row, "analyst_bull_case", None)
    bear = getattr(row, "analyst_bear_case", None)
    valuation = getattr(row, "analyst_valuation_check", None)
    if bull or bear or valuation:
        out["analyst_summary"] = {
            "bull_case": bull,
            "bear_case": bear,
            "valuation_check": valuation,
        }

    # Allow commentary JSON to surface structured data
    commentary = getattr(row, "commentary", None)
    if isinstance(commentary, str):
        try:
            parsed = json.loads(commentary)
            if isinstance(parsed, dict):
                if "analyst_summary" in parsed and "analyst_summary" not in out:
                    out["analyst_summary"] = parsed.get("analyst_summary")
                sc = parsed.get("sentiment_commentary")
                if isinstance(sc, str) and sc:
                    out["commentary"] = sc
        except Exception:
            pass

    return out


def list_row_to_dict(row: MvAiAnalysisLatestList) -> Dict[str, Any]:
    return {
        "analysis_id": row.analysis_id,
        "as_of_date": getattr(row, "as_of_date", None),
        "symbol": getattr(row, "symbol", None),
        "company_name": getattr(row, "company_name", None),
        "asset_type": getattr(row, "asset_type", None),
        "overall_rating": getattr(row, "overall_rating", None),
        "confidence": getattr(row, "confidence", None),
        "commentary": getattr(row, "commentary", None),
        "bull_price_target": coerce_float(getattr(row, "bull_price_target", None)),
        "bull_probability_pct": coerce_float(getattr(row, "bull_probability_pct", None)),
        "base_price_target": coerce_float(getattr(row, "base_price_target", None)),
        "base_probability_pct": coerce_float(getattr(row, "base_probability_pct", None)),
        "bear_price_target": coerce_float(getattr(row, "bear_price_target", None)),
        "bear_probability_pct": coerce_float(getattr(row, "bear_probability_pct", None)),
        "price_close": coerce_float(getattr(row, "close_px", None)),
        "price_date": getattr(row, "price_date", None),
        "delta_bull_pct": coerce_float(getattr(row, "delta_bull_pct", None)),
        "delta_base_pct": coerce_float(getattr(row, "delta_base_pct", None)),
        "delta_bear_pct": coerce_float(getattr(row, "delta_bear_pct", None)),
        "nearest_scenario": getattr(row, "nearest_scenario", None),
        "nearest_distance_pct": coerce_float(getattr(row, "nearest_distance_pct", None)),
    }


def compute_proximity_for_analysis(
    db: Session, analysis_id: UUID, symbol: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Compute proximity data for a specific analysis using latest close."""
    if not symbol:
        return None
    sym = str(symbol).upper()

    px_row = db.execute(
        select(FactSecurityPrice.close_px, DimDate.full_date)
        .join(DimStock, DimStock.stock_key == FactSecurityPrice.stock_key)
        .join(DimDate, DimDate.date_key == FactSecurityPrice.date_key)
        .where(DimStock.symbol == sym)
        .order_by(desc(FactSecurityPrice.date_key))
        .limit(1)
    ).first()
    if not px_row:
        return None
    close_px, price_date = px_row
    close_val = coerce_float(close_px)
    if not close_val or close_val <= 0:
        return None

    # Prefer precomputed proximity when available
    prox_row = db.execute(
        select(VwAiScenarioProximity)
        .where(VwAiScenarioProximity.analysis_id == analysis_id)
        .limit(1)
    ).scalar_one_or_none()
    if prox_row is not None:
        return {
            "price_close": close_val,
            "price_date": price_date,
            "delta_bull_pct": coerce_float(getattr(prox_row, "delta_bull_pct", None)),
            "delta_base_pct": coerce_float(getattr(prox_row, "delta_base_pct", None)),
            "delta_bear_pct": coerce_float(getattr(prox_row, "delta_bear_pct", None)),
            "nearest_scenario": getattr(prox_row, "nearest_scenario", None),
            "nearest_distance_pct": coerce_float(getattr(prox_row, "nearest_distance_pct", None)),
        }

    target_rows = db.execute(
        select(
            FactAiPriceScenario.scenario_type,
            FactAiPriceScenario.price_target,
            FactAiPriceScenario.probability_pct,
        ).where(FactAiPriceScenario.analysis_id == analysis_id)
    ).all()
    targets: Dict[str, Dict[str, Optional[float]]] = {}
    for scenario_type, price, probability in target_rows:
        targets[str(scenario_type)] = {
            "price": coerce_float(price),
            "prob": coerce_float(probability),
        }

    def delta(target_price: Optional[float]) -> Optional[float]:
        return ((target_price / close_val) - 1.0) * 100.0 if (target_price and close_val) else None

    bull_delta = delta(targets.get("bull", {}).get("price"))
    base_delta = delta(targets.get("base", {}).get("price"))
    bear_delta = delta(targets.get("bear", {}).get("price"))

    choices = []
    if bull_delta is not None:
        choices.append(("bull", abs(bull_delta), targets.get("bull", {}).get("prob") or 0.0))
    if base_delta is not None:
        choices.append(("base", abs(base_delta), targets.get("base", {}).get("prob") or 0.0))
    if bear_delta is not None:
        choices.append(("bear", abs(bear_delta), targets.get("bear", {}).get("prob") or 0.0))

    if choices:
        priority = {"base": 0, "bull": 1, "bear": 2}
        choices.sort(key=lambda item: (item[1], -item[2], priority.get(item[0], 9)))
        nearest, nearest_abs, _ = choices[0]
    else:
        nearest = None
        nearest_abs = None

    return {
        "price_close": close_val,
        "price_date": price_date,
        "delta_bull_pct": bull_delta,
        "delta_base_pct": base_delta,
        "delta_bear_pct": bear_delta,
        "nearest_scenario": nearest,
        "nearest_distance_pct": nearest_abs,
    }


def load_precomputed_proximity(db: Session, analysis_ids: list[UUID]) -> Dict[str, Any]:
    """Load proximity rows from the materialized view when available."""
    if not analysis_ids:
        return {}
    try:
        rows = (
            db.execute(
                select(MvAiScenarioProximity).where(
                    MvAiScenarioProximity.analysis_id.in_(analysis_ids)
                )
            )
            .scalars()
            .all()
        )
    except Exception:
        rows = (
            db.execute(
                select(VwAiScenarioProximity).where(
                    VwAiScenarioProximity.analysis_id.in_(analysis_ids)
                )
            )
            .scalars()
            .all()
        )
    result: Dict[str, Any] = {}
    for r in rows:
        aid = str(getattr(r, "analysis_id", None))
        result[aid] = {
            "price_close": coerce_float(getattr(r, "close_px", None)),
            "price_date": getattr(r, "price_date", None),
            "delta_bull_pct": coerce_float(getattr(r, "delta_bull_pct", None)),
            "delta_base_pct": coerce_float(getattr(r, "delta_base_pct", None)),
            "delta_bear_pct": coerce_float(getattr(r, "delta_bear_pct", None)),
            "nearest_scenario": getattr(r, "nearest_scenario", None),
            "nearest_distance_pct": coerce_float(getattr(r, "nearest_distance_pct", None)),
        }
    return result
