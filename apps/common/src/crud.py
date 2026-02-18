from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timezone
from typing import Any

from sqlalchemy import Row, cast, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from apps.common.src.settings_base import BaseAppSettings

from .models import (
    DimAssetType,
    DimConfidence,
    DimDate,
    DimFinMetric,
    DimRating,
    DimSource,
    DimStock,
    DimStyle,
    DimTenor,
    DimTimeframe,
    DimTrendCategory,
    DimVarMethod,
    FactAiCatalyst,
    FactAiDataGap,
    FactAiFactorScore,
    FactAiHeadlineRisk,
    FactAiMacroRisk,
    FactAiPeerComparison,
    FactAiPriceScenario,
    FactAiStockAnalysis,
    FactAiValuationMetrics,
    FactBenchmarkPrice,
    FactCorporateAction,
    FactFactorReturn,
    FactFinFundamental,
    FactFxRate,
    FactIvSurface,
    FactPortfolioFactorExposure,
    FactPortfolioNav,
    FactPortfolioScenarioPnl,
    FactPortfolioTrade,
    FactPortfolioVar,
    FactRiskFreeRate,
    FactSecurityPrice,
    FactStockBorrowRate,
    FactTradeRecommendation,
    Portfolio,
    PortfolioPosition,
    VLatestScreener,
    VLatestScreenerValues,
    VwFinFundamentals,
    VwIvSurface,
    VwModelStrategyPerformance,
    VwNewsSentiment,
    VwPortfolioFactorExposure,
    VwPortfolioPerformance,
    VwPortfolioPosition,
    VwPortfolioPositionAttribution,
    VwPortfolioScenarioPnl,
    VwPortfolioSnapshot,
    VwPortfolioTopContrib,
    VwPortfolioTurnover,
    VwPortfolioVar,
    VwRiskDashboard,
    VwRiskFreeRate,
    VwScoreHistory,
    VwScreenerRank,
    VwStockBorrowRate,
    VwStockStyleScores,
    VwTradeRecommendation,
)


def get_engine(settings: BaseAppSettings | None = None) -> Any:
    """Return a SQLAlchemy engine configured from :class:`BaseAppSettings`."""
    settings = settings or BaseAppSettings()
    url = (
        "postgresql+psycopg2://"
        f"{settings.db_username}:{settings.password}"
        f"@{settings.host}:{settings.port}/{settings.database_name}"
    )
    return create_engine(url)


def get_or_create_stock(session: Session, symbol: str) -> int:
    """Ensure a DimStock exists and return its key."""
    return _get_or_create_stock(session, symbol, "equity")


def get_or_create_stock_any(
    session: Session,
    symbol: str,
    *,
    asset_type_label: str | None = "equity",
    currency_code: str | None = None,
) -> int:
    """Ensure a DimStock exists with optional asset_type/currency, returning its key.

    This is useful for broker-ingested symbols where we may have a currency code but
    limited additional metadata.
    """
    return _get_or_create_stock(session, symbol, asset_type_label, currency_code)


def get_metric(session: Session, metric_code: str) -> tuple[str, int, str]:
    """
    Lookup an existing metric_key by metric_code.
    Raises ValueError if no such metric exists.
    """
    result = session.execute(
        select(DimFinMetric.metric_code, DimFinMetric.metric_key, DimFinMetric.stmt_code).where(
            DimFinMetric.metric_code == metric_code
        )
    ).one_or_none()

    if result is None:
        raise ValueError(f"Metric not found: {metric_code}")
    code, key, stmt = result
    return code, key, stmt


def upsert_fundamental(
    session: Session,
    date_key: int,
    stock_key: int,
    metric_key: int,
    value: float,
    source_key: int,
    fiscal_year: int,
    fiscal_period: str,
) -> None:
    """
    Insert or update a FactFinFundamental.
    Conflicts on the PK constraint 'pk_fact_finfund' (date_key, stock_key, stmt_code, metric_key).
    """

    stmt = (
        insert(FactFinFundamental)
        .values(
            date_key=date_key,
            stock_key=stock_key,
            metric_key=metric_key,
            fact_id=uuid.uuid4(),
            source_key=source_key,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            metric_value=value,
            load_ts=datetime.now(timezone.utc),
        )
        .on_conflict_do_update(
            constraint="pk_fact_finfund",
            set_={
                "metric_value": value,
                "load_ts": datetime.now(timezone.utc),
            },
        )
    )
    session.execute(stmt)


# ── SMALL LOOKUP HELPERS ───────────────────────────────────
def _get_key(session: Session, model, label_col: str, value: str) -> int:
    """Generic helper to fetch the surrogate key for a label in a small dimension."""
    col = getattr(model, label_col)
    key_col = next(c for c in model.__table__.columns if c.primary_key)
    key = session.scalar(select(key_col).where(col == value))
    if key is None:
        raise ValueError(f"{model.__name__}: '{value}' not found")
    return key


def _get_or_create_source(session: Session, name: str = "RankAlpha-AI", version: str = "1") -> int:
    stmt = (
        insert(DimSource)
        .values(source_name=name, version=version)
        .on_conflict_do_nothing(index_elements=[DimSource.source_name, DimSource.version])
        .returning(DimSource.source_key)
    )
    key = session.execute(stmt).scalar_one_or_none()
    if key is not None:
        return key

    fallback = session.scalar(
        select(DimSource.source_key).where(
            DimSource.source_name == name, DimSource.version == version
        )
    )

    assert fallback is not None, f"Failed to retrieve source for {name}"
    return fallback


