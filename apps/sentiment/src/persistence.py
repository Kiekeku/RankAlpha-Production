from __future__ import annotations

import contextlib
import json
import os
import re
from typing import Any

import psycopg2
import requests  # type: ignore[import-untyped]
from psycopg2.extras import Json, execute_values

from apps.common.src.logging import get_logger
from apps.sentiment.src.settings import Settings as Settings

SENTIMENT_SOURCE_NAME = "RankAlpha Sentiment AI"
_TABLE_EXISTENCE_CACHE: dict[str, bool] = {}
_DIM_KEY_CACHE: dict[str, dict[str, int]] = {}


def _normalize_dim_label(value: str) -> str:
    """Normalize human/LLM labels to match dim_* labels.

    - lowercases
    - trims whitespace
    - replaces unicode dashes with ASCII '-'
    - collapses spaces/underscores to a single underscore for style/rating inputs
    """
    s = (value or "").strip().lower()
    if not s:
        return ""
    # Normalize common unicode dash variants to ASCII '-'
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        s = s.replace(dash, "-")
    # Normalize whitespace
    s = " ".join(s.split())
    return s


def _normalize_keyish(value: str) -> str:
    """Normalize labels that are effectively enum keys (rating/style)."""
    s = _normalize_dim_label(value)
    # 'Strong Buy' -> 'strong_buy', 'low vol' -> 'low_vol'
    s = s.replace(" ", "_")
    s = s.replace("-", "_")
    return s


def _normalize_catalyst_type(value: Any) -> str:
    """Normalize catalyst_type into short|long|event for storage."""
    if not value:
        return "short"
    s = str(value).strip().lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        s = s.replace(dash, "-")
    s = s.replace("_", " ").replace("-", " ")
    s = " ".join(s.split())
    if "short" in s:
        return "short"
    if "long" in s:
        return "long"
    if "event" in s:
        return "event"
    return "event"


def _load_dim_map(cursor, *, cache_key: str, sql: str) -> dict[str, int]:
    cached = _DIM_KEY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    cursor.execute(sql)
    rows = cursor.fetchall() or []
    out: dict[str, int] = {}
    for k, label in rows:
        if label is None:
            continue
        out[_normalize_dim_label(str(label))] = int(k)
    _DIM_KEY_CACHE[cache_key] = out
    return out


def _coerce_level_label(conf_val: Any) -> str | None:
    """Return 'low'|'medium'|'high' for strings/numerics; else None.

    Accepts:
    - Labels: 'low'|'medium'|'high' (case-insensitive)
    - Dim-like keys: 1/2/3 (or "1"/"2"/"3") interpreted as low/medium/high
    - Numerics: <=1.0 treated as proportion, else as percent in 0–100
    """
    if conf_val is None:
        return None
    if isinstance(conf_val, str):
        s = _normalize_dim_label(conf_val)
        if s in {"low", "medium", "high"}:
            return s
        if s in {"1", "2", "3"}:
            return {"1": "low", "2": "medium", "3": "high"}[s]
        try:
            num = float(s)
        except Exception:
            return None
        if num <= 1.0:
            num *= 100.0
    else:
        try:
            num = float(conf_val)
        except Exception:
            return None
        # If an integer-ish 1/2/3, treat as low/medium/high (common enum encoding).
        try:
            if float(num).is_integer():
                as_int = int(num)
                if as_int in (1, 2, 3):
                    return {1: "low", 2: "medium", 3: "high"}[as_int]
        except Exception:
            pass
        if num <= 1.0:
            num *= 100.0
    if num <= 40.0:
        return "low"
    if num <= 70.0:
        return "medium"
    return "high"