def _get_or_create_stock(
    session: Session,
    symbol: str,
    asset_type_label: str | None,
    currency_code: str | None = None,
) -> int:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")

    asset_type_key = None
    if asset_type_label:
        norm_label = asset_type_label.strip().lower()
        asset_type_key = _get_key(session, DimAssetType, "asset_type_name", norm_label)

    ccy = (currency_code or "").strip().upper() or None
    if ccy:
        existing_ccy = session.scalar(
            select(DimStock.currency_code).where(DimStock.symbol == symbol)
        )
        if existing_ccy and existing_ccy.strip().upper() != ccy:
            raise ValueError(
                f"dim_stock symbol collision: symbol={symbol!r} already exists with "
                f"currency_code={existing_ccy!r}; refusing to upsert currency_code={ccy!r}. "
                "Use an exchange-qualified symbol for the other listing (e.g., SHOP.TO) "
                "or fix upstream symbol mapping."
            )
    insert_values: dict[str, Any] = {"symbol": symbol, "asset_type_key": asset_type_key}
    if ccy:
        insert_values["currency_code"] = ccy
    update_values: dict[str, Any] = {
        "asset_type_key": func.coalesce(DimStock.asset_type_key, asset_type_key),
    }

    stmt = (
        insert(DimStock)
        .values(**insert_values)
        .on_conflict_do_update(
            index_elements=[DimStock.symbol],
            set_=update_values,
        )
        .returning(DimStock.stock_key)
    )
    key = session.execute(stmt).scalar_one_or_none()
    if key is not None:
        return key
    fallback = session.scalar(select(DimStock.stock_key).where(DimStock.symbol == symbol))
    assert fallback is not None, f"Failed to retrieve stock_key for {symbol}"
    return fallback


def _date_to_key(session: Session, dt: date) -> int:
    key = session.scalar(select(DimDate.date_key).where(DimDate.full_date == dt))
    if key is None:
        raise ValueError(f"Date {dt} not found in dim_date")
    return key


# ── MAIN INSERTION FUNCTION ────────────────────────────────
# usage: with Session(get_engine()) as sess:
#     analysis_id = insert_ai_stock_analysis(sess, json_payload)
#     print("Loaded AI analysis", analysis_id)
def insert_ai_stock_analysis(session: Session, payload: dict[str, Any]) -> uuid.UUID:
    """
    Persist one RankAlpha‑AI jsonData structure and all child arrays.
    The call is idempotent per (date, stock, source) triple: if such a
    row exists the function returns its analysis_id without re‑inserting
    children; otherwise it inserts everything.
    """
    # --- 1. Keys & high‑level lookups ---------------------------------
    as_of = datetime.strptime(payload["as_of_date"], "%Y-%m-%d").date()
    date_key = _date_to_key(session, as_of)

    stock_key = _get_or_create_stock(
        session,
        payload["ticker"],
        payload.get("asset_type"),
        payload.get("currency_code"),
    )

    source_key = _get_or_create_source(session)

    # Trend keys (some may be None)
    trend = payload["fundamental"]
    gm_key = _get_key(session, DimTrendCategory, "trend_label", trend["gross_margin_trend"])
    nm_key = _get_key(session, DimTrendCategory, "trend_label", trend["net_margin_trend"])
    fcf_key = _get_key(session, DimTrendCategory, "trend_label", trend["free_cash_flow_trend"])
    insider_key = _get_key(session, DimTrendCategory, "trend_label", trend["insider_activity"])

    rating_key = _get_key(session, DimRating, "rating_label", payload["overall_rating"])
    conf_key = _get_key(session, DimConfidence, "confidence_label", payload["confidence"])
    tf_key = _get_key(session, DimTimeframe, "timeframe_label", payload["recommendation_timeframe"])

    # Check if we already loaded this (date, stock, source)
    existing = session.scalar(
        select(FactAiStockAnalysis.analysis_id).where(
            FactAiStockAnalysis.date_key == date_key,
            FactAiStockAnalysis.stock_key == stock_key,
            FactAiStockAnalysis.source_key == source_key,
        )
    )
    if existing:
        return existing

    # --- 2. Insert central fact ---------------------------------------
    analysis_id = uuid.uuid4()
    central = FactAiStockAnalysis(
        analysis_id=analysis_id,
        date_key=date_key,
        stock_key=stock_key,
        source_key=source_key,
        market_cap_usd=payload["market_cap_usd"],
        revenue_cagr_3y_pct=trend["revenue_cagr_3y_pct"],
        gross_margin_trend_key=gm_key,
        net_margin_trend_key=nm_key,
        free_cash_flow_trend_key=fcf_key,
        insider_activity_key=insider_key,
        beta_sp500=payload["macro_sensitivity"]["beta_sp500"],
        rate_sensitivity_bps=payload["macro_sensitivity"]["rate_sensitivity_bps"],
        fx_sensitivity=payload["macro_sensitivity"]["fx_sensitivity"],
        commodity_exposure=payload["macro_sensitivity"]["commodity_exposure"],
        news_sentiment_30d=payload["sentiment"]["news_sentiment_30d"],
        social_sentiment_7d=payload["sentiment"]["social_sentiment_7d"],
        options_skew_30d=payload["sentiment"]["options_skew_30d"],
        short_interest_pct_float=payload["sentiment"]["short_interest_pct_float"],
        employee_glassdoor_score=payload["sentiment"]["employee_glassdoor_score"],
        headline_buzz_score=payload["sentiment"]["headline_buzz_score"],
        commentary=payload["sentiment"]["commentary"],
        overall_rating_key=rating_key,
        confidence_key=conf_key,
        timeframe_key=tf_key,
    )
    session.add(central)

    # --- 3. Child 1‑to‑1: valuation -----------------------------------
    val = payload["fundamental"]["valuation_vs_peers"]
    session.add(
        FactAiValuationMetrics(
            analysis_id=analysis_id,
            pe_forward=val["pe_forward"],
            ev_ebitda_forward=val["ev_ebitda_forward"],
            pe_percentile_in_sector=val["pe_percentile_in_sector"],
        )
    )

    # --- 4. Peers ------------------------------------------------------
    for peer in payload["peer_analysis"]:
        peer_key = _get_or_create_stock(
            session,
            peer["ticker"],
            None,
            peer.get("currency_code"),
        )
        session.add(
            FactAiPeerComparison(
                analysis_id=analysis_id,
                peer_stock_key=peer_key,
                pe_forward=peer["pe_forward"],
                ev_ebitda_forward=peer["ev_ebitda_forward"],
                return_1y_pct=peer["1y_price_total_return_pct"],
                summary=peer["summary"],
            )
        )

    # --- 5. Factor scores ---------------------------------------------
    for style_name, score in payload["factor_scores"].items():
        style_key = _get_key(session, DimStyle, "style_name", style_name)
        session.add(
            FactAiFactorScore(
                analysis_id=analysis_id,
                style_key=style_key,
                score=score,
            )
        )

    # --- 6. Catalysts --------------------------------------------------
    for cat_type in ("shortTerm", "longTerm"):
        ctype_label = "short" if cat_type == "shortTerm" else "long"
        for cat in payload["catalysts"][cat_type]:
            session.add(
                FactAiCatalyst(
                    analysis_id=analysis_id,
                    catalyst_type=ctype_label,
                    title=cat["title"],
                    description=cat["description"],
                    # Standard key is probability_pct; support legacy probability_ptc for backward compat
                    probability_pct=cat.get("probability_pct", cat.get("probability_ptc")),
                    expected_price_move_pct=cat["expected_price_move_pct"],
                    expected_date=datetime.strptime(cat["expected_date"], "%Y-%m-%d").date()
                    if cat["expected_date"]
                    else None,
                    priced_in_pct=cat["priced_in_pct"],
                    # Standard key is price_drop_risk_pct; support legacy price_drop_ptc_risk_if_fails
                    price_drop_risk_pct=cat.get(
                        "price_drop_risk_pct", cat.get("price_drop_ptc_risk_if_fails")
                    ),
                )
            )

    # --- 7. Price scenarios -------------------------------------------
    for scen in ("bull", "base", "bear"):
        sdata = payload["scenario_price_targets"][scen]
        session.add(
            FactAiPriceScenario(
                analysis_id=analysis_id,
                scenario_type=scen,
                price_target=sdata["price"],
                # Standard key is probability_pct; support legacy probability_ptc
                probability_pct=sdata.get("probability_pct", sdata.get("probability_ptc")),
            )
        )

    # --- 8. Text arrays -----------------------------------------------
    for risk in payload["macro_sensitivity"]["top_macro_risks"]:
        session.add(FactAiMacroRisk(analysis_id=analysis_id, risk_text=risk))

    for risk in payload["analyst_summary"]["headline_risks"]:
        session.add(FactAiHeadlineRisk(analysis_id=analysis_id, risk_text=risk))

    for gap in payload["data_gaps"]:
        session.add(FactAiDataGap(analysis_id=analysis_id, gap_text=gap))

    # --- 9. Commit -----------------------------------------------------
    session.commit()
    return analysis_id