class DimKeyResolver:
    """Resolves dim_* keys by label to avoid brittle hard-coded IDs."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def trend_key(self, trend_label: str | None) -> int | None:
        if not trend_label:
            return None
        m = _load_dim_map(
            self._cursor,
            cache_key="trend",
            sql="SELECT trend_key, trend_label FROM rankalpha.dim_trend_category",
        )
        return m.get(_normalize_dim_label(trend_label))

    def rating_key(self, rating_label: str | None) -> int | None:
        if not rating_label:
            return None
        normalized = _normalize_keyish(rating_label)
        m = _load_dim_map(
            self._cursor,
            cache_key="rating",
            sql="SELECT rating_key, rating_label FROM rankalpha.dim_rating",
        )
        return m.get(_normalize_dim_label(normalized))

    def confidence_key(self, confidence: Any) -> int | None:
        label = _coerce_level_label(confidence)
        if not label:
            return None
        m = _load_dim_map(
            self._cursor,
            cache_key="confidence",
            sql="SELECT confidence_key, confidence_label FROM rankalpha.dim_confidence",
        )
        return m.get(_normalize_dim_label(label))

    def timeframe_key(self, timeframe_label: Any) -> int | None:
        if not timeframe_label:
            return None
        if not isinstance(timeframe_label, str):
            return None
        raw = _normalize_dim_label(timeframe_label)
        # Normalize variants like "6–12m", "6‑12m", "6-12m", "6 to 12m"
        raw = raw.replace("months", "m").replace("month", "m")
        raw = raw.replace("to", "-")
        raw = raw.replace(" ", "")
        # DB uses labels like '6‑12m' (unicode dash) - our normalize maps it to '-'
        if raw in {"3m", "6-12m", "12-24m"}:
            normalized = raw
        else:
            normalized = raw
        m = _load_dim_map(
            self._cursor,
            cache_key="timeframe",
            sql="SELECT timeframe_key, timeframe_label FROM rankalpha.dim_timeframe",
        )
        # Compare normalized versions of DB labels as well
        return m.get(_normalize_dim_label(normalized))

    def style_key(self, style_name: str | None) -> int | None:
        if not style_name:
            return None
        normalized = _normalize_keyish(style_name)
        m = _load_dim_map(
            self._cursor,
            cache_key="style",
            sql="SELECT style_key, style_name FROM rankalpha.dim_style",
        )
        return m.get(_normalize_dim_label(normalized))


def table_exists(cursor, qualified_name: str) -> bool:
    """Check if a fully qualified table exists (cached per process)."""

    if qualified_name in _TABLE_EXISTENCE_CACHE:
        return _TABLE_EXISTENCE_CACHE[qualified_name]
    cursor.execute("SELECT to_regclass(%s)", (qualified_name,))
    row = cursor.fetchone()
    exists = bool(row and row[0])
    _TABLE_EXISTENCE_CACHE[qualified_name] = exists
    return exists


def extract_json_block(text: str) -> str:
    match1 = re.search(r"'''json\s*(\{.*?\})\s*'''", text, re.DOTALL)
    match2 = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match1:
        return match1.group(1)
    if match2:
        return match2.group(1)
    raise ValueError("JSON block not found in report")


def get_stock_key(cursor, ticker: str):
    cursor.execute(
        "SELECT stock_key FROM rankalpha.dim_stock WHERE symbol = %s AND is_active IS TRUE",
        (ticker,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_or_create_source_key(
    cursor,
    source_name: str = SENTIMENT_SOURCE_NAME,
    version: str = "1",
) -> int:
    """Ensure a dim_source entry exists and return its key.

    Uses rankalpha.dim_source explicitly to avoid reliance on search_path.
    """
    try:
        cursor.execute(
            "INSERT INTO rankalpha.dim_source (source_name, version) VALUES (%s, %s) "
            "ON CONFLICT (source_name) DO NOTHING",
            (source_name, version),
        )
    except Exception:
        # Ignore conflicts or transient errors; we will select next
        pass
    cursor.execute(
        "SELECT source_key FROM rankalpha.dim_source WHERE source_name = %s",
        (source_name,),
    )
    row = cursor.fetchone()
    if not row:
        raise RuntimeError(f"Failed to obtain source_key for source '{source_name}'")
    return int(row[0])


def _notify_ai_cache_refresh(
    symbol: str | None,
    analysis_id: str | None,
    settings: Settings,
) -> None:
    url = getattr(settings, "ai_analysis_cache_url", None) or os.getenv("AI_ANALYSIS_CACHE_URL")
    token = getattr(settings, "ai_analysis_cache_token", None) or os.getenv(
        "AI_ANALYSIS_CACHE_TOKEN"
    )
    if not url or not token:
        return
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    timeout = getattr(settings, "ai_analysis_cache_timeout_seconds", None)
    try:
        timeout = float(timeout) if timeout is not None else 15.0
    except Exception:
        timeout = 15.0
    payload: dict[str, object] = {
        "symbols": [symbol.upper()] if symbol else [],
        "analysis_ids": [str(analysis_id)] if analysis_id else [],
        "include_proximity": True,
        "reason": "sentiment",
    }
    chunk_size = getattr(settings, "ai_analysis_cache_refresh_chunk_size", None) or os.getenv(
        "AI_ANALYSIS_CACHE_REFRESH_CHUNK_SIZE"
    )
    if chunk_size:
        try:
            payload["chunk_size"] = int(chunk_size)
        except Exception:
            pass
    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            get_logger(__name__).warning(
                "AI cache refresh request failed for %s: HTTP %s %s",
                symbol,
                response.status_code,
                response.text[:2000],
            )
    except Exception as exc:
        get_logger(__name__).warning("AI cache refresh request failed for %s: %s", symbol, exc)


def load_json_and_insert(report_path: str, *, extra: dict[str, Any] | None = None) -> None:
    # Read and parse
    settings = Settings()
    logger = get_logger(__name__)
    logger.info(f"Loading report JSON into database from {report_path}")
    with open(report_path, "r", encoding="utf-8") as file_obj:
        raw = file_obj.read()
    try:
        json_str = extract_json_block(raw)
    except Exception:
        # Support files that contain raw JSON without code fences
        json_str = raw.strip()
    data = json.loads(json_str)
    try:
        logger.info(
            "Parsed report: ticker=%s, company=%s, date=%s",
            data.get("ticker"),
            data.get("company_name"),
            data.get("as_of_date"),
        )
    except Exception:
        pass

    conn = psycopg2.connect(
        database=settings.database_name,
        user=settings.db_username,
        password=settings.password,
        host=settings.host,
        port=settings.port,
    )
    cur = conn.cursor()
    try:
        resolver = DimKeyResolver(cur)
        ticker = (data.get("ticker") or "").strip()
        if not ticker:
            logger.warning("Skipping analysis insert: generated report missing ticker")
            conn.rollback()
            return
        stock_key_val = get_stock_key(cur, ticker)
        if stock_key_val is None:
            logger.warning(
                "Skipping analysis insert: ticker %s not found or inactive in dim_stock",
                ticker,
            )
            conn.rollback()
            return
        stock_key_int = int(stock_key_val)
        insert_main = (
            "INSERT INTO rankalpha.fact_ai_stock_analysis"
            "(date_key, stock_key, source_key, market_cap_usd, revenue_cagr_3y_pct,"
            " gross_margin_trend_key, net_margin_trend_key, free_cash_flow_trend_key,"
            " insider_activity_key, beta_sp500, rate_sensitivity_bps, fx_sensitivity,"
            " commodity_exposure, news_sentiment_30d, social_sentiment_7d, options_skew_30d,"
            " short_interest_pct_float, employee_glassdoor_score, headline_buzz_score, commentary,"
            " overall_rating_key, confidence_key, timeframe_key)"
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING analysis_id"
        )
        # Ensure source exists (create if missing) and use its key
        source_key_val = get_or_create_source_key(cur, SENTIMENT_SOURCE_NAME, "1")
        # Support both full and lean schemas
        fundamental = data.get("fundamental") or {}
        macro = data.get("macro_sensitivity") or {}
        sentiment = data.get("sentiment") or {}
        # Detect lean shape to optionally pack commentary + analyst_summary as JSON
        is_lean_shape = isinstance(data.get("overall"), dict) or "sentiment_commentary" in data
        if is_lean_shape and (data.get("analyst_summary") or data.get("sentiment_commentary")):
            try:
                commentary_obj = {
                    "sentiment_commentary": data.get("sentiment_commentary"),
                    "analyst_summary": data.get("analyst_summary") or {},
                }
                commentary = json.dumps(commentary_obj, ensure_ascii=False)
            except Exception:
                commentary = data.get("sentiment_commentary") or sentiment.get("commentary")
        else:
            commentary = data.get("sentiment_commentary") or sentiment.get("commentary")
        rating_str = data.get("overall_rating") or (
            (data.get("overall") or {}).get("overall_rating")
        )
        conf_val = data.get("confidence") or ((data.get("overall") or {}).get("confidence"))
        timeframe_val = data.get("recommendation_timeframe") or (
            (data.get("overall") or {}).get("recommendation_timeframe")
        )

        date_key_i = int(data["as_of_date"].replace("-", ""))
        main_vals = (
            date_key_i,
            stock_key_int,
            source_key_val,
            data.get("market_cap_usd"),
            fundamental.get("revenue_cagr_3y_pct") if isinstance(fundamental, dict) else None,
            resolver.trend_key(fundamental.get("gross_margin_trend"))
            if isinstance(fundamental, dict)
            else None,
            resolver.trend_key(fundamental.get("net_margin_trend"))
            if isinstance(fundamental, dict)
            else None,
            resolver.trend_key(fundamental.get("free_cash_flow_trend"))
            if isinstance(fundamental, dict)
            else None,
            resolver.trend_key(fundamental.get("insider_activity"))
            if isinstance(fundamental, dict)
            else None,
            macro.get("beta_sp500") if isinstance(macro, dict) else None,
            macro.get("rate_sensitivity_bps") if isinstance(macro, dict) else None,
            # NOTE: These are string level labels (varchar), not FK dim keys.
            # Values are expected to be low|medium|high.
            _coerce_level_label(macro.get("fx_sensitivity")) if isinstance(macro, dict) else None,
            _coerce_level_label(macro.get("commodity_exposure"))
            if isinstance(macro, dict)
            else None,
            sentiment.get("news_sentiment_30d") if isinstance(sentiment, dict) else None,
            sentiment.get("social_sentiment_7d") if isinstance(sentiment, dict) else None,
            sentiment.get("options_skew_30d") if isinstance(sentiment, dict) else None,
            sentiment.get("short_interest_pct_float") if isinstance(sentiment, dict) else None,
            sentiment.get("employee_glassdoor_score") if isinstance(sentiment, dict) else None,
            sentiment.get("headline_buzz_score") if isinstance(sentiment, dict) else None,
            commentary,
            resolver.rating_key(rating_str),
            resolver.confidence_key(conf_val),
            resolver.timeframe_key(timeframe_val),
        )
        cur.execute(insert_main, main_vals)
        row = cur.fetchone()
        if row is None:
            raise ValueError("No analysis_id returned from INSERT")
        analysis_id = row[0]
        try:
            logger.info(
                "Inserted analysis_id=%s for %s (%s) on %s",
                analysis_id,
                data.get("company_name"),
                data.get("ticker"),
                data.get("as_of_date"),
            )
        except Exception:
            logger.info("Inserted analysis_id=%s", analysis_id)

        # Valuation metrics
        val = fundamental.get("valuation_vs_peers", {}) if isinstance(fundamental, dict) else {}
        cur.execute(
            "INSERT INTO rankalpha.fact_ai_valuation_metrics"
            "(analysis_id, pe_forward, ev_ebitda_forward, pe_percentile_in_sector)"
            "VALUES (%s, %s, %s, %s)",
            (
                analysis_id,
                val.get("pe_forward"),
                val.get("ev_ebitda_forward"),
                val.get("pe_percentile_in_sector"),
            ),
        )

        # External (human) analyst target snapshot (optional)
        try:
            if extra and table_exists(cur, "rankalpha.fact_ai_human_analyst_target"):
                organic_raw = extra.get("human_analyst_targets_organic")
                organic_obj = None
                if isinstance(organic_raw, str) and organic_raw.strip():
                    try:
                        organic_obj = json.loads(organic_raw)
                    except Exception:
                        organic_obj = None
                elif isinstance(organic_raw, list):
                    organic_obj = organic_raw
                provider = (
                    (extra.get("human_analyst_targets_provider") or "serper") if extra else "serper"
                )
                query_text = extra.get("human_analyst_targets_query") if extra else None
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_human_analyst_target "
                    "(date_key, analysis_id, provider, query_text, targets_organic, target_low_usd, target_high_usd, "
                    " target_median_usd, target_mean_usd, target_count) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (analysis_id) DO UPDATE SET "
                    "date_key=EXCLUDED.date_key, "
                    "provider=EXCLUDED.provider, query_text=EXCLUDED.query_text, targets_organic=EXCLUDED.targets_organic, "
                    "target_low_usd=EXCLUDED.target_low_usd, target_high_usd=EXCLUDED.target_high_usd, "
                    "target_median_usd=EXCLUDED.target_median_usd, target_mean_usd=EXCLUDED.target_mean_usd, "
                    "target_count=EXCLUDED.target_count",
                    (
                        date_key_i,
                        analysis_id,
                        str(provider),
                        str(query_text) if query_text else None,
                        Json(organic_obj) if organic_obj is not None else None,
                        extra.get("human_analyst_target_low_usd"),
                        extra.get("human_analyst_target_high_usd"),
                        extra.get("human_analyst_target_median_usd"),
                        extra.get("human_analyst_target_mean_usd"),
                        extra.get("human_analyst_target_count"),
                    ),
                )
        except Exception:
            try:
                logger.warning(
                    "Failed to upsert human analyst target snapshot for analysis_id=%s; continuing without it",
                    analysis_id,
                    exc_info=True,
                )
            except Exception:
                pass
            # If Serper analyst targets are enabled, persistence is considered required.
            if bool(getattr(settings, "sentiment_use_serper_analyst_targets", False)):
                raise

        # Peer comparisons
        peer_values = []
        for peer in data.get("peer_analysis", []):
            peer_key = get_stock_key(cur, peer["ticker"])
            if peer_key:
                peer_values.append(
                    (
                        analysis_id,
                        peer_key,
                        peer.get("pe_forward"),
                        peer.get("ev_ebitda_forward"),
                        peer.get("1y_price_total_return_pct"),
                        peer.get("summary"),
                    )
                )
        if peer_values:
            execute_values(
                cur,
                "INSERT INTO rankalpha.fact_ai_peer_comparison"
                "(analysis_id, peer_stock_key, pe_forward, ev_ebitda_forward, return_1y_pct, summary) VALUES %s",
                peer_values,
            )

        # Factor scores
        factor_scores = data.get("factor_scores", {})
        fs_vals = []
        for key, value in factor_scores.items():
            style_key = resolver.style_key(key)
            if style_key is None:
                continue
            fs_vals.append((analysis_id, style_key, value))
        if fs_vals:
            execute_values(
                cur,
                "INSERT INTO rankalpha.fact_ai_factor_score"
                "(analysis_id, style_key, score) VALUES %s",
                fs_vals,
            )

        # Catalysts: support legacy {shortTerm,longTerm} and lean list
        catalysts = data.get("catalysts")
        if isinstance(catalysts, dict):
            for ct in catalysts.get("shortTerm", []):
                # Accept either probability_pct or probability_ptc from the JSON
                prob = ct.get("probability_pct")
                if prob is None:
                    prob = ct.get("probability_ptc")
                # Accept either price_drop_risk_pct or price_drop_ptc_risk_if_fails
                drop_risk = ct.get("price_drop_risk_pct")
                if drop_risk is None:
                    drop_risk = ct.get("price_drop_ptc_risk_if_fails")
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_catalyst"
                    "(analysis_id, catalyst_type, title, description, probability_pct, expected_price_move_pct, expected_date, priced_in_pct, price_drop_risk_pct)"
                    "VALUES (%s, 'short', %s, %s, %s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        ct.get("title"),
                        ct.get("description"),
                        prob,
                        ct.get("expected_price_move_pct"),
                        ct.get("expected_date"),
                        ct.get("priced_in_pct"),
                        drop_risk,
                    ),
                )
            for ct in catalysts.get("longTerm", []):
                prob = ct.get("probability_pct")
                if prob is None:
                    prob = ct.get("probability_ptc")
                drop_risk = ct.get("price_drop_risk_pct")
                if drop_risk is None:
                    drop_risk = ct.get("price_drop_ptc_risk_if_fails")
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_catalyst"
                    "(analysis_id, catalyst_type, title, description, probability_pct, expected_price_move_pct, expected_date, priced_in_pct, price_drop_risk_pct)"
                    "VALUES (%s, 'long', %s, %s, %s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        ct.get("title"),
                        ct.get("description"),
                        prob,
                        ct.get("expected_price_move_pct"),
                        ct.get("expected_date"),
                        ct.get("priced_in_pct"),
                        drop_risk,
                    ),
                )
        elif isinstance(catalysts, list):
            for ct in catalysts:
                catalyst_type = _normalize_catalyst_type(ct.get("catalyst_type") or ct.get("type"))
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_catalyst"
                    "(analysis_id, catalyst_type, title, description, probability_pct, expected_price_move_pct, expected_date, priced_in_pct, price_drop_risk_pct)"
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        catalyst_type,
                        ct.get("title"),
                        ct.get("description"),
                        ct.get("probability_pct"),
                        ct.get("expected_price_move_pct"),
                        ct.get("expected_date"),
                        ct.get("priced_in_pct"),
                        ct.get("price_drop_risk_pct"),
                    ),
                )

        # Scenario price targets (support legacy + lean schema shapes)
        scenario_targets = data.get("scenario_price_targets") or {}
        scenario_rows = []
        if isinstance(scenario_targets, dict):
            if any(key in scenario_targets for key in ("bull", "base", "bear")):
                # Legacy shape: {bull|base|bear: {price, probability_pct}}
                for scen in ("bull", "base", "bear"):
                    sdata = scenario_targets.get(scen) or {}
                    price = sdata.get("price") if isinstance(sdata, dict) else None
                    prob = None
                    if isinstance(sdata, dict):
                        prob = sdata.get("probability_pct")
                        if prob is None:
                            prob = sdata.get("probability_ptc")
                    scenario_rows.append((analysis_id, scen, price, prob))
            elif any(
                key in scenario_targets
                for key in ("bull_target", "base_target", "bear_target", "associated_probabilities")
            ):
                # Lean shape: {bull_target, base_target, bear_target, associated_probabilities}
                probs = scenario_targets.get("associated_probabilities") or {}
                scenario_rows.extend(
                    [
                        (
                            analysis_id,
                            "bull",
                            scenario_targets.get("bull_target"),
                            probs.get("bull"),
                        ),
                        (
                            analysis_id,
                            "base",
                            scenario_targets.get("base_target"),
                            probs.get("base"),
                        ),
                        (
                            analysis_id,
                            "bear",
                            scenario_targets.get("bear_target"),
                            probs.get("bear"),
                        ),
                    ]
                )
        if scenario_rows:
            execute_values(
                cur,
                "INSERT INTO rankalpha.fact_ai_price_scenario"
                "(analysis_id, scenario_type, price_target, probability_pct) VALUES %s",
                scenario_rows,
            )

        # Events
        events = data.get("events", [])
        if events:
            if table_exists(cur, "rankalpha.fact_ai_event"):
                for event in events:
                    cur.execute(
                        "INSERT INTO rankalpha.fact_ai_event"
                        "(analysis_id, event_title, event_summary, event_date, expected_impact_pct, confidence_key)"
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (
                            analysis_id,
                            event.get("title"),
                            event.get("summary"),
                            event.get("date"),
                            event.get("expected_impact_pct"),
                            resolver.confidence_key(event.get("confidence")),
                        ),
                    )
            else:
                logger.warning("Skipping events insert: table rankalpha.fact_ai_event not found")

        # Risk factors
        risks = data.get("risks", [])
        if risks:
            if table_exists(cur, "rankalpha.fact_ai_risk"):
                for risk in risks:
                    cur.execute(
                        "INSERT INTO rankalpha.fact_ai_risk"
                        "(analysis_id, risk_title, risk_summary, probability_pct, severity_pct)"
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            analysis_id,
                            risk.get("title"),
                            risk.get("summary"),
                            risk.get("probability_pct"),
                            risk.get("severity_pct"),
                        ),
                    )
            else:
                logger.warning("Skipping risks insert: table rankalpha.fact_ai_risk not found")

        # News items
        news_items = data.get("news", [])
        if news_items:
            if table_exists(cur, "rankalpha.fact_ai_news"):
                for news_item in news_items:
                    cur.execute(
                        "INSERT INTO rankalpha.fact_ai_news"
                        "(analysis_id, published_at, headline, url, sentiment_score)"
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            analysis_id,
                            news_item.get("published_at"),
                            news_item.get("headline"),
                            news_item.get("url"),
                            news_item.get("sentiment_score"),
                        ),
                    )
            else:
                logger.warning("Skipping news insert: table rankalpha.fact_ai_news not found")

        # Scenario proximity (lean)
        scenario_proximity = data.get("scenario_proximity", [])
        if scenario_proximity:
            if table_exists(cur, "rankalpha.fact_ai_scenario_proximity"):
                for scen in scenario_proximity:
                    cur.execute(
                        "INSERT INTO rankalpha.fact_ai_scenario_proximity"
                        "(analysis_id, scenario_id, similarity_score, scenario_summary) VALUES (%s, %s, %s, %s)",
                        (
                            analysis_id,
                            scen.get("scenario_id"),
                            scen.get("similarity_score"),
                            scen.get("scenario_summary"),
                        ),
                    )
            else:
                logger.warning(
                    "Skipping scenario proximity insert: table rankalpha.fact_ai_scenario_proximity not found"
                )

        # Alternative data (lean)
        alt_data = data.get("alternative_data") or {}
        if isinstance(alt_data, dict):
            if table_exists(cur, "rankalpha.fact_ai_alternative_data"):
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_alternative_data"
                    "(analysis_id, credit_card_spend_score, app_ranking_score, job_postings_trend)"
                    "VALUES (%s, %s, %s, %s)",
                    (
                        analysis_id,
                        alt_data.get("credit_card_spend_score"),
                        alt_data.get("app_ranking_score"),
                        alt_data.get("job_postings_trend"),
                    ),
                )
            else:
                logger.warning(
                    "Skipping alternative data insert: table rankalpha.fact_ai_alternative_data not found"
                )

        # Attach benchmarking data when present
        benchmarking = data.get("benchmarking")
        if isinstance(benchmarking, dict):
            if table_exists(cur, "rankalpha.fact_ai_benchmarking"):
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_benchmarking"
                    "(analysis_id, revenue_growth_rank, margin_rank, valuation_rank, sentiment_rank)"
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        benchmarking.get("revenue_growth_rank"),
                        benchmarking.get("margin_rank"),
                        benchmarking.get("valuation_rank"),
                        benchmarking.get("sentiment_rank"),
                    ),
                )
            else:
                logger.warning(
                    "Skipping benchmarking insert: table rankalpha.fact_ai_benchmarking not found"
                )

        # Structured summary metrics
        summary_metrics = data.get("summary_metrics") or {}
        if isinstance(summary_metrics, dict):
            if table_exists(cur, "rankalpha.fact_ai_summary_metrics"):
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_summary_metrics"
                    "(analysis_id, upside_pct, downside_pct, base_case_pct, risk_reward_ratio)"
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        summary_metrics.get("upside_pct"),
                        summary_metrics.get("downside_pct"),
                        summary_metrics.get("base_case_pct"),
                        summary_metrics.get("risk_reward_ratio"),
                    ),
                )
            else:
                logger.warning(
                    "Skipping summary metrics insert: table rankalpha.fact_ai_summary_metrics not found"
                )

        # Store structured lean summary when present
        lean_summary = data.get("overall") or {}
        if isinstance(lean_summary, dict):
            if table_exists(cur, "rankalpha.fact_ai_overall_summary"):
                cur.execute(
                    "INSERT INTO rankalpha.fact_ai_overall_summary"
                    "(analysis_id, overall_rating_key, confidence_key, recommendation_timeframe_key, analyst_summary)"
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        analysis_id,
                        resolver.rating_key(lean_summary.get("overall_rating")),
                        resolver.confidence_key(lean_summary.get("confidence")),
                        resolver.timeframe_key(lean_summary.get("recommendation_timeframe")),
                        json.dumps(
                            lean_summary.get("analyst_summary"),
                            ensure_ascii=False,
                        )
                        if lean_summary.get("analyst_summary")
                        else None,
                    ),
                )
            else:
                logger.warning(
                    "Skipping overall summary insert: table rankalpha.fact_ai_overall_summary not found"
                )

        # Headline risks (Lean Schema v1.0 top-level list)
        headline_risks = data.get("headline_risks", [])
        if isinstance(headline_risks, list) and headline_risks:
            if table_exists(cur, "rankalpha.fact_ai_headline_risk"):
                for risk_text in headline_risks:
                    if not isinstance(risk_text, str) or not risk_text.strip():
                        continue
                    cur.execute(
                        "INSERT INTO rankalpha.fact_ai_headline_risk (analysis_id, risk_text) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (analysis_id, risk_text.strip()),
                    )
            else:
                logger.warning(
                    "Skipping headline risks insert: table rankalpha.fact_ai_headline_risk not found"
                )

        # Data gaps
        for gap in data.get("data_gaps", []):
            cur.execute(
                "INSERT INTO rankalpha.fact_ai_data_gap (analysis_id, gap_text) VALUES (%s, %s)",
                (analysis_id, gap),
            )

        conn.commit()
        with contextlib.suppress(Exception):
            _notify_ai_cache_refresh(data.get("ticker"), str(analysis_id), settings)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        with contextlib.suppress(Exception):
            conn.close()


__all__ = [
    "SENTIMENT_SOURCE_NAME",
    "DimKeyResolver",
    "extract_json_block",
    "get_stock_key",
    "get_or_create_source_key",
    "load_json_and_insert",
]