# ── TRADE RECOMMENDATIONS ────────────────────────────────────────────────

### Typical call pattern


# with Session(get_engine()) as sess:
#     rec_id = upsert_trade_recommendation(sess, {
#         "symbol": "AAPL",
#         "action": "BUY",
#         "recommended_price": 185.50,
#         "stop_loss_price": 174,
#         "take_profit_price": 210,
#         "size_percent": 3.0,
#         "as_of_date": "2025-06-29",
#         "confidence_label": "High",
#         "timeframe_label": "3‑6M",
#         "strategy_name": "Breakout‑2025Q2"
#     })
#     print("Recommendation ID:", rec_id)
def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    else:
        ts = datetime.fromisoformat(value)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _parse_bool_strict(value: Any) -> bool:
    """Parse a boolean value strictly.

    Accepts True/False, 1/0, and common string literals (case-insensitive):
    'true'/'t'/'1'/'yes'/'y'/'on' → True, 'false'/'f'/'0'/'no'/'n'/'off' → False.
    Raises ValueError for anything else to avoid silently setting True.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"Invalid integer for is_live (expected 0 or 1): {value}")
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "t", "1", "yes", "y", "on"):
            return True
        if s in ("false", "f", "0", "no", "n", "off"):
            return False
    raise ValueError(f"Invalid boolean literal for is_live: {value!r}")


def upsert_trade_recommendation(session: Session, payload: dict[str, Any]) -> uuid.UUID:
    """
    Idempotently insert or update a trade recommendation.

    Required keys in *payload*:
        symbol, action, recommended_price, as_of_date, source_name
    Optional keys: stop_loss_price, take_profit_price, size_shares, size_percent,
        confidence_label, timeframe_label, strategy_name, description, order_type,
        time_in_force, valid_from_ts, expiry_ts, limit_price, stop_trigger_price,
        portfolio_id, routing_hint, risk_budget_bps, signal_version, trail_percent,
        model_run_id, preconditions, auto_hedge
    """
    # 1. Dimension look‑ups
    as_of = datetime.strptime(payload["as_of_date"], "%Y-%m-%d").date()
    date_key = _date_to_key(session, as_of)

    stock_key = _get_or_create_stock(
        session,
        payload["symbol"],
        payload.get("asset_type"),
        payload.get("currency_code"),
    )

    source_key = _get_or_create_source(
        session, payload.get("source_name", "RankAlpha‑Analyst"), payload.get("source_version", "1")
    )

    confidence_key = None
    if "confidence_label" in payload:
        confidence_key = _get_key(
            session, DimConfidence, "confidence_label", payload["confidence_label"]
        )

    timeframe_key = None
    if "timeframe_label" in payload:
        timeframe_key = _get_key(
            session, DimTimeframe, "timeframe_label", payload["timeframe_label"]
        )

    order_type = payload.get("order_type", "MARKET").upper()
    time_in_force = payload.get("time_in_force", "DAY").upper()
    valid_from_ts = _parse_timestamp(payload.get("valid_from_ts") or payload.get("valid_from"))
    expiry_ts = _parse_timestamp(payload.get("expiry_ts") or payload.get("valid_until"))

    limit_price = payload.get("limit_price")
    stop_trigger_price = payload.get("stop_trigger_price")

    portfolio_id = payload.get("portfolio_id")
    if portfolio_id:
        portfolio_id = uuid.UUID(str(portfolio_id))

    routing_hint = payload.get("routing_hint")
    risk_budget_bps = payload.get("risk_budget_bps")
    signal_version = payload.get("signal_version")
    model_run_id = payload.get("model_run_id")
    if model_run_id:
        model_run_id = uuid.UUID(str(model_run_id))

    preconditions = payload.get("preconditions") or {}
    if not isinstance(preconditions, dict):
        preconditions = {}
    trail_percent = payload.get("trail_percent")
    if trail_percent is not None:
        try:
            preconditions = dict(preconditions)
            preconditions["trail_percent"] = float(trail_percent)
        except Exception:
            pass
    auto_hedge = payload.get("auto_hedge", False)

    insert_values: dict[str, Any] = {
        "date_key": date_key,
        "stock_key": stock_key,
        "source_key": source_key,
        "action": payload["action"].upper(),
        "order_type": order_type,
        "time_in_force": time_in_force,
        "expiry_ts": expiry_ts,
        "recommended_price": payload["recommended_price"],
        "limit_price": limit_price,
        "stop_trigger_price": stop_trigger_price,
        "stop_loss_price": payload.get("stop_loss_price"),
        "take_profit_price": payload.get("take_profit_price"),
        "size_shares": payload.get("size_shares"),
        "size_percent": payload.get("size_percent"),
        "portfolio_id": portfolio_id,
        "routing_hint": routing_hint,
        "risk_budget_bps": risk_budget_bps,
        "signal_version": signal_version,
        "model_run_id": model_run_id,
        "preconditions": preconditions,
        "auto_hedge": auto_hedge,
        "confidence_key": confidence_key,
        "timeframe_key": timeframe_key,
        "strategy_name": payload.get("strategy_name"),
        "description": payload.get("description"),
    }
    # Optional live flag can be passed by OMS (strict parsing)
    if "is_live" in payload and payload["is_live"] is not None:
        insert_values["is_live"] = _parse_bool_strict(payload["is_live"])  # type: ignore[arg-type]
    if valid_from_ts is not None:
        insert_values["valid_from_ts"] = valid_from_ts

    # 2. Upsert (unique on date_key+stock_key+source_key+action)
    stmt = (
        insert(FactTradeRecommendation)
        .values(**insert_values)
        .on_conflict_do_update(
            constraint="uq_trade_rec",
            set_={
                "recommended_price": payload["recommended_price"],
                "order_type": order_type,
                "time_in_force": time_in_force,
                **({"valid_from_ts": valid_from_ts} if valid_from_ts is not None else {}),
                "expiry_ts": expiry_ts,
                "limit_price": limit_price,
                "stop_trigger_price": stop_trigger_price,
                "stop_loss_price": payload.get("stop_loss_price"),
                "take_profit_price": payload.get("take_profit_price"),
                "size_shares": payload.get("size_shares"),
                "size_percent": payload.get("size_percent"),
                "portfolio_id": portfolio_id,
                "routing_hint": routing_hint,
                "risk_budget_bps": risk_budget_bps,
                "signal_version": signal_version,
                "model_run_id": model_run_id,
                "preconditions": FactTradeRecommendation.preconditions.op("||")(
                    cast(preconditions, JSONB)
                ),
                "auto_hedge": auto_hedge,
                "confidence_key": confidence_key,
                "timeframe_key": timeframe_key,
                "strategy_name": payload.get("strategy_name"),
                "description": payload.get("description"),
                **(
                    {"is_live": _parse_bool_strict(payload["is_live"])}
                    if "is_live" in payload and payload["is_live"] is not None
                    else {}
                ),
                "update_ts": datetime.now(UTC),
            },
        )
        .returning(FactTradeRecommendation.recommendation_id)
    )
    recommendation_id = session.execute(stmt).scalar_one()
    session.commit()
    return recommendation_id


def fetch_active_recommendations(
    session: Session, date_limit: date | None = None
) -> list[FactTradeRecommendation]:
    """
    Return open (is_live=FALSE) recommendations, optionally newer than *date_limit*.
    """
    q = select(FactTradeRecommendation).where(FactTradeRecommendation.is_live.is_(False))
    if date_limit:
        date_key_cutoff = _date_to_key(session, date_limit)
        q = q.where(FactTradeRecommendation.date_key >= date_key_cutoff)
    return list(session.scalars(q).all())


def get_trade_recommendations_view(
    session: Session,
    symbol: str | None = None,
    since: date | None = None,
    is_live: bool | None = None,
) -> list[VwTradeRecommendation]:
    """
    Fetch rows from the human‑readable view with optional filters.

        • *symbol*  – only that ticker
        • *since*   – only recs on/after this calendar date
        • *is_live* – True  → filled / placed
                      False → still open
                      None  → both
    """
    q = select(VwTradeRecommendation)
    if symbol:
        q = q.where(VwTradeRecommendation.symbol == symbol.upper())
    if since:
        q = q.where(VwTradeRecommendation.recommendation_date >= since)
    if is_live is not None:
        q = q.where(VwTradeRecommendation.is_live.is_(is_live))
    return list(session.scalars(q.order_by(VwTradeRecommendation.recommendation_date.desc())).all())


def get_news_sentiment_view(
    session: Session,
    symbol: str | None = None,
    since: date | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    label: str | None = None,
    source_name: str | None = None,
) -> list[VwNewsSentiment]:
    """
    Convenient read‑only access to *vw_news_sentiment*.

        • symbol       – ticker filter (case‑insensitive)
        • since        – calendar date >=
        • min_score    – sentiment_score ≥
        • max_score    – sentiment_score ≤
        • label        – sentiment_label EQ (e.g. 'positive')
        • source_name  – Newswire / {LLM} extractor
    """
    q = select(VwNewsSentiment)

    if symbol:
        q = q.where(VwNewsSentiment.symbol.ilike(symbol))
    if since:
        q = q.where(VwNewsSentiment.article_date >= since)
    if min_score is not None:
        q = q.where(VwNewsSentiment.sentiment_score >= min_score)
    if max_score is not None:
        q = q.where(VwNewsSentiment.sentiment_score <= max_score)
    if label:
        q = q.where(VwNewsSentiment.sentiment_label == label)
    if source_name:
        q = q.where(VwNewsSentiment.source_name == source_name)

    return list(
        session.scalars(
            q.order_by(VwNewsSentiment.article_date.desc(), VwNewsSentiment.sentiment_score.desc())
        ).all()
    )


def get_news_sentiment_view_by_date(
    session: Session,
    target_date: date,
    symbol: str | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    label: str | None = None,
    source_name: str | None = None,
) -> list[VwNewsSentiment]:
    """
    Fetch all rows from vw_news_sentiment for a given article_date, with optional filters:
      • target_date  – calendar date to match (exact)
      • symbol       – ticker filter (case-insensitive)
      • min_score    – sentiment_score ≥
      • max_score    – sentiment_score ≤
      • label        – sentiment_label EQ (e.g. 'positive')
      • source_name  – Newswire / {LLM} extractor
    """
    q = select(VwNewsSentiment).where(VwNewsSentiment.article_date == target_date)

    if symbol:
        q = q.where(VwNewsSentiment.symbol.ilike(symbol))
    if min_score is not None:
        q = q.where(VwNewsSentiment.sentiment_score >= min_score)
    if max_score is not None:
        q = q.where(VwNewsSentiment.sentiment_score <= max_score)
    if label:
        q = q.where(VwNewsSentiment.sentiment_label == label)
    if source_name:
        q = q.where(VwNewsSentiment.source_name == source_name)

    # order most relevant first (newest + strongest sentiment)
    q = q.order_by(VwNewsSentiment.sentiment_score.desc(), VwNewsSentiment.load_ts.desc())

    return list(session.scalars(q).all())


# … existing imports stay …


# ── PORTFOLIO CRUD ──────────────────────────────────────────────────
def get_or_create_portfolio(
    session: Session,
    portfolio_name: str,
    currency_code: str = "USD",
    inception_date: date | None = None,
    description: str | None = None,
) -> uuid.UUID:
    """
    Ensure a Portfolio exists; return portfolio_id.
    """
    stmt = (
        insert(Portfolio)
        .values(
            portfolio_name=portfolio_name,
            currency_code=currency_code.upper(),
            inception_date=inception_date,
            description=description,
        )
        .on_conflict_do_nothing(index_elements=[Portfolio.portfolio_name])
        .returning(Portfolio.portfolio_id)
    )
    pid = session.execute(stmt).scalar_one_or_none()
    if pid is not None:
        return pid
    # Already existed -> fetch
    fallback = session.scalar(
        select(Portfolio.portfolio_id).where(Portfolio.portfolio_name == portfolio_name)
    )
    assert fallback is not None, f"Failed to retrieve portfolio_id for {portfolio_name}"
    # If the portfolio was created by another process, we can still return it
    return fallback


def upsert_portfolio_position(
    session: Session,
    portfolio_name: str,
    symbol: str,
    quantity: float,
    avg_cost: float | None = None,
    open_date: date | None = None,
    currency_code: str = "USD",
) -> uuid.UUID:
    """
    Insert/update current position for (*portfolio_name*, *symbol*).
    Idempotent on (portfolio_id, stock_key).
    """
    # 1. Dimension look‑ups
    portfolio_id = get_or_create_portfolio(session, portfolio_name, currency_code)

    stock_key = _get_or_create_stock(session, symbol, "Equity")

    # 2. Upsert
    stmt = (
        insert(PortfolioPosition)
        .values(
            portfolio_id=portfolio_id,
            stock_key=stock_key,
            quantity=quantity,
            avg_cost=avg_cost,
            open_date=open_date,
        )
        .on_conflict_do_update(
            constraint="uq_portfolio_stock",
            set_={
                "quantity": quantity,
                "avg_cost": avg_cost,
                "open_date": open_date,
                "last_update_ts": datetime.now(UTC),
            },
        )
        .returning(PortfolioPosition.position_id)
    )
    pos_id = session.execute(stmt).scalar_one()
    session.commit()
    return pos_id


def get_portfolio_positions_view(
    session: Session, portfolio_name: str | None = None, symbol: str | None = None
) -> list[VwPortfolioPosition]:
    """
    Read‑only convenience wrapper on *vw_portfolio_position*.
    """
    q = select(VwPortfolioPosition)
    if portfolio_name:
        q = q.where(VwPortfolioPosition.portfolio_name == portfolio_name)
    if symbol:
        q = q.where(VwPortfolioPosition.symbol == symbol.upper())
    return list(
        session.scalars(
            q.order_by(VwPortfolioPosition.portfolio_name, VwPortfolioPosition.symbol)
        ).all()
    )


# ── PRICES & ACTIONS ──────────────────────────────────────────────────
def upsert_security_price(
    session: Session,
    date_key: int,
    stock_key: int,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    total_return_factor: float | None,
    volume: int | None,
) -> None:
    stmt = (
        insert(FactSecurityPrice)
        .values(
            date_key=date_key,
            stock_key=stock_key,
            open_px=open_px,
            high_px=high_px,
            low_px=low_px,
            close_px=close_px,
            total_return_factor=total_return_factor,
            volume=volume,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=[FactSecurityPrice.date_key, FactSecurityPrice.stock_key],
            set_={
                "open_px": open_px,
                "high_px": high_px,
                "low_px": low_px,
                "close_px": close_px,
                "total_return_factor": total_return_factor,
                "volume": volume,
                "load_ts": datetime.now(UTC),
            },
        )
    )
    session.execute(stmt)


def insert_trade(
    session: Session,
    portfolio_id: uuid.UUID,
    stock_key: int,
    side: str,
    quantity: float,
    price: float,
    exec_ts: datetime,
    commission: float | None = None,
    venue: str | None = None,
    strategy_tag: str | None = None,
) -> uuid.UUID:
    stmt = (
        insert(FactPortfolioTrade)
        .values(
            trade_id=uuid.uuid4(),
            portfolio_id=portfolio_id,
            stock_key=stock_key,
            exec_ts=exec_ts,
            side=side,
            quantity=quantity,
            price=price,
            commission=commission,
            venue=venue,
            strategy_tag=strategy_tag,
        )
        .returning(FactPortfolioTrade.trade_id)
    )
    trade_id = session.execute(stmt).scalar_one()
    session.commit()
    return trade_id


def upsert_nav(
    session: Session,
    date_key: int,
    portfolio_id: uuid.UUID,
    nav_base_ccy: float,
    gross_leverage: float | None,
    inflow: float | None,
    outflow: float | None,
) -> None:
    stmt = (
        insert(FactPortfolioNav)
        .values(
            date_key=date_key,
            portfolio_id=portfolio_id,
            nav_base_ccy=nav_base_ccy,
            gross_leverage=gross_leverage,
            capital_inflow=inflow,
            capital_outflow=outflow,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_portfolio_nav_pkey",
            set_={
                "nav_base_ccy": nav_base_ccy,
                "gross_leverage": gross_leverage,
                "capital_inflow": inflow,
                "capital_outflow": outflow,
                "load_ts": datetime.now(UTC),
            },
        )
    )
    session.execute(stmt)


def get_portfolio_snapshot(session: Session, portfolio_name: str) -> list[Row]:
    """
    Returns rows from vw_portfolio_snapshot for *portfolio_name* ordered by weight descending.
    """
    q = text("""
        SELECT *
        FROM rankalpha.vw_portfolio_snapshot
        WHERE portfolio_name = :p
        ORDER BY weight_pct DESC
    """)
    return list(session.execute(q, {"p": portfolio_name}).all())


# ── RISK HELPERS ─────────────────────────────────────────────────
def _get_var_method_key(session: Session, method_label: str) -> int:
    return _get_key(session, DimVarMethod, "method_label", method_label)


# ── UPSERT 1: DAILY VAR / ES ────────────────────────────────────
def upsert_portfolio_var(
    session: Session,
    date_key: int,
    portfolio_id: uuid.UUID,
    method_label: str,
    horizon_days: int,
    confidence_pct: float,
    var_value: float,
    es_value: float | None = None,
) -> None:
    var_method_key = _get_var_method_key(session, method_label)

    stmt = (
        insert(FactPortfolioVar)
        .values(
            date_key=date_key,
            portfolio_id=portfolio_id,
            var_method_key=var_method_key,
            horizon_days=horizon_days,
            confidence_pct=confidence_pct,
            var_value=var_value,
            es_value=es_value,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_portfolio_var_pkey",
            set_={
                "var_value": var_value,
                "es_value": es_value,
                "load_ts": datetime.now(UTC),
            },
        )
    )
    session.execute(stmt)


# ── UPSERT 2: FACTOR EXPOSURE ───────────────────────────────────
def upsert_factor_exposure(
    session: Session, date_key: int, portfolio_id: uuid.UUID, factor_key: int, exposure_value: float
) -> None:
    stmt = (
        insert(FactPortfolioFactorExposure)
        .values(
            date_key=date_key,
            portfolio_id=portfolio_id,
            factor_key=factor_key,
            exposure_value=exposure_value,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_portfolio_factor_exposure_pkey",
            set_={
                "exposure_value": exposure_value,
                "load_ts": datetime.now(UTC),
            },
        )
    )
    session.execute(stmt)


# ── UPSERT 3: STRESS‑TEST PNL ──────────────────────────────────
def upsert_portfolio_scenario_pnl(
    session: Session, date_key: int, portfolio_id: uuid.UUID, scenario_key: int, pnl_value: float
) -> None:
    stmt = (
        insert(FactPortfolioScenarioPnl)
        .values(
            date_key=date_key,
            portfolio_id=portfolio_id,
            scenario_key=scenario_key,
            pnl_value=pnl_value,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_portfolio_scenario_pnl_pkey",
            set_={
                "pnl_value": pnl_value,
                "load_ts": datetime.now(UTC),
            },
        )
    )
    session.execute(stmt)


# ── VIEW HELPERS ─────────────────────────────────────────────────
def get_portfolio_var_view(
    session: Session,
    portfolio: str | None = None,
    method: str | None = None,
    since: date | None = None,
) -> list[VwPortfolioVar]:
    q = select(VwPortfolioVar)
    if portfolio:
        q = q.where(VwPortfolioVar.portfolio_name == portfolio)
    if method:
        q = q.where(VwPortfolioVar.method_label.ilike(method))
    if since:
        q = q.where(VwPortfolioVar.risk_date >= since)
    return list(
        session.scalars(
            q.order_by(VwPortfolioVar.risk_date.desc(), VwPortfolioVar.portfolio_name)
        ).all()
    )


def get_factor_exposure_view(
    session: Session,
    portfolio: str | None = None,
    factor: str | None = None,
    model: str | None = None,
    on_date: date | None = None,
) -> list[VwPortfolioFactorExposure]:
    q = select(VwPortfolioFactorExposure)
    if portfolio:
        q = q.where(VwPortfolioFactorExposure.portfolio_name == portfolio)
    if factor:
        q = q.where(VwPortfolioFactorExposure.factor_name.ilike(factor))
    if model:
        q = q.where(VwPortfolioFactorExposure.model_name.ilike(model))
    if on_date:
        q = q.where(VwPortfolioFactorExposure.exposure_date == on_date)
    return list(
        session.scalars(
            q.order_by(
                VwPortfolioFactorExposure.exposure_date.desc(),
                VwPortfolioFactorExposure.factor_name,
            )
        ).all()
    )


def get_scenario_pnl_view(
    session: Session,
    portfolio: str | None = None,
    scenario: str | None = None,
    since: date | None = None,
) -> list[VwPortfolioScenarioPnl]:
    q = select(VwPortfolioScenarioPnl)
    if portfolio:
        q = q.where(VwPortfolioScenarioPnl.portfolio_name == portfolio)
    if scenario:
        q = q.where(VwPortfolioScenarioPnl.scenario_name.ilike(scenario))
    if since:
        q = q.where(VwPortfolioScenarioPnl.scenario_date >= since)
    return list(
        session.scalars(
            q.order_by(
                VwPortfolioScenarioPnl.scenario_date.desc(), VwPortfolioScenarioPnl.scenario_name
            )
        ).all()
    )


# ── LOOK‑UP: TENOR ----------------------------------------------------
def _get_tenor_key(session: Session, tenor_label: str) -> int:
    return _get_key(session, DimTenor, "tenor_label", tenor_label.upper())


# ── UPSERT A: Risk‑free curve ----------------------------------------
def upsert_risk_free_rate(
    session: Session, date_key: int, tenor_label: str, rate_pct: float
) -> None:
    tenor_key = _get_tenor_key(session, tenor_label)
    stmt = (
        insert(FactRiskFreeRate)
        .values(
            date_key=date_key, tenor_key=tenor_key, rate_pct=rate_pct, load_ts=datetime.now(UTC)
        )
        .on_conflict_do_update(
            constraint="fact_rfr_pkey", set_={"rate_pct": rate_pct, "load_ts": datetime.now(UTC)}
        )
    )
    session.execute(stmt)


# ── UPSERT B: Borrow rate --------------------------------------------
def upsert_borrow_rate(
    session: Session, date_key: int, stock_key: int, borrow_rate_bp: float
) -> None:
    stmt = (
        insert(FactStockBorrowRate)
        .values(
            date_key=date_key,
            stock_key=stock_key,
            borrow_rate_bp=borrow_rate_bp,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_borrow_pkey",
            set_={"borrow_rate_bp": borrow_rate_bp, "load_ts": datetime.now(UTC)},
        )
    )
    session.execute(stmt)


# ── UPSERT C: IV surface ---------------------------------------------
def upsert_iv_surface(
    session: Session, date_key: int, stock_key: int, tenor_label: str, implied_vol: float
) -> None:
    tenor_key = _get_tenor_key(session, tenor_label)
    stmt = (
        insert(FactIvSurface)
        .values(
            date_key=date_key,
            stock_key=stock_key,
            tenor_key=tenor_key,
            implied_vol=implied_vol,
            load_ts=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="fact_iv_pkey",
            set_={"implied_vol": implied_vol, "load_ts": datetime.now(UTC)},
        )
    )
    session.execute(stmt)


# ── VIEW WRAPPERS -----------------------------------------------------
def get_risk_free_rate_view(
    session: Session, on_date: date | None = None, tenor: str | None = None
) -> list[VwRiskFreeRate]:
    q = select(VwRiskFreeRate)
    if on_date:
        q = q.where(VwRiskFreeRate.rate_date == on_date)
    if tenor:
        q = q.where(VwRiskFreeRate.tenor_label == tenor.upper())
    return list(
        session.scalars(
            q.order_by(VwRiskFreeRate.rate_date.desc(), VwRiskFreeRate.tenor_label)
        ).all()
    )


def get_stock_borrow_view(
    session: Session, symbol: str | None = None, since: date | None = None
) -> list[VwStockBorrowRate]:
    q = select(VwStockBorrowRate)
    if symbol:
        q = q.where(VwStockBorrowRate.symbol == symbol.upper())
    if since:
        q = q.where(VwStockBorrowRate.borrow_date >= since)
    return list(
        session.scalars(
            q.order_by(VwStockBorrowRate.borrow_date.desc(), VwStockBorrowRate.symbol)
        ).all()
    )


def get_iv_surface_view(
    session: Session, symbol: str | None = None, tenor: str | None = None, since: date | None = None
) -> list[VwIvSurface]:
    q = select(VwIvSurface)
    if symbol:
        q = q.where(VwIvSurface.symbol == symbol.upper())
    if tenor:
        q = q.where(VwIvSurface.tenor_label == tenor.upper())
    if since:
        q = q.where(VwIvSurface.iv_date >= since)
    return list(
        session.scalars(
            q.order_by(VwIvSurface.iv_date.desc(), VwIvSurface.symbol, VwIvSurface.tenor_label)
        ).all()
    )


def upsert_factor_return(
    session: Session, date_key: int, factor_key: int, daily_return: float
) -> None:
    stmt = (
        insert(FactFactorReturn)
        .values(date_key=date_key, factor_key=factor_key, daily_return=daily_return)
        .on_conflict_do_update(
            constraint="fact_factor_return_pkey", set_={"daily_return": daily_return}
        )
    )
    session.execute(stmt)


def upsert_fx_rate(
    session: Session, date_key: int, from_ccy: str, to_ccy: str, mid_px: float
) -> None:
    stmt = (
        insert(FactFxRate)
        .values(date_key=date_key, from_ccy=from_ccy.upper(), to_ccy=to_ccy.upper(), mid_px=mid_px)
        .on_conflict_do_update(constraint="fact_fx_rate_pkey", set_={"mid_px": mid_px})
    )
    session.execute(stmt)


def upsert_benchmark_price(
    session: Session,
    date_key: int,
    benchmark_key: int,
    close_px: float,
    tr_factor: float | None = None,
) -> None:
    stmt = (
        insert(FactBenchmarkPrice)
        .values(
            date_key=date_key,
            benchmark_key=benchmark_key,
            close_px=close_px,
            total_return_factor=tr_factor,
        )
        .on_conflict_do_update(
            constraint="fact_benchmark_price_pkey",
            set_={"close_px": close_px, "total_return_factor": tr_factor},
        )
    )
    session.execute(stmt)


def insert_corporate_action(
    session: Session,
    stock_key: int,
    action_type: str,
    ex_date: date,
    ratio_or_amt: float | None = None,
) -> uuid.UUID:
    stmt = (
        insert(FactCorporateAction)
        .values(
            action_id=uuid.uuid4(),
            stock_key=stock_key,
            action_type=action_type,
            ex_date=ex_date,
            ratio_or_amt=ratio_or_amt,
        )
        .returning(FactCorporateAction.action_id)
    )
    action_id = session.execute(stmt).scalar_one()
    session.commit()
    return action_id


# ── VIEW WRAPPERS (read‑only) ─────────────────────────────────────────
def get_latest_screener(session: Session) -> list[VLatestScreener]:
    return list(session.scalars(select(VLatestScreener)).all())


def get_latest_screener_values(
    session: Session, order_by_hits: bool = False
) -> list[VLatestScreenerValues]:
    q = select(VLatestScreenerValues)
    if order_by_hits:
        q = q.order_by(
            VLatestScreenerValues.appearances.desc(), VLatestScreenerValues.rank_value.asc()
        )
    return list(session.scalars(q).all())


def get_fin_fundamentals_view(
    session: Session,
    symbol: str | None = None,
    metric_code: str | None = None,
    since: date | None = None,
) -> list[VwFinFundamentals]:
    q = select(VwFinFundamentals)
    if symbol:
        q = q.where(VwFinFundamentals.symbol == symbol.upper())
    if metric_code:
        q = q.where(VwFinFundamentals.metric_code == metric_code)
    if since:
        q = q.where(VwFinFundamentals.as_of_date >= since)
    return list(session.scalars(q).all())


def get_portfolio_performance_view(
    session: Session, portfolio_name: str | None = None, since: date | None = None
) -> list[VwPortfolioPerformance]:
    q = select(VwPortfolioPerformance)
    if portfolio_name:
        q = q.where(VwPortfolioPerformance.portfolio_name == portfolio_name)
    if since:
        q = q.where(VwPortfolioPerformance.full_date >= since)
    return list(session.scalars(q.order_by(VwPortfolioPerformance.full_date)).all())


def get_model_strategy_performance_view(
    session: Session,
    *,
    portfolio_id: uuid.UUID,
    since: date | None = None,
) -> list[VwModelStrategyPerformance]:
    q = select(VwModelStrategyPerformance).where(
        VwModelStrategyPerformance.portfolio_id == portfolio_id
    )
    if since:
        q = q.where(VwModelStrategyPerformance.full_date >= since)
    q = q.order_by(
        VwModelStrategyPerformance.strategy_name.asc(),
        VwModelStrategyPerformance.source_name.asc(),
        VwModelStrategyPerformance.full_date.asc(),
    )
    return list(session.scalars(q).all())


def get_portfolio_snapshot_view(session: Session, portfolio_name: str) -> list[VwPortfolioSnapshot]:
    q = select(VwPortfolioSnapshot).where(VwPortfolioSnapshot.portfolio_name == portfolio_name)
    return list(session.scalars(q).all())


def get_portfolio_position_attribution_view(
    session: Session,
    *,
    portfolio_id: uuid.UUID,
    since: date | None = None,
) -> list[VwPortfolioPositionAttribution]:
    q = select(VwPortfolioPositionAttribution).where(
        VwPortfolioPositionAttribution.portfolio_id == portfolio_id
    )
    if since:
        q = q.where(VwPortfolioPositionAttribution.full_date >= since)
    q = q.order_by(
        VwPortfolioPositionAttribution.full_date.asc(),
        VwPortfolioPositionAttribution.pnl_base.desc(),
    )
    return list(session.scalars(q).all())


def get_portfolio_top_contrib_view(
    session: Session, portfolio_name: str | None = None, limit: int = 20
) -> list[VwPortfolioTopContrib]:
    q = select(VwPortfolioTopContrib)
    if portfolio_name:
        q = q.where(VwPortfolioTopContrib.portfolio_name == portfolio_name)
    q = q.limit(limit)
    return list(session.scalars(q).all())


def get_portfolio_turnover_view(
    session: Session, portfolio_name: str | None = None, since: date | None = None
) -> list[VwPortfolioTurnover]:
    q = select(VwPortfolioTurnover)
    if portfolio_name:
        q = q.where(VwPortfolioTurnover.portfolio_name == portfolio_name)
    if since:
        q = q.where(VwPortfolioTurnover.full_date >= since)
    return list(session.scalars(q.order_by(VwPortfolioTurnover.full_date.desc())).all())


def get_risk_dashboard_view(
    session: Session, portfolio_name: str | None = None, since: date | None = None
) -> list[VwRiskDashboard]:
    q = select(VwRiskDashboard)
    if portfolio_name:
        q = q.where(VwRiskDashboard.portfolio_name == portfolio_name)
    if since:
        q = q.where(VwRiskDashboard.full_date >= since)
    return list(session.scalars(q.order_by(VwRiskDashboard.full_date.desc())).all())


def get_score_history_view(
    session: Session,
    symbol: str | None = None,
    score_type: str | None = None,
    since: date | None = None,
) -> list[VwScoreHistory]:
    q = select(VwScoreHistory)
    if symbol:
        q = q.where(VwScoreHistory.symbol == symbol.upper())
    if score_type:
        q = q.where(VwScoreHistory.score_type_name == score_type)
    if since:
        q = q.where(VwScoreHistory.as_of_date >= since)
    return list(session.scalars(q.order_by(VwScoreHistory.as_of_date.desc())).all())


def get_screener_rank_view(
    session: Session, symbol: str | None = None, style: str | None = None, since: date | None = None
) -> list[VwScreenerRank]:
    q = select(VwScreenerRank)
    if symbol:
        q = q.where(VwScreenerRank.symbol == symbol.upper())
    if style:
        q = q.where(VwScreenerRank.style_name == style)
    if since:
        q = q.where(VwScreenerRank.as_of_date >= since)
    return list(session.scalars(q.order_by(VwScreenerRank.as_of_date.desc())).all())


def get_stock_style_scores_view(
    session: Session, symbol: str, since: date | None = None
) -> list[VwStockStyleScores]:
    q = select(VwStockStyleScores).where(VwStockStyleScores.symbol == symbol.upper())
    if since:
        q = q.where(VwStockStyleScores.as_of_date >= since)
    return list(session.scalars(q.order_by(VwStockStyleScores.as_of_date.desc())).all())
