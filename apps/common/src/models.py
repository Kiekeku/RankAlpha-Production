from __future__ import annotations

import uuid

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base, relationship

trade_action_enum = Enum(
    "BUY",
    "SELL",
    "SHORT",
    "COVER",
    name="trade_action",
    create_type=False,  # the type already exists in Postgres
    native_enum=False,  # map to the existing domain
)

portfolio_kind_enum = Enum(
    "BROKER",
    "MODEL",
    "SLEEVE",
    name="portfolio_kind",
    create_type=False,
    native_enum=False,
)

portfolio_run_kind_enum = Enum(
    "MODEL_CONSTRUCTION",
    "BROKER_REBALANCE",
    "SLEEVE_BUILD",
    name="portfolio_run_kind",
    create_type=False,
    native_enum=False,
)

portfolio_run_status_enum = Enum(
    "DRAFT",
    "IN_REVIEW",
    "APPROVED",
    "REJECTED",
    "SUPERSEDED",
    name="portfolio_run_status",
    create_type=False,
    native_enum=False,
)

approval_status_enum = Enum(
    "PENDING",
    "APPROVED",
    "REJECTED",
    name="approval_status",
    create_type=False,
    native_enum=False,
)

signal_sizing_method_enum = Enum(
    "USE_SIGNAL_SIZE",
    "NOTIONAL_PCT_NAV",
    "RISK_BUDGET_BPS_INV_VOL",
    "RISK_BUDGET_BPS_FIXED",
    name="signal_sizing_method",
    create_type=False,
    native_enum=False,
)

risk_severity_enum = Enum(
    "INFO",
    "WARN",
    "HARD",
    name="risk_severity",
    create_type=False,
    native_enum=False,
)

risk_status_enum = Enum(
    "PASS",
    "WARN",
    "FAIL",
    name="risk_status",
    create_type=False,
    native_enum=False,
)

portfolio_position_role_enum = Enum(
    "BASELINE",
    "TARGET",
    name="portfolio_position_role",
    create_type=False,
    native_enum=False,
)

portfolio_instrument_type_enum = Enum(
    "EQUITY",
    "CASH",
    "ETF",
    "FX",
    "FUTURE",
    "OPTION",
    "BOND",
    "CRYPTO",
    name="portfolio_instrument_type",
    create_type=False,
    native_enum=False,
)


Base = declarative_base()


class AuthRole(Base):
    __tablename__ = "auth_role"
    __table_args__ = {"schema": "rankalpha"}

    role_id = Column(Integer, primary_key=True)
    role_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_assignable = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user_links = relationship(
        "AuthUserRole",
        back_populates="role",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AuthUser(Base):
    __tablename__ = "auth_user"
    __table_args__ = {"schema": "rankalpha"}

    user_id = Column(BigInteger, primary_key=True)
    email = Column(String(320), unique=True, nullable=False)
    full_name = Column(Text, nullable=True)
    avatar_url = Column(Text, nullable=True)
    provider = Column(String(40), nullable=True)
    provider_account_id = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    profile_metadata = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    roles = relationship(
        "AuthUserRole",
        foreign_keys="AuthUserRole.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assigned_roles = relationship(
        "AuthUserRole",
        foreign_keys="AuthUserRole.assigned_by",
        back_populates="assigned_by_user",
        cascade="all",
        passive_deletes=True,
    )


class AuthUserRole(Base):
    __tablename__ = "auth_user_role"
    __table_args__ = {"schema": "rankalpha"}

    user_id = Column(
        BigInteger, ForeignKey("rankalpha.auth_user.user_id", ondelete="CASCADE"), primary_key=True
    )
    role_id = Column(
        Integer, ForeignKey("rankalpha.auth_role.role_id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    assigned_by = Column(
        BigInteger, ForeignKey("rankalpha.auth_user.user_id", ondelete="SET NULL"), nullable=True
    )
    note = Column(Text, nullable=True)

    user = relationship(
        "AuthUser",
        foreign_keys=[user_id],
        back_populates="roles",
        passive_deletes=True,
    )
    role = relationship(
        "AuthRole",
        foreign_keys=[role_id],
        back_populates="user_links",
        passive_deletes=True,
    )
    assigned_by_user = relationship(
        "AuthUser",
        foreign_keys=[assigned_by],
        back_populates="assigned_roles",
        passive_deletes=True,
    )


class DimFinMetric(Base):
    __tablename__ = "dim_fin_metric"
    __table_args__ = (
        UniqueConstraint("metric_code", name="dim_fin_metric_metric_code_key"),
        {"schema": "rankalpha"},
    )

    metric_key = Column(Integer, primary_key=True)
    metric_code = Column(String(60), nullable=False)
    metric_name = Column(Text, nullable=False)
    stmt_code = Column(String(64), nullable=False)
    default_unit = Column(String(64), server_default="USD")

    fundamentals = relationship("FactFinFundamental", back_populates="metric")


class DimSource(Base):
    __tablename__ = "dim_source"
    __table_args__ = (
        UniqueConstraint("source_name", name="dim_source_source_name_key"),
        {"schema": "rankalpha"},
    )

    source_key = Column(Integer, primary_key=True)
    source_name = Column(String(50), nullable=False)
    version = Column(String(20), nullable=False, default="1")
    exclude_from_screener = Column(Boolean, nullable=False, server_default=text("false"))
    screener_weight = Column(Numeric(6, 4), nullable=False, server_default=text("1.0"))

    fundamentals = relationship("FactFinFundamental", back_populates="source")
    news_articles = relationship("FactNewsArticles", back_populates="source")


class DimStyle(Base):
    __tablename__ = "dim_style"
    __table_args__ = {"schema": "rankalpha"}

    style_key = Column(Integer, primary_key=True)
    style_name = Column(String(50), unique=True, nullable=False)
    position_side = Column(String(10), nullable=False, server_default=text("'long'"))
    screener_weight = Column(Numeric(6, 4), nullable=False, server_default=text("1.0"))


class DimDate(Base):
    __tablename__ = "dim_date"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date, unique=True, nullable=False)
    day_of_week = Column(SmallInteger, nullable=False)
    month_num = Column(SmallInteger, nullable=False)
    month_name = Column(String(10), nullable=False)
    quarter = Column(SmallInteger, nullable=False)
    calendar_year = Column(SmallInteger, nullable=False)
    is_trading_day = Column(Boolean, default=True, nullable=False)


class DimMacroSeries(Base):
    __tablename__ = "dim_macro_series"
    __table_args__ = {"schema": "rankalpha"}

    series_key = Column(Integer, primary_key=True)
    series_code = Column(Text, unique=True, nullable=False)
    series_name = Column(Text, nullable=False)
    category = Column(Text)
    frequency = Column(Text)
    units = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    description = Column(Text)


class FactMacroSeries(Base):
    __tablename__ = "fact_macro_series"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    series_key = Column(
        Integer, ForeignKey("rankalpha.dim_macro_series.series_key"), primary_key=True
    )
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"))
    value = Column(Numeric(20, 6), nullable=False)
    load_ts = Column(DateTime, nullable=False, server_default=func.now())


class VwMacroSeries(Base):
    __tablename__ = "vw_macro_series"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    date_key = Column(Integer)
    series_code = Column(Text, primary_key=True)
    series_name = Column(Text)
    category = Column(Text)
    frequency = Column(Text)
    units = Column(Text)
    value = Column(Numeric(20, 6))
    source_key = Column(Integer)
    load_ts = Column(DateTime)


class DimScoreType(Base):
    __tablename__ = "dim_score_type"
    __table_args__ = {"schema": "rankalpha"}

    score_type_key = Column(Integer, primary_key=True)
    score_type_name = Column(String(50), unique=True, nullable=False)


class DimCorrMethod(Base):
    __tablename__ = "dim_corr_method"
    __table_args__ = {"schema": "rankalpha"}

    corr_method_key = Column(Integer, primary_key=True)
    corr_method_name = Column(String(40), unique=True, nullable=False)


class DimCorrWindow(Base):
    __tablename__ = "dim_corr_window"
    __table_args__ = {"schema": "rankalpha"}

    corr_window_key = Column(Integer, primary_key=True)
    window_label = Column(String(30), unique=True, nullable=False)
    window_days = Column(Integer, nullable=False)


class FactFinFundamental(Base):
    __tablename__ = "fact_fin_fundamentals"
    __table_args__ = ({"schema": "rankalpha"},)

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)

    metric_key = Column(
        Integer, ForeignKey("rankalpha.dim_fin_metric.metric_key"), primary_key=True
    )

    fact_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    fiscal_year = Column(SmallInteger, nullable=False)
    fiscal_period = Column(String(3), nullable=False)
    metric_value = Column(Numeric(20, 4), nullable=False)
    restated = Column(Boolean, default=False)
    ttm_flag = Column(Boolean, default=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    stock = relationship("DimStock", back_populates="fundamentals")
    metric = relationship("DimFinMetric", back_populates="fundamentals")
    source = relationship("DimSource", back_populates="fundamentals")
    date = relationship("DimDate")


class FactScreenerRank(Base):
    __tablename__ = "fact_screener_rank"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    style_key = Column(Integer, ForeignKey("rankalpha.dim_style.style_key"), nullable=True)
    rank_value = Column(Integer, nullable=False)
    screening_runid = Column(UUID(as_uuid=True), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactScreenerRankChange(Base):
    __tablename__ = "fact_screener_rank_change"
    __table_args__ = {"schema": "rankalpha"}

    change_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    change_date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), nullable=False)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    style_key = Column(Integer, ForeignKey("rankalpha.dim_style.style_key"))
    change_type = Column(String(20), nullable=False)
    current_rank = Column(Integer)
    previous_rank = Column(Integer)
    rank_delta = Column(Integer)
    last_seen_date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"))
    days_since_last_seen = Column(Integer)
    absent_trading_days = Column(Integer)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactStockScores(Base):
    __tablename__ = "fact_stock_scores"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    style_key = Column(Integer, ForeignKey("rankalpha.dim_style.style_key"), nullable=False)
    score_value = Column(Numeric(14, 2), nullable=False)
    rank_value = Column(Integer, nullable=False)
    score_runid = Column(UUID(as_uuid=True), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactStockScoreType(Base):
    __tablename__ = "fact_stock_score_types"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    score_type_key = Column(
        Integer, ForeignKey("rankalpha.dim_score_type.score_type_key"), nullable=False
    )
    score_value = Column(Numeric(14, 2), nullable=False)
    rank_value = Column(Integer, nullable=False)
    score_runid = Column(UUID(as_uuid=True), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactScoreHistory(Base):
    __tablename__ = "fact_score_history"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    score_type_key = Column(
        Integer, ForeignKey("rankalpha.dim_score_type.score_type_key"), nullable=False
    )
    score = Column(Numeric(14, 2), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactNewsArticles(Base):
    __tablename__ = "fact_news_articles"
    __table_args__ = {"schema": "rankalpha"}

    article_date = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    article_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    headline = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    sentiment = relationship("FactNewsSentiment", back_populates="article", uselist=False)
    stock = relationship("DimStock", back_populates="news_articles")
    source = relationship("DimSource", back_populates="news_articles")
    date = relationship("DimDate")


class FactNewsSentiment(Base):
    __tablename__ = "fact_news_sentiment"
    __table_args__ = {"schema": "rankalpha"}

    article_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_news_articles.article_id"),
        primary_key=True,
    )
    sentiment_score = Column(Numeric(5, 3), nullable=False)
    sentiment_label = Column(String(20), nullable=False)
    analysis_runid = Column(UUID(as_uuid=True), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    article = relationship("FactNewsArticles", back_populates="sentiment")


class FactNewsRaw(Base):
    __tablename__ = "fact_news_raw"
    __table_args__ = {"schema": "rankalpha"}

    raw_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_seen_ts = Column(DateTime, server_default=func.now(), nullable=False)
    published_at = Column(DateTime, nullable=True)
    source_domain = Column(Text, nullable=False)
    url_canonical = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    snippet = Column(Text, nullable=True)
    language = Column(String(10), nullable=True)
    country = Column(String(2), nullable=True)
    dedup_key = Column(Text, nullable=False)
    text_fingerprint = Column(BigInteger, nullable=True)
    cluster_id = Column(UUID(as_uuid=True), nullable=True)
    raw_json = Column(JSONB, nullable=True)
    # Body storage (optional, gated)
    body_text = Column(Text, nullable=True)
    body_fingerprint = Column(BigInteger, nullable=True)
    body_bytes = Column(Integer, nullable=True)
    body_truncated = Column(Boolean, nullable=False, server_default="false")
    body_fetch_ts = Column(DateTime, nullable=True)
    body_source = Column(Text, nullable=True)
    body_lang = Column(String(10), nullable=True)
    body_fetch_status = Column(Text, nullable=True)
    body_fetch_error = Column(Text, nullable=True)


class DimNewsCluster(Base):
    __tablename__ = "dim_news_cluster"
    __table_args__ = {"schema": "rankalpha"}

    cluster_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_seen_ts = Column(DateTime, server_default=func.now(), nullable=False)
    simhash = Column(BigInteger, nullable=False)
    source_count = Column(Integer, nullable=False, default=1)
    centroid_raw_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.fact_news_raw.raw_id"), nullable=True
    )
    is_official = Column(Boolean, nullable=False, default=False)


class FactNewsEvent(Base):
    __tablename__ = "fact_news_event"
    __table_args__ = {"schema": "rankalpha"}

    event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.dim_news_cluster.cluster_id"), nullable=False
    )
    event_type = Column(Text, nullable=True)
    materiality_score = Column(Numeric(5, 2), nullable=False)
    direction = Column(String(20), nullable=True)
    timescale = Column(String(20), nullable=True)
    summary = Column(Text, nullable=True)
    decided_at = Column(DateTime, server_default=func.now(), nullable=False)
    model_version = Column(String(50), nullable=True)
    is_high_confidence = Column(Boolean, nullable=False, default=False)
    prefilter_reason = Column(Text, nullable=True)
    llm_prompt = Column(Text, nullable=True)
    llm_response = Column(JSONB, nullable=True)
    llm_ran_at = Column(DateTime, nullable=True)
    llm_model = Column(Text, nullable=True)
    llm_tokens_prompt = Column(Integer, nullable=True)
    llm_tokens_completion = Column(Integer, nullable=True)
    llm_error = Column(Text, nullable=True)


class FactNewsImpact(Base):
    __tablename__ = "fact_news_impact"
    __table_args__ = {"schema": "rankalpha"}

    impact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.fact_news_event.event_id"), nullable=False
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    role = Column(Text, nullable=False)
    confidence = Column(Numeric(5, 2), nullable=False, default=0.5)
    rationale = Column(Text, nullable=True)
    direction = Column(String(20), nullable=True)  # positive|negative|mixed|unclear
    magnitude_score = Column(Numeric(5, 2), nullable=True)  # 0..100
    expected_return_pct = Column(Numeric(6, 2), nullable=True)


class FactStockCorrelation(Base):
    __tablename__ = "fact_stock_correlation"
    __table_args__ = (
        CheckConstraint("stock1_key < stock2_key", name="chk_stock_order"),
        CheckConstraint(
            "correlation_value >= -1 AND correlation_value <= 1",
            name="fact_stock_correlation_correlation_value_check",
        ),
        {"schema": "rankalpha"},
    )

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    fact_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock1_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    stock2_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    corr_method_key = Column(
        Integer, ForeignKey("rankalpha.dim_corr_method.corr_method_key"), nullable=False
    )
    corr_window_key = Column(
        Integer, ForeignKey("rankalpha.dim_corr_window.corr_window_key"), nullable=False
    )
    correlation_value = Column(Numeric(6, 4), nullable=False)
    corr_runid = Column(UUID(as_uuid=True), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class DimAssetType(Base):
    __tablename__ = "dim_asset_type"
    __table_args__ = {"schema": "rankalpha"}

    asset_type_key = Column(Integer, primary_key=True)
    asset_type_name = Column(String(20), unique=True, nullable=False)

    stocks = relationship("DimStock", back_populates="asset_type")


class DimRating(Base):
    __tablename__ = "dim_rating"
    __table_args__ = {"schema": "rankalpha"}

    rating_key = Column(Integer, primary_key=True)
    rating_label = Column(String(20), unique=True, nullable=False)


class DimConfidence(Base):
    __tablename__ = "dim_confidence"
    __table_args__ = {"schema": "rankalpha"}

    confidence_key = Column(Integer, primary_key=True)
    confidence_label = Column(String(10), unique=True, nullable=False)


class DimTimeframe(Base):
    __tablename__ = "dim_timeframe"
    __table_args__ = {"schema": "rankalpha"}

    timeframe_key = Column(Integer, primary_key=True)
    timeframe_label = Column(String(12), unique=True, nullable=False)


class DimTrendCategory(Base):
    __tablename__ = "dim_trend_category"
    __table_args__ = {"schema": "rankalpha"}

    trend_key = Column(Integer, primary_key=True)
    trend_label = Column(String(20), unique=True, nullable=False)


# ── 1.2 PATCH DimStock TO REFERENCE ASSET‑TYPE ────────────
class DimStock(Base):
    __tablename__ = "dim_stock"
    __table_args__ = {"schema": "rankalpha"}

    stock_key = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)
    company_name = Column(Text)
    sector = Column(Text)
    exchange = Column(Text)
    currency_code = Column(CHAR(3), nullable=False, server_default=text("'USD'"))
    is_active = Column(Boolean, nullable=False, server_default="true")

    asset_type_key = Column(Integer, ForeignKey("rankalpha.dim_asset_type.asset_type_key"))
    asset_type = relationship("DimAssetType", back_populates="stocks")

    # existing relationships …
    fundamentals = relationship("FactFinFundamental", back_populates="stock")
    news_articles = relationship("FactNewsArticles", back_populates="stock")


# ── 1.3 CENTRAL FACT TABLE ────────────────────────────────
class FactAiStockAnalysis(Base):
    __tablename__ = "fact_ai_stock_analysis"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), nullable=False)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)

    # Scalars (sample – add any others you put in Flyway)
    market_cap_usd = Column(Numeric(20, 2))
    revenue_cagr_3y_pct = Column(Numeric(6, 2))

    gross_margin_trend_key = Column(Integer, ForeignKey("rankalpha.dim_trend_category.trend_key"))
    net_margin_trend_key = Column(Integer, ForeignKey("rankalpha.dim_trend_category.trend_key"))
    free_cash_flow_trend_key = Column(Integer, ForeignKey("rankalpha.dim_trend_category.trend_key"))
    insider_activity_key = Column(Integer, ForeignKey("rankalpha.dim_trend_category.trend_key"))

    beta_sp500 = Column(Numeric(6, 4))
    rate_sensitivity_bps = Column(Numeric(10, 2))
    fx_sensitivity = Column(String(8))
    commodity_exposure = Column(String(8))

    news_sentiment_30d = Column(Numeric(5, 2))
    social_sentiment_7d = Column(Numeric(5, 2))
    options_skew_30d = Column(Numeric(7, 3))
    short_interest_pct_float = Column(Numeric(6, 2))
    employee_glassdoor_score = Column(Numeric(4, 2))
    headline_buzz_score = Column(String(6))
    commentary = Column(Text)

    overall_rating_key = Column(Integer, ForeignKey("rankalpha.dim_rating.rating_key"))
    confidence_key = Column(Integer, ForeignKey("rankalpha.dim_confidence.confidence_key"))
    timeframe_key = Column(Integer, ForeignKey("rankalpha.dim_timeframe.timeframe_key"))

    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    # helpful back‑refs
    stock = relationship("DimStock")
    date = relationship("DimDate")
    source = relationship("DimSource")

    # children: define only if you need ORM navigation
    valuation = relationship("FactAiValuationMetrics", back_populates="analysis", uselist=False)
    peers = relationship("FactAiPeerComparison", back_populates="analysis")
    factor_scores = relationship("FactAiFactorScore", back_populates="analysis")
    catalysts = relationship("FactAiCatalyst", back_populates="analysis")
    scenarios = relationship("FactAiPriceScenario", back_populates="analysis")


# ── 1.4 CHILD FACTS (condensed – keep fields you need) ────
class FactAiValuationMetrics(Base):
    __tablename__ = "fact_ai_valuation_metrics"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    pe_forward = Column(Numeric(10, 2))
    ev_ebitda_forward = Column(Numeric(10, 2))
    pe_percentile_in_sector = Column(Numeric(6, 2))

    analysis = relationship("FactAiStockAnalysis", back_populates="valuation")


class FactAiPeerComparison(Base):
    __tablename__ = "fact_ai_peer_comparison"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    peer_stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    pe_forward = Column(Numeric(10, 2))
    ev_ebitda_forward = Column(Numeric(10, 2))
    return_1y_pct = Column(Numeric(7, 2))
    summary = Column(Text)

    analysis = relationship("FactAiStockAnalysis", back_populates="peers")
    peer_stock = relationship("DimStock")


class FactAiFactorScore(Base):
    __tablename__ = "fact_ai_factor_score"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    style_key = Column(Integer, ForeignKey("rankalpha.dim_style.style_key"), primary_key=True)
    score = Column(Numeric(14, 2), nullable=False)

    analysis = relationship("FactAiStockAnalysis", back_populates="factor_scores")
    style = relationship("DimStyle")


class FactAiCatalyst(Base):
    __tablename__ = "fact_ai_catalyst"
    __table_args__ = {"schema": "rankalpha"}

    catalyst_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        nullable=False,
    )
    catalyst_type = Column(String(10), nullable=False)  # 'short' / 'long'
    title = Column(Text, nullable=False)
    description = Column(Text)
    probability_pct = Column(Numeric(6, 2))
    expected_price_move_pct = Column(Numeric(7, 2))
    expected_date = Column(Date)
    priced_in_pct = Column(Numeric(6, 2))
    price_drop_risk_pct = Column(Numeric(7, 2))

    analysis = relationship("FactAiStockAnalysis", back_populates="catalysts")


class FactAiPriceScenario(Base):
    __tablename__ = "fact_ai_price_scenario"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    scenario_type = Column(String(6), primary_key=True)  # bull / base / bear
    price_target = Column(Numeric(20, 2))
    probability_pct = Column(Numeric(6, 2))

    analysis = relationship("FactAiStockAnalysis", back_populates="scenarios")


class FactAiMacroRisk(Base):
    __tablename__ = "fact_ai_macro_risk"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    risk_text = Column(Text, primary_key=True)


class FactAiHeadlineRisk(Base):
    __tablename__ = "fact_ai_headline_risk"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    risk_text = Column(Text, primary_key=True)


class FactAiDataGap(Base):
    __tablename__ = "fact_ai_data_gap"
    __table_args__ = {"schema": "rankalpha"}

    analysis_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_ai_stock_analysis.analysis_id"),
        primary_key=True,
    )
    gap_text = Column(Text, primary_key=True)


# ── FACT: TRADE RECOMMENDATION ────────────────────────────────────────────
class FactTradeRecommendation(Base):
    __tablename__ = "fact_trade_recommendation"
    __table_args__ = {"schema": "rankalpha"}

    recommendation_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), nullable=False)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)

    action = Column(trade_action_enum, nullable=False)
    order_type = Column(String(16), nullable=False, default="MARKET", server_default="MARKET")
    time_in_force = Column(String(12), nullable=False, default="DAY", server_default="DAY")
    valid_from_ts = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expiry_ts = Column(DateTime(timezone=True))

    recommended_price = Column(Numeric(20, 4))
    limit_price = Column(Numeric(20, 4))
    stop_trigger_price = Column(Numeric(20, 4))
    stop_loss_price = Column(Numeric(20, 4))
    take_profit_price = Column(Numeric(20, 4))

    size_shares = Column(Integer)
    size_percent = Column(Numeric(6, 2))

    portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=True,
    )
    routing_hint = Column(String(32))
    risk_budget_bps = Column(Numeric(10, 4))
    signal_version = Column(String(20))
    model_run_id = Column(UUID(as_uuid=True))
    preconditions = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    auto_hedge = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    confidence_key = Column(Integer, ForeignKey("rankalpha.dim_confidence.confidence_key"))
    timeframe_key = Column(Integer, ForeignKey("rankalpha.dim_timeframe.timeframe_key"))

    strategy_name = Column(String(50))
    description = Column(Text)

    is_live = Column(Boolean, default=False)
    filled_price = Column(Numeric(20, 4))
    filled_date = Column(Date)

    create_ts = Column(DateTime, server_default=func.now(), nullable=False)
    update_ts = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships (handy shortcuts)
    stock = relationship("DimStock", back_populates="trade_recommendations")
    source = relationship("DimSource")
    date = relationship("DimDate")
    portfolio = relationship("Portfolio")


# Add to DimStock for reverse lookup (optional)
DimStock.trade_recommendations = relationship(
    "FactTradeRecommendation",
    back_populates="stock",
    cascade="all, delete-orphan",
)


# ── VIEW: TRADE RECOMMENDATION (READ‑ONLY) ───────────────────────────────
class VwTradeRecommendation(Base):
    __tablename__ = "vw_trade_recommendation"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    # The view re‑exposes recommendation_id, so we can use it as PK
    recommendation_id = Column(UUID(as_uuid=True), primary_key=True)

    recommendation_date = Column(Date)
    symbol = Column(String(20))
    exchange = Column(String)
    asset_type = Column(String(20))

    source_name = Column(String(50))
    source_version = Column(String(20))

    action = Column(String(5))
    recommended_price = Column(Numeric(20, 4))
    stop_loss_price = Column(Numeric(20, 4))
    take_profit_price = Column(Numeric(20, 4))
    size_shares = Column(Integer)
    size_percent = Column(Numeric(6, 2))

    confidence_label = Column(String(10))
    timeframe_label = Column(String(12))

    strategy_name = Column(String(50))
    description = Column(Text)

    is_live = Column(Boolean)
    filled_price = Column(Numeric(20, 4))
    filled_date = Column(Date)

    create_ts = Column(DateTime)
    update_ts = Column(DateTime)
    order_type = Column(String(16))
    time_in_force = Column(String(12))
    valid_from_ts = Column(DateTime(timezone=True))
    expiry_ts = Column(DateTime(timezone=True))
    limit_price = Column(Numeric(20, 4))
    stop_trigger_price = Column(Numeric(20, 4))
    portfolio_id = Column(UUID(as_uuid=True))
    portfolio_name = Column(String(50))
    routing_hint = Column(String(32))
    risk_budget_bps = Column(Numeric(10, 4))
    signal_version = Column(String(20))
    model_run_id = Column(UUID(as_uuid=True))
    preconditions = Column(JSONB)
    auto_hedge = Column(Boolean)


class VwNewsSentiment(Base):
    __tablename__ = "vw_news_sentiment"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}  # read‑only

    article_id = Column(UUID(as_uuid=True), primary_key=True)
    date_key = Column(Integer)  # 20250629 etc.
    article_date = Column(Date)  # calendar date
    stock_key = Column(Integer)
    symbol = Column(String(20))
    source_key = Column(Integer)
    source_name = Column(String(50))
    source_version = Column(String(20))

    sentiment_score = Column(Numeric(5, 3))
    sentiment_label = Column(String(20))

    headline = Column(Text)
    url = Column(Text)

    load_ts = Column(DateTime)


# ── PORTFOLIO MASTER ────────────────────────────────────────────────
class Portfolio(Base):
    __tablename__ = "portfolio"
    __table_args__ = {"schema": "rankalpha"}

    portfolio_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_name = Column(String(50), unique=True, nullable=False)
    portfolio_kind = Column(
        portfolio_kind_enum,
        nullable=False,
        server_default=text("'BROKER'"),
    )
    currency_code = Column(CHAR(3), nullable=False, default="USD")
    broker_name = Column(String(32))
    broker_account_id = Column(String(64))
    is_public = Column(Boolean, nullable=False, server_default=text("false"))
    is_visible = Column(Boolean, nullable=False, server_default=text("false"))
    portfolio_owner_id = Column(
        BigInteger,
        ForeignKey("rankalpha.auth_user.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    inception_date = Column(Date)
    description = Column(Text)

    owner = relationship("AuthUser", foreign_keys=[portfolio_owner_id])
    positions = relationship(
        "PortfolioPosition", back_populates="portfolio", cascade="all, delete-orphan"
    )
    cash_positions = relationship(
        "PortfolioCashPosition",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )
    runs = relationship(
        "PortfolioRun",
        back_populates="portfolio",
        cascade="all, delete-orphan",
    )


# ── CURRENT HOLDINGS ────────────────────────────────────────────────
class PortfolioPosition(Base):
    __tablename__ = "portfolio_position"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "stock_key", name="uq_portfolio_stock"),
        {"schema": "rankalpha"},
    )

    position_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), nullable=False
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    quantity = Column(Numeric(20, 4), nullable=False)
    avg_cost = Column(Numeric(20, 4))
    open_date = Column(Date)
    last_update_ts = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    portfolio = relationship("Portfolio", back_populates="positions")
    stock = relationship("DimStock")


class PortfolioCashPosition(Base):
    __tablename__ = "portfolio_cash_position"
    __table_args__ = {"schema": "rankalpha"}

    portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        primary_key=True,
    )
    currency_code = Column(CHAR(3), primary_key=True)
    cash_amount = Column(Numeric(20, 4), nullable=False)
    last_update_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    portfolio = relationship("Portfolio", back_populates="cash_positions")


# OPTIONAL: handy read‑only mapping to the view
class VwPortfolioPosition(Base):
    __tablename__ = "vw_portfolio_position"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    position_id = Column(UUID(as_uuid=True), primary_key=True)
    portfolio_id = Column(UUID(as_uuid=True))
    portfolio_name = Column(String(50))
    symbol = Column(String(20))
    company_name = Column(Text)
    quantity = Column(Numeric(20, 4))
    avg_cost = Column(Numeric(20, 4))
    position_cost = Column(Numeric(20, 4))
    open_date = Column(Date)
    last_update_ts = Column(DateTime)


# (optional) reverse lookup on DimStock:
DimStock.positions = relationship(
    "PortfolioPosition",
    viewonly=True,
)


class PortfolioPolicyVersion(Base):
    __tablename__ = "portfolio_policy_version"
    __table_args__ = {"schema": "rankalpha"}

    policy_id = Column(BigInteger, primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    target_vol = Column(Numeric(12, 6))
    target_gross_exposure = Column(Numeric(12, 6))
    target_net_exposure = Column(Numeric(12, 6))
    approval_status = Column(
        approval_status_enum, nullable=False, server_default=text("'APPROVED'")
    )
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Text)
    constraints = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(Text)

    portfolio = relationship("Portfolio")


class PortfolioModelConfigVersion(Base):
    __tablename__ = "portfolio_model_config_version"
    __table_args__ = {"schema": "rankalpha"}

    config_id = Column(BigInteger, primary_key=True)
    model_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id", ondelete="CASCADE"),
        nullable=False,
    )
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    approval_status = Column(approval_status_enum, nullable=False, server_default=text("'PENDING'"))
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Text)
    config = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(Text)

    model_portfolio = relationship("Portfolio")


class PortfolioSignalSubscription(Base):
    __tablename__ = "portfolio_signal_subscription"
    __table_args__ = {"schema": "rankalpha"}

    subscription_id = Column(BigInteger, primary_key=True)
    broker_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), nullable=False)
    strategy_name = Column(String(50))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    approval_status = Column(approval_status_enum, nullable=False, server_default=text("'PENDING'"))
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Text)
    sizing_method = Column(signal_sizing_method_enum, nullable=False)
    allocation_pct = Column(Numeric(6, 2))
    default_risk_budget_bps = Column(Numeric(10, 4))
    default_notional_pct_nav = Column(Numeric(8, 4))
    constraints = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(Text)

    broker_portfolio = relationship("Portfolio")
    source = relationship("DimSource")


class PortfolioDeployment(Base):
    __tablename__ = "portfolio_deployment"
    __table_args__ = {"schema": "rankalpha"}

    deployment_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    model_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    sleeve_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    allocation_pct = Column(Numeric(6, 2), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(Text)

    broker_portfolio = relationship("Portfolio", foreign_keys=[broker_portfolio_id])
    model_portfolio = relationship("Portfolio", foreign_keys=[model_portfolio_id])
    sleeve_portfolio = relationship("Portfolio", foreign_keys=[sleeve_portfolio_id])


class PortfolioRun(Base):
    __tablename__ = "portfolio_run"
    __table_args__ = {"schema": "rankalpha"}

    run_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    run_kind = Column(portfolio_run_kind_enum, nullable=False)
    as_of_date = Column(Date, nullable=False)
    run_seq = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(
        portfolio_run_status_enum, nullable=False, default="DRAFT", server_default=text("'DRAFT'")
    )
    policy_id = Column(BigInteger, ForeignKey("rankalpha.portfolio_policy_version.policy_id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(Text)
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Text)

    portfolio = relationship("Portfolio", back_populates="runs")
    policy = relationship("PortfolioPolicyVersion")
    orders = relationship(
        "PortfolioOrderIntent",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    positions = relationship(
        "PortfolioRunPosition",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    inputs = relationship(
        "PortfolioRunInput",
        back_populates="broker_run",
        cascade="all, delete-orphan",
        foreign_keys="PortfolioRunInput.broker_run_id",
    )

    artifacts = relationship(
        "PortfolioRunArtifact",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    risk_report = relationship(
        "PortfolioRunRiskReport",
        back_populates="run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class PortfolioRunInput(Base):
    __tablename__ = "portfolio_run_input"
    __table_args__ = {"schema": "rankalpha"}

    broker_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id"),
        primary_key=True,
    )
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_deployment.deployment_id"),
        primary_key=True,
    )
    model_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id"),
        nullable=False,
    )
    allocation_pct_snapshot = Column(Numeric(6, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    broker_run = relationship("PortfolioRun", foreign_keys=[broker_run_id], back_populates="inputs")
    model_run = relationship("PortfolioRun", foreign_keys=[model_run_id])
    deployment = relationship("PortfolioDeployment")


class PortfolioRunPosition(Base):
    __tablename__ = "portfolio_run_position"
    __table_args__ = (
        CheckConstraint(
            "(instrument_type = 'EQUITY' AND stock_key IS NOT NULL AND currency_code IS NULL) "
            "OR (instrument_type = 'CASH' AND stock_key IS NULL AND currency_code IS NOT NULL)",
            name="ck_runpos_instrument",
        ),
        {"schema": "rankalpha"},
    )

    position_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id"),
        nullable=False,
    )
    position_role = Column(portfolio_position_role_enum, nullable=False)
    instrument_type = Column(portfolio_instrument_type_enum, nullable=False)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"))
    currency_code = Column(CHAR(3))
    quantity = Column(Numeric(20, 4), nullable=False)
    price_close_local = Column(Numeric(20, 4))
    market_value_local = Column(Numeric(20, 4))
    market_value_base = Column(Numeric(20, 4))
    weight_pct = Column(Numeric(12, 6))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("PortfolioRun", back_populates="positions")
    stock = relationship("DimStock")


class PortfolioRunArtifact(Base):
    __tablename__ = "portfolio_run_artifact"
    __table_args__ = {"schema": "rankalpha"}

    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    artifact_type = Column(Text, primary_key=True)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run = relationship("PortfolioRun", back_populates="artifacts")


class PortfolioRunSignalInput(Base):
    __tablename__ = "portfolio_run_signal_input"
    __table_args__ = {"schema": "rankalpha"}

    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    recommendation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_trade_recommendation.recommendation_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    subscription_id = Column(
        BigInteger,
        ForeignKey(
            "rankalpha.portfolio_signal_subscription.subscription_id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    sized_notional_base = Column(Numeric(20, 4))
    sized_qty_shares = Column(Integer)
    included = Column(Boolean, nullable=False, server_default=text("true"))
    reason = Column(Text)

    run = relationship("PortfolioRun")
    recommendation = relationship("FactTradeRecommendation")
    subscription = relationship("PortfolioSignalSubscription")


class PortfolioRunRiskReport(Base):
    __tablename__ = "portfolio_run_risk_report"
    __table_args__ = {"schema": "rankalpha"}

    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    evaluated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    status = Column(risk_status_enum, nullable=False)
    summary = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    run = relationship("PortfolioRun", back_populates="risk_report")
    checks = relationship(
        "PortfolioRunRiskCheck",
        back_populates="report",
        cascade="all, delete-orphan",
    )


class PortfolioRunRiskCheck(Base):
    __tablename__ = "portfolio_run_risk_check"
    __table_args__ = {"schema": "rankalpha"}

    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run_risk_report.run_id", ondelete="CASCADE"),
        primary_key=True,
    )
    check_code = Column(Text, primary_key=True)
    severity = Column(risk_severity_enum, nullable=False)
    status = Column(risk_status_enum, nullable=False)
    metric_value = Column(Numeric(20, 6))
    threshold_value = Column(Numeric(20, 6))
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    report = relationship("PortfolioRunRiskReport", back_populates="checks")


class PortfolioOrderIntent(Base):
    __tablename__ = "portfolio_order_intent"
    __table_args__ = (
        UniqueConstraint("run_id", "line_no", name="uq_order_line"),
        {"schema": "rankalpha"},
    )

    order_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id"),
        nullable=False,
    )
    line_no = Column(Integer, nullable=False)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    action = Column(trade_action_enum, nullable=False)
    order_type = Column(String(16), nullable=False, server_default=text("'MARKET'"))
    time_in_force = Column(String(12), nullable=False, server_default=text("'DAY'"))
    limit_price = Column(Numeric(20, 4))
    stop_trigger_price = Column(Numeric(20, 4))
    qty_shares = Column(Numeric(20, 4), nullable=False)
    target_weight_after = Column(Numeric(12, 6))
    approval_status = Column(approval_status_enum, nullable=False, server_default=text("'PENDING'"))
    approved_at = Column(DateTime(timezone=True))
    approved_by = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("PortfolioRun", back_populates="orders")
    stock = relationship("DimStock")
    sources = relationship(
        "PortfolioOrderIntentSource",
        back_populates="order",
        cascade="all, delete-orphan",
    )
    allocs = relationship(
        "PortfolioOrderIntentAlloc",
        back_populates="order",
        cascade="all, delete-orphan",
    )
    exports = relationship(
        "PortfolioOrderExport",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class PortfolioOrderIntentSource(Base):
    __tablename__ = "portfolio_order_intent_source"
    __table_args__ = {"schema": "rankalpha"}

    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_order_intent.order_id"),
        primary_key=True,
    )
    recommendation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_trade_recommendation.recommendation_id"),
        primary_key=True,
    )
    weight_component = Column(Numeric(12, 6))

    order = relationship("PortfolioOrderIntent", back_populates="sources")
    recommendation = relationship("FactTradeRecommendation")


class PortfolioOrderIntentAlloc(Base):
    __tablename__ = "portfolio_order_intent_alloc"
    __table_args__ = {"schema": "rankalpha"}

    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_order_intent.order_id"),
        primary_key=True,
    )
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_deployment.deployment_id"),
        primary_key=True,
    )
    qty_component = Column(Numeric(20, 4), nullable=False)
    weight_component = Column(Numeric(12, 6))

    order = relationship("PortfolioOrderIntent", back_populates="allocs")
    deployment = relationship("PortfolioDeployment")


class PortfolioOrderExport(Base):
    __tablename__ = "portfolio_order_export"
    __table_args__ = {"schema": "rankalpha"}

    order_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_order_intent.order_id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_trade_recommendation.recommendation_id", ondelete="CASCADE"),
        nullable=False,
    )
    exported_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    exported_by = Column(Text)

    order = relationship("PortfolioOrderIntent", back_populates="exports")
    run = relationship("PortfolioRun")
    recommendation = relationship("FactTradeRecommendation")


class FactInternalCross(Base):
    __tablename__ = "fact_internal_cross"
    __table_args__ = {"schema": "rankalpha"}

    cross_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_run.run_id"),
        nullable=False,
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    cross_qty = Column(Numeric(20, 4), nullable=False)
    price_close_local = Column(Numeric(20, 4), nullable=False)
    currency_code = Column(CHAR(3), nullable=False)
    buy_sleeve_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    sell_sleeve_portfolio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio.portfolio_id"),
        nullable=False,
    )
    buy_trade_id = Column(UUID(as_uuid=True), ForeignKey("rankalpha.fact_portfolio_trade.trade_id"))
    sell_trade_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.fact_portfolio_trade.trade_id")
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    broker_run = relationship("PortfolioRun")
    stock = relationship("DimStock")
    buy_sleeve_portfolio = relationship("Portfolio", foreign_keys=[buy_sleeve_portfolio_id])
    sell_sleeve_portfolio = relationship("Portfolio", foreign_keys=[sell_sleeve_portfolio_id])
    buy_trade = relationship("FactPortfolioTrade", foreign_keys=[buy_trade_id])
    sell_trade = relationship("FactPortfolioTrade", foreign_keys=[sell_trade_id])


class PortfolioTradeLink(Base):
    __tablename__ = "portfolio_trade_link"
    __table_args__ = {"schema": "rankalpha"}

    trade_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_portfolio_trade.trade_id"),
        primary_key=True,
    )
    order_id = Column(UUID(as_uuid=True), ForeignKey("rankalpha.portfolio_order_intent.order_id"))
    linked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade = relationship("FactPortfolioTrade")
    order = relationship("PortfolioOrderIntent")


class PortfolioTradeAlloc(Base):
    __tablename__ = "portfolio_trade_alloc"
    __table_args__ = {"schema": "rankalpha"}

    trade_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.fact_portfolio_trade.trade_id"),
        primary_key=True,
    )
    deployment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.portfolio_deployment.deployment_id"),
        primary_key=True,
    )
    qty_alloc = Column(Numeric(20, 4), nullable=False)
    notional_alloc_base = Column(Numeric(20, 4))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    trade = relationship("FactPortfolioTrade")
    deployment = relationship("PortfolioDeployment")


# ── MARKET & BENCHMARKS ───────────────────────────────────────────────
class FactSecurityPrice(Base):
    __tablename__ = "fact_security_price"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)

    open_px = Column(Numeric(20, 4))
    high_px = Column(Numeric(20, 4))
    low_px = Column(Numeric(20, 4))
    close_px = Column(Numeric(20, 4))
    total_return_factor = Column(Numeric(18, 8))
    volume = Column(BigInteger)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactStockNextEarnings(Base):
    __tablename__ = "fact_stock_next_earnings"
    __table_args__ = {"schema": "rankalpha"}

    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    earnings_date = Column(Date, nullable=False)
    earnings_time = Column(String)
    earnings_source = Column(String, nullable=False, default="finnhub")
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactCorporateAction(Base):
    __tablename__ = "fact_corporate_action"
    __table_args__ = {"schema": "rankalpha"}

    action_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    action_type = Column(String(12), nullable=False)
    ex_date = Column(Date, nullable=False)
    ratio_or_amt = Column(Numeric(18, 8))
    declared_ts = Column(DateTime, server_default=func.now(), nullable=False)


class DimBenchmark(Base):
    __tablename__ = "dim_benchmark"
    __table_args__ = {"schema": "rankalpha"}

    benchmark_key = Column(Integer, primary_key=True)
    benchmark_name = Column(String(50), unique=True, nullable=False)
    currency_code = Column(CHAR(3), nullable=False, default="USD")
    description = Column(Text)


class FactBenchmarkPrice(Base):
    __tablename__ = "fact_benchmark_price"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    benchmark_key = Column(
        Integer, ForeignKey("rankalpha.dim_benchmark.benchmark_key"), primary_key=True
    )
    close_px = Column(Numeric(20, 4))
    total_return_factor = Column(Numeric(18, 8))


class DimFactor(Base):
    __tablename__ = "dim_factor"
    __table_args__ = (
        UniqueConstraint("model_name", "factor_name", name="uq_factor_model_name"),
        {"schema": "rankalpha"},
    )

    factor_key = Column(Integer, primary_key=True)
    model_name = Column(String(20), nullable=False)
    factor_name = Column(String(40), nullable=False)
    description = Column(Text)


class FactFactorReturn(Base):
    __tablename__ = "fact_factor_return"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    factor_key = Column(Integer, ForeignKey("rankalpha.dim_factor.factor_key"), primary_key=True)
    daily_return = Column(Numeric(10, 6), nullable=False)


class FactFxRate(Base):
    __tablename__ = "fact_fx_rate"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    from_ccy = Column(CHAR(3), primary_key=True)
    to_ccy = Column(CHAR(3), primary_key=True)
    mid_px = Column(Numeric(18, 8), nullable=False)


# ── TRADE & PORTFOLIO TIME SERIES ─────────────────────────────────────
class FactPortfolioTrade(Base):
    __tablename__ = "fact_portfolio_trade"
    __table_args__ = {"schema": "rankalpha"}

    trade_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), nullable=False
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    exec_ts = Column(DateTime, nullable=False)
    side = Column(String(4), nullable=False)  # BUY / SELL
    quantity = Column(Numeric(20, 4), nullable=False)
    price = Column(Numeric(20, 4), nullable=False)
    commission = Column(Numeric(20, 4))
    venue = Column(String(12))
    strategy_tag = Column(String(40))


class FactPortfolioPositionHist(Base):
    __tablename__ = "fact_portfolio_position_hist"
    __table_args__ = {"schema": "rankalpha"}

    effective_date = Column(Date, primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    quantity = Column(Numeric(20, 4), nullable=False)
    avg_cost = Column(Numeric(20, 4))
    run_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)


class FactPortfolioNav(Base):
    __tablename__ = "fact_portfolio_nav"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    nav_base_ccy = Column(Numeric(20, 4), nullable=False)
    gross_leverage = Column(Numeric(6, 2))
    capital_inflow = Column(Numeric(20, 4))
    capital_outflow = Column(Numeric(20, 4))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactPortfolioBrokerNlv(Base):
    __tablename__ = "fact_portfolio_broker_nlv"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    currency_code = Column(CHAR(3), nullable=False, server_default=text("'USD'"))
    nlv_base_ccy = Column(Numeric(20, 4), nullable=False)
    gross_leverage = Column(Numeric(6, 2))
    source_system = Column(Text)
    load_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FactPortfolioPnl(Base):
    __tablename__ = "fact_portfolio_pnl"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    unrealised_pnl = Column(Numeric(20, 4))
    realised_pnl = Column(Numeric(20, 4))
    dividend_income = Column(Numeric(20, 4))
    fees = Column(Numeric(20, 4))


class FactModelStrategyNav(Base):
    __tablename__ = "fact_model_strategy_nav"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    model_portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    source_key = Column(Integer, ForeignKey("rankalpha.dim_source.source_key"), primary_key=True)
    strategy_name = Column(String(50), primary_key=True)
    nav_base_ccy = Column(Numeric(20, 4), nullable=False)
    load_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FactPortfolioRisk(Base):
    __tablename__ = "fact_portfolio_risk"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    metric_name = Column(String(32), primary_key=True)
    metric_value = Column(Numeric(20, 6), nullable=False)
    methodology = Column(String(20))


class VwModelStrategyPerformance(Base):
    __tablename__ = "vw_model_strategy_performance"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date)
    portfolio_id = Column(UUID(as_uuid=True), primary_key=True)
    portfolio_name = Column(String(50))
    source_key = Column(Integer, primary_key=True)
    source_name = Column(String(50))
    strategy_name = Column(String(50), primary_key=True)
    nav_base_ccy = Column(Numeric(20, 4))
    nav_prev = Column(Numeric(20, 4))
    daily_return = Column(Numeric(12, 6))


class FactPortfolioPositionAttribution(Base):
    __tablename__ = "fact_portfolio_position_attribution"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)

    qty_prev = Column(Numeric(20, 4), nullable=False)
    qty_end = Column(Numeric(20, 4))

    close_prev_local = Column(Numeric(20, 4))
    close_local = Column(Numeric(20, 4))
    fx_prev = Column(Numeric(18, 8))
    fx = Column(Numeric(18, 8))
    close_prev_base = Column(Numeric(20, 4))
    close_base = Column(Numeric(20, 4))
    market_value_prev_base = Column(Numeric(20, 4))
    pnl_base = Column(Numeric(20, 4))
    return_base = Column(Numeric(12, 6))
    weight_prev_pct = Column(Numeric(12, 6))
    contribution_pct = Column(Numeric(12, 6))
    methodology = Column(Text, nullable=False, server_default=text("'CLOSE_TO_CLOSE_QTY_PREV'"))
    load_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VwPortfolioPositionAttribution(Base):
    __tablename__ = "vw_portfolio_position_attribution"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date)
    portfolio_id = Column(UUID(as_uuid=True), primary_key=True)
    portfolio_name = Column(String(50))
    stock_key = Column(Integer, primary_key=True)
    symbol = Column(String(20))
    company_name = Column(Text)

    qty_prev = Column(Numeric(20, 4))
    qty_end = Column(Numeric(20, 4))
    close_prev_local = Column(Numeric(20, 4))
    close_local = Column(Numeric(20, 4))
    close_prev_base = Column(Numeric(20, 4))
    close_base = Column(Numeric(20, 4))
    market_value_prev_base = Column(Numeric(20, 4))
    pnl_base = Column(Numeric(20, 4))
    return_base = Column(Numeric(12, 6))
    weight_prev_pct = Column(Numeric(12, 6))
    contribution_pct = Column(Numeric(12, 6))
    methodology = Column(Text)
    load_ts = Column(DateTime(timezone=True))


# ---------- NEW DIMENSION -------------------------------------------
class DimVarMethod(Base):
    __tablename__ = "dim_var_method"
    __table_args__ = {"schema": "rankalpha"}

    var_method_key = Column(Integer, primary_key=True)
    method_label = Column(String(30), unique=True, nullable=False)
    description = Column(Text)

    vars = relationship("FactPortfolioVar", back_populates="method")


class DimStressScenario(Base):
    __tablename__ = "dim_stress_scenario"
    __table_args__ = {"schema": "rankalpha"}

    scenario_key = Column(Integer, primary_key=True)
    scenario_name = Column(String(50), unique=True, nullable=False)
    category = Column(String(20))
    reference_date = Column(Date)
    severity_label = Column(String(12))
    description = Column(Text)

    pnl = relationship("FactPortfolioScenarioPnl", back_populates="scenario")


# ---------- NEW FACTS -----------------------------------------------
class FactPortfolioVar(Base):
    __tablename__ = "fact_portfolio_var"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    var_method_key = Column(
        Integer, ForeignKey("rankalpha.dim_var_method.var_method_key"), primary_key=True
    )
    horizon_days = Column(Integer, primary_key=True)
    confidence_pct = Column(Numeric(5, 2), primary_key=True)
    var_value = Column(Numeric(20, 4), nullable=False)
    es_value = Column(Numeric(20, 4))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    date = relationship("DimDate")
    portfolio = relationship("Portfolio", back_populates="vars")
    method = relationship("DimVarMethod", back_populates="vars")


class FactPortfolioFactorExposure(Base):
    __tablename__ = "fact_portfolio_factor_exposure"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    factor_key = Column(Integer, ForeignKey("rankalpha.dim_factor.factor_key"), primary_key=True)
    exposure_value = Column(Numeric(20, 6), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    date = relationship("DimDate")
    portfolio = relationship("Portfolio", back_populates="factor_exposures")
    factor = relationship("DimFactor")


class FactPortfolioScenarioPnl(Base):
    __tablename__ = "fact_portfolio_scenario_pnl"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    portfolio_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.portfolio.portfolio_id"), primary_key=True
    )
    scenario_key = Column(
        Integer, ForeignKey("rankalpha.dim_stress_scenario.scenario_key"), primary_key=True
    )
    pnl_value = Column(Numeric(20, 4), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)

    date = relationship("DimDate")
    portfolio = relationship("Portfolio", back_populates="scenario_pnls")
    scenario = relationship("DimStressScenario", back_populates="pnl")


# ---------- BACK‑REFS ON Portfolio -----------------------------------
Portfolio.vars = relationship(
    "FactPortfolioVar", back_populates="portfolio", cascade="all, delete-orphan"
)
Portfolio.factor_exposures = relationship(
    "FactPortfolioFactorExposure", back_populates="portfolio", cascade="all, delete-orphan"
)
Portfolio.scenario_pnls = relationship(
    "FactPortfolioScenarioPnl", back_populates="portfolio", cascade="all, delete-orphan"
)


# ---------- READ‑ONLY RISK VIEWS ------------------------------------
class VwPortfolioVar(Base):
    __tablename__ = "vw_portfolio_var"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    risk_date = Column(Date, primary_key=True)
    portfolio_name = Column(String(50), primary_key=True)
    method_label = Column(String(30), primary_key=True)
    horizon_days = Column(Integer, primary_key=True)
    confidence_pct = Column(Numeric(5, 2), primary_key=True)

    var_value = Column(Numeric(20, 4))
    es_value = Column(Numeric(20, 4))
    load_ts = Column(DateTime)


class VwPortfolioFactorExposure(Base):
    __tablename__ = "vw_portfolio_factor_exposure"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    exposure_date = Column(Date, primary_key=True)
    portfolio_name = Column(String(50), primary_key=True)
    model_name = Column(String(20), primary_key=True)
    factor_name = Column(String(40), primary_key=True)

    exposure_value = Column(Numeric(20, 6))
    load_ts = Column(DateTime)


class VwPortfolioScenarioPnl(Base):
    __tablename__ = "vw_portfolio_scenario_pnl"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    scenario_date = Column(Date, primary_key=True)
    portfolio_name = Column(String(50), primary_key=True)
    scenario_name = Column(String(50), primary_key=True)

    category = Column(String(20))
    severity_label = Column(String(12))
    pnl_value = Column(Numeric(20, 4))
    load_ts = Column(DateTime)


# ── MARKET REFERENCE DATA ────────────────────────────────────────────
class DimTenor(Base):
    __tablename__ = "dim_tenor"
    __table_args__ = {"schema": "rankalpha"}

    tenor_key = Column(Integer, primary_key=True)
    tenor_label = Column(String(10), unique=True, nullable=False)
    tenor_days = Column(SmallInteger, nullable=False)


# Risk‑free
class FactRiskFreeRate(Base):
    __tablename__ = "fact_risk_free_rate"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    tenor_key = Column(Integer, ForeignKey("rankalpha.dim_tenor.tenor_key"), primary_key=True)
    rate_pct = Column(Numeric(10, 4), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


# Borrow cost
class FactStockBorrowRate(Base):
    __tablename__ = "fact_stock_borrow_rate"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    borrow_rate_bp = Column(Numeric(12, 4), nullable=False)  # basis‑points
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


# Implied volatility
class FactIvSurface(Base):
    __tablename__ = "fact_iv_surface"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    tenor_key = Column(Integer, ForeignKey("rankalpha.dim_tenor.tenor_key"), primary_key=True)
    implied_vol = Column(Numeric(8, 4), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


# Read‑only views ------------------------------------------------------
class VwRiskFreeRate(Base):
    __tablename__ = "vw_risk_free_rate"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    rate_date = Column(Date, primary_key=True)
    tenor_label = Column(String(10), primary_key=True)
    rate_pct = Column(Numeric(10, 4))


# ---------- AI ANALYSIS FULL VIEW (denormalized) --------------------
class VwAiAnalysisFull(Base):
    __tablename__ = "vw_ai_analysis_full"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True)
    date_key = Column(Integer)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    company_name = Column(Text)
    asset_type = Column(String(20))
    source_name = Column(String(50))

    market_cap_usd = Column(Numeric(20, 2))
    revenue_cagr_3y_pct = Column(Numeric(6, 2))
    gross_margin_trend = Column(String(20))
    net_margin_trend = Column(String(20))
    free_cash_flow_trend = Column(String(20))
    insider_activity = Column(String(20))

    beta_sp500 = Column(Numeric(6, 4))
    rate_sensitivity_bps = Column(Numeric(10, 2))
    fx_sensitivity = Column(String(8))
    commodity_exposure = Column(String(8))

    news_sentiment_30d = Column(Numeric(5, 2))
    social_sentiment_7d = Column(Numeric(5, 2))
    options_skew_30d = Column(Numeric(7, 3))
    short_interest_pct_float = Column(Numeric(6, 2))
    employee_glassdoor_score = Column(Numeric(4, 2))
    headline_buzz_score = Column(String(6))
    commentary = Column(Text)

    overall_rating = Column(String(20))
    confidence = Column(String(10))
    recommendation_timeframe = Column(String(12))

    pe_forward = Column(Numeric(10, 2))
    ev_ebitda_forward = Column(Numeric(10, 2))
    pe_percentile_in_sector = Column(Numeric(6, 2))

    value_score = Column(Numeric(5, 2))
    quality_score = Column(Numeric(5, 2))
    momentum_score = Column(Numeric(5, 2))
    low_vol_score = Column(Numeric(5, 2))

    bull_price_target = Column(Numeric(20, 2))
    bull_probability_pct = Column(Numeric(6, 2))
    base_price_target = Column(Numeric(20, 2))
    base_probability_pct = Column(Numeric(6, 2))
    bear_price_target = Column(Numeric(20, 2))
    bear_probability_pct = Column(Numeric(6, 2))

    short_catalysts = Column(JSONB)
    long_catalysts = Column(JSONB)
    events = Column(JSONB)
    macro_risks = Column(ARRAY(Text))
    headline_risks = Column(ARRAY(Text))
    data_gaps = Column(ARRAY(Text))
    peers = Column(JSONB)
    analyst_bull_case = Column(Text)
    analyst_bear_case = Column(Text)
    analyst_valuation_check = Column(Text)
    human_analyst_targets_provider = Column(Text)
    human_analyst_targets_query = Column(Text)
    human_analyst_targets_organic = Column(JSONB)
    human_analyst_target_low_usd = Column(Numeric(20, 2))
    human_analyst_target_high_usd = Column(Numeric(20, 2))
    human_analyst_target_median_usd = Column(Numeric(20, 2))
    human_analyst_target_mean_usd = Column(Numeric(20, 2))
    human_analyst_target_count = Column(Integer)
    load_ts = Column(DateTime)


# Latest AI analysis per symbol (one row per symbol)
class VwAiAnalysisLatest(Base):
    __tablename__ = "vw_ai_analysis_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True)
    date_key = Column(Integer)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    company_name = Column(Text)
    asset_type = Column(String(20))
    source_name = Column(String(50))

    market_cap_usd = Column(Numeric(20, 2))
    revenue_cagr_3y_pct = Column(Numeric(6, 2))
    gross_margin_trend = Column(String(20))
    net_margin_trend = Column(String(20))
    free_cash_flow_trend = Column(String(20))
    insider_activity = Column(String(20))

    beta_sp500 = Column(Numeric(6, 4))
    rate_sensitivity_bps = Column(Numeric(10, 2))
    fx_sensitivity = Column(String(8))
    commodity_exposure = Column(String(8))

    news_sentiment_30d = Column(Numeric(5, 2))
    social_sentiment_7d = Column(Numeric(5, 2))
    options_skew_30d = Column(Numeric(7, 3))
    short_interest_pct_float = Column(Numeric(6, 2))
    employee_glassdoor_score = Column(Numeric(4, 2))
    headline_buzz_score = Column(String(6))
    commentary = Column(Text)

    overall_rating = Column(String(20))
    confidence = Column(String(10))
    recommendation_timeframe = Column(String(12))

    pe_forward = Column(Numeric(10, 2))
    ev_ebitda_forward = Column(Numeric(10, 2))
    pe_percentile_in_sector = Column(Numeric(6, 2))

    value_score = Column(Numeric(5, 2))
    quality_score = Column(Numeric(5, 2))
    momentum_score = Column(Numeric(5, 2))
    low_vol_score = Column(Numeric(5, 2))

    bull_price_target = Column(Numeric(20, 2))
    bull_probability_pct = Column(Numeric(6, 2))
    base_price_target = Column(Numeric(20, 2))
    base_probability_pct = Column(Numeric(6, 2))
    bear_price_target = Column(Numeric(20, 2))
    bear_probability_pct = Column(Numeric(6, 2))

    short_catalysts = Column(JSONB)
    long_catalysts = Column(JSONB)
    events = Column(JSONB)
    macro_risks = Column(ARRAY(Text))
    headline_risks = Column(ARRAY(Text))
    data_gaps = Column(ARRAY(Text))
    peers = Column(JSONB)
    analyst_bull_case = Column(Text)
    analyst_bear_case = Column(Text)
    analyst_valuation_check = Column(Text)
    human_analyst_targets_provider = Column(Text)
    human_analyst_targets_query = Column(Text)
    human_analyst_targets_organic = Column(JSONB)
    human_analyst_target_low_usd = Column(Numeric(20, 2))
    human_analyst_target_high_usd = Column(Numeric(20, 2))
    human_analyst_target_median_usd = Column(Numeric(20, 2))
    human_analyst_target_mean_usd = Column(Numeric(20, 2))
    human_analyst_target_count = Column(Integer)
    load_ts = Column(DateTime)


# Scenario proximity vs latest close (one row per symbol, latest analysis)
class VwAiScenarioProximity(Base):
    __tablename__ = "vw_ai_scenario_proximity"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True)
    symbol = Column(String(20))
    px_date_key = Column(Integer)
    price_date = Column(Date)
    close_px = Column(Numeric(20, 4))
    delta_bull_pct = Column(Numeric(12, 4))
    delta_base_pct = Column(Numeric(12, 4))
    delta_bear_pct = Column(Numeric(12, 4))
    nearest_scenario = Column(String(10))
    nearest_distance_pct = Column(Numeric(12, 4))


class VwStockBorrowRate(Base):
    __tablename__ = "vw_stock_borrow_rate"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    borrow_date = Column(Date, primary_key=True)
    symbol = Column(String(20), primary_key=True)
    borrow_rate_bp = Column(Numeric(12, 4))


class VwIvSurface(Base):
    __tablename__ = "vw_iv_surface"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    iv_date = Column(Date, primary_key=True)
    symbol = Column(String(20), primary_key=True)
    tenor_label = Column(String(10), primary_key=True)
    implied_vol = Column(Numeric(8, 4))


class VLatestScreener(Base):
    __tablename__ = "v_latest_screener"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    fact_id = Column(UUID(as_uuid=True))
    stock_key = Column(Integer)
    source_key = Column(Integer)
    style_key = Column(Integer)
    rank_value = Column(Integer)
    appearances = Column(Integer)
    screening_runid = Column(UUID(as_uuid=True))
    load_ts = Column(DateTime)


class VLatestScreenerValues(Base):
    __tablename__ = "v_latest_screener_values"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date)
    symbol = Column(String(20))
    company_name = Column(Text)
    sector = Column(Text)
    exchange = Column(Text)
    source = Column(String(50))
    style = Column(String(50))
    position_side = Column(String(10))
    source_weight = Column(Numeric(6, 4))
    style_weight = Column(Numeric(6, 4))
    rank_value = Column(Integer)
    screening_runid = Column(UUID(as_uuid=True))
    load_ts = Column(DateTime)


class VLatestScreenerConsensus(Base):
    __tablename__ = "v_latest_screener_consensus"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    full_date = Column(Date, primary_key=True)
    symbol = Column(String(20), primary_key=True)
    position_side = Column(String(10), primary_key=True)
    company_name = Column(Text)
    sector = Column(Text)
    exchange = Column(Text)
    primary_source = Column(String(50))
    primary_style = Column(String(50))

    rank_best = Column(Integer)
    rank_avg = Column(Numeric(10, 2))
    rank_median = Column(Numeric(10, 2))
    appearances = Column(Numeric(14, 4))
    styles_distinct = Column(Numeric(14, 4))
    sources_distinct = Column(Numeric(14, 4))
    styles = Column(ARRAY(String))
    sources = Column(ARRAY(String))
    runids = Column(ARRAY(UUID(as_uuid=True)))
    min_style_rank_pct = Column(Numeric(8, 6))
    long_score_raw = Column(Numeric(12, 4))
    short_score_raw = Column(Numeric(12, 4))
    net_score_raw = Column(Numeric(12, 4))
    families_count_long = Column(Integer)
    families_count_short = Column(Integer)
    screens_count_long = Column(Integer)
    screens_count_short = Column(Integer)
    tier12_hits_long = Column(Integer)
    tier12_hits_short = Column(Integer)
    breadth_bonus_long = Column(Numeric(6, 4))
    any_bonus_long = Column(Numeric(6, 4))
    family_streak_bonus_long = Column(Numeric(6, 4))
    any_bonus_short = Column(Numeric(6, 4))
    family_streak_bonus_short = Column(Numeric(6, 4))
    long_pct = Column(Numeric(6, 2))
    short_pct = Column(Numeric(6, 2))
    net_pct = Column(Numeric(6, 2))
    consensus_score = Column(Numeric(6, 2))


class MVScreenerChanges(Base):
    __tablename__ = "mv_screener_changes"
    __table_args__ = {"schema": "rankalpha"}

    change_date_key = Column(Integer)
    change_date = Column(Date)
    stock_key = Column(Integer)
    symbol = Column(String(20))
    company_name = Column(Text)
    sector = Column(Text)
    exchange = Column(Text)
    source_key = Column(Integer)
    source_name = Column(String(50))
    source_weight = Column(Numeric(6, 4))
    style_key = Column(Integer)
    style_name = Column(String(50))
    position_side = Column(String(10))
    style_weight = Column(Numeric(6, 4))
    change_weight = Column(Numeric(12, 6))
    change_type = Column(String(20))
    current_rank = Column(Integer)
    previous_rank = Column(Integer)
    rank_delta = Column(Integer)
    last_seen_date_key = Column(Integer)
    last_seen_date = Column(Date)
    days_since_last_seen = Column(Integer)
    absent_trading_days = Column(Integer)

    __mapper_args__ = {
        "primary_key": (
            change_date_key,
            stock_key,
            source_key,
            style_key,
            change_type,
        )
    }


class MVScreenerBreadth(Base):
    __tablename__ = "mv_screener_breadth"
    __table_args__ = {"schema": "rankalpha"}

    change_date = Column(Date, primary_key=True)
    style_key = Column(Integer, primary_key=True)
    style_name = Column(String(50))
    position_side = Column(String(10))
    entered_count = Column(Numeric(18, 6))
    reentered_count = Column(Numeric(18, 6))
    dropped_count = Column(Numeric(18, 6))
    eligible_count = Column(Numeric(18, 6))
    entered_pct = Column(Numeric(12, 6))
    dropped_pct = Column(Numeric(12, 6))
    net_pct = Column(Numeric(12, 6))
    entered_pct_avg_5d = Column(Numeric(12, 6))
    dropped_pct_avg_5d = Column(Numeric(12, 6))
    net_pct_avg_5d = Column(Numeric(12, 6))


class FactTechnicalIndicator(Base):
    __tablename__ = "fact_technical_indicator"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    indicator_code = Column(String(40), primary_key=True)
    value = Column(Numeric(20, 6))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


# ---------- Regime universe & intensity (US-only) --------------------
class MvUniverseRegimeUs(Base):
    __tablename__ = "mv_universe_regime_us"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    stock_key = Column(Integer, primary_key=True)
    symbol = Column(String(20))
    exchange = Column(Text)
    eligible = Column(Boolean)


class MvStyleIntensityUs(Base):
    __tablename__ = "mv_style_intensity_us"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    style_name = Column(String(50), primary_key=True)
    intensity_raw = Column(Numeric(12, 6))
    universe_count = Column(Integer)


class MvScreenerBreadthFlow(Base):
    __tablename__ = "mv_screener_breadth_flow"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    change_date = Column(Date, primary_key=True)
    date_key = Column(Integer)
    canonical_name = Column(String(50), primary_key=True)
    entered_count = Column(Numeric(20, 6))
    dropped_count = Column(Numeric(20, 6))
    continuers_count = Column(Numeric(20, 6))
    eligible_count = Column(Numeric(20, 6))
    entered_pct = Column(Numeric(12, 6))
    dropped_pct = Column(Numeric(12, 6))
    continuers_pct = Column(Numeric(12, 6))
    net_pct_us = Column(Numeric(12, 6))
    churn_pct = Column(Numeric(12, 6))


class FactStyleZUs(Base):
    __tablename__ = "fact_style_z_us"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    style_name = Column(String(50), primary_key=True)
    z_value = Column(Numeric(12, 6), nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactRegimeSeries(Base):
    __tablename__ = "fact_regime_series"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    risk_on_core = Column(Numeric(12, 6), nullable=False)
    risk_off_core = Column(Numeric(12, 6), nullable=False)
    regime_raw = Column(Numeric(12, 6), nullable=False)
    ema10 = Column(Numeric(12, 6), nullable=False)
    ema50 = Column(Numeric(12, 6), nullable=False)
    regime_label = Column(Text, nullable=False)
    regime_index = Column(Numeric(12, 6), nullable=False)
    participation = Column(Numeric(12, 6))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactRegimeEffectiveWeight(Base):
    __tablename__ = "fact_regime_effective_weight"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    canonical_name = Column(Text, primary_key=True)
    effective_weight = Column(Numeric(12, 6), nullable=False)
    g_factor = Column(Numeric(12, 6))
    base_weight = Column(Numeric(12, 6))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class VwRegimeSeries(Base):
    __tablename__ = "vw_regime_series"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    date_key = Column(Integer)
    risk_on_core = Column(Numeric(12, 6))
    risk_off_core = Column(Numeric(12, 6))
    regime_raw = Column(Numeric(12, 6))
    ema10 = Column(Numeric(12, 6))
    ema50 = Column(Numeric(12, 6))
    regime_label = Column(Text)
    regime_index = Column(Numeric(12, 6))
    participation = Column(Numeric(12, 6))


class FactVixTermStructure(Base):
    __tablename__ = "fact_vix_term_structure"
    __table_args__ = {"schema": "rankalpha"}

    underlying_symbol = Column(String(40), primary_key=True, server_default=text("'SPX/VIX'"))
    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    as_of_date = Column(Date, nullable=False)

    vix_1d = Column(Numeric(14, 6))
    vix_9d = Column(Numeric(14, 6))
    vix_1m = Column(Numeric(14, 6))
    vix_3m = Column(Numeric(14, 6))
    vix_6m = Column(Numeric(14, 6))
    vix_1y = Column(Numeric(14, 6))

    slope_1d_9d = Column(Numeric(14, 6))
    slope_9d_1m = Column(Numeric(14, 6))
    slope_1m_3m = Column(Numeric(14, 6))
    slope_3m_6m = Column(Numeric(14, 6))
    slope_6m_1y = Column(Numeric(14, 6))
    curve_slope = Column(Numeric(14, 6))

    ratio_1m_3m = Column(Numeric(14, 6))
    ratio_1m_6m = Column(Numeric(14, 6))
    ratio_3m_1y = Column(Numeric(14, 6))

    num_inversions = Column(SmallInteger)
    is_contango = Column(Boolean)
    is_contango_full = Column(Boolean)
    is_backwardation_front = Column(Boolean)
    is_backwardation_short = Column(Boolean)

    regime = Column(Text)
    risk_flag = Column(SmallInteger)

    load_ts = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


class VwVixTermStructureLatest(Base):
    __tablename__ = "vw_vix_term_structure_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    underlying_symbol = Column(String(40), primary_key=True)
    date_key = Column(Integer)
    as_of_date = Column(Date)

    vix_1d = Column(Numeric(14, 6))
    vix_9d = Column(Numeric(14, 6))
    vix_1m = Column(Numeric(14, 6))
    vix_3m = Column(Numeric(14, 6))
    vix_6m = Column(Numeric(14, 6))
    vix_1y = Column(Numeric(14, 6))

    slope_1d_9d = Column(Numeric(14, 6))
    slope_9d_1m = Column(Numeric(14, 6))
    slope_1m_3m = Column(Numeric(14, 6))
    slope_3m_6m = Column(Numeric(14, 6))
    slope_6m_1y = Column(Numeric(14, 6))
    curve_slope = Column(Numeric(14, 6))

    ratio_1m_3m = Column(Numeric(14, 6))
    ratio_1m_6m = Column(Numeric(14, 6))
    ratio_3m_1y = Column(Numeric(14, 6))

    num_inversions = Column(SmallInteger)
    is_contango = Column(Boolean)
    is_contango_full = Column(Boolean)
    is_backwardation_front = Column(Boolean)
    is_backwardation_short = Column(Boolean)

    regime = Column(Text)
    risk_flag = Column(SmallInteger)

    load_ts = Column(DateTime)
    updated_at = Column(DateTime)


# ── SPX/VIX VARIANCE RISK PREMIUM ──────────────────────────────────────
class FactSpxVixVrp(Base):
    __tablename__ = "fact_spx_vix_vrp"
    __table_args__ = {"schema": "rankalpha"}

    underlying_symbol = Column(String(40), primary_key=True, server_default=text("'SPX/VIX'"))
    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)

    spx_close = Column(Numeric(20, 4))
    vix_close = Column(Numeric(20, 4))

    rv_30d_var = Column(Numeric(18, 8))
    iv_30d_var = Column(Numeric(18, 8))
    vrp_30d = Column(Numeric(18, 8))

    vrp_p20 = Column(Numeric(18, 8))
    vrp_p80 = Column(Numeric(18, 8))
    vix_p33 = Column(Numeric(18, 8))
    vix_p66 = Column(Numeric(18, 8))

    vrp_state = Column(Text)
    vol_state = Column(Text)
    vrp_regime = Column(Text)

    load_ts = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), nullable=False)


class VwSpxVixVrpLatest(Base):
    __tablename__ = "vw_spx_vix_vrp_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    underlying_symbol = Column(String(40), primary_key=True)
    date_key = Column(Integer)
    as_of_date = Column(Date)

    spx_close = Column(Numeric(20, 4))
    vix_close = Column(Numeric(20, 4))

    rv_30d_var = Column(Numeric(18, 8))
    iv_30d_var = Column(Numeric(18, 8))
    vrp_30d = Column(Numeric(18, 8))

    vrp_p20 = Column(Numeric(18, 8))
    vrp_p80 = Column(Numeric(18, 8))
    vix_p33 = Column(Numeric(18, 8))
    vix_p66 = Column(Numeric(18, 8))

    vrp_state = Column(Text)
    vol_state = Column(Text)
    vrp_regime = Column(Text)

    load_ts = Column(DateTime)
    updated_at = Column(DateTime)


class FactRegimeRules(Base):
    __tablename__ = "fact_regime_rules"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    mb = Column(Numeric(14, 6))
    bb = Column(Numeric(14, 6))
    mri = Column(Numeric(14, 6))
    db = Column(Numeric(14, 6))
    tt = Column(Numeric(14, 6))
    mrp = Column(Numeric(14, 6))
    rop = Column(Numeric(14, 6))
    dt = Column(Numeric(14, 6))
    ps = Column(Numeric(14, 6))
    tb = Column(Numeric(14, 6))
    rs = Column(Numeric(14, 6))
    rs_smooth = Column(Numeric(14, 6))
    label = Column(Text, nullable=False)
    tags = Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    config_version = Column(Text, nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactRegimeMarketStructure(Base):
    __tablename__ = "fact_regime_market_structure"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    trend_raw = Column(Numeric(14, 6))
    rv20_ann = Column(Numeric(14, 6))
    corr_pca1_share = Column(Numeric(14, 6))
    disp_cs_mad = Column(Numeric(14, 6))
    trend_z = Column(Numeric(14, 6))
    rv20_z = Column(Numeric(14, 6))
    corr_z = Column(Numeric(14, 6))
    disp_z = Column(Numeric(14, 6))
    label = Column(Text, nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactHyStress(Base):
    __tablename__ = "fact_hy_stress"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    benchmark_key = Column(
        Integer, ForeignKey("rankalpha.dim_benchmark.benchmark_key"), primary_key=True
    )
    hy_stress_raw = Column(Numeric(14, 6))
    hy_stress_ma = Column(Numeric(14, 6))
    hy_stress_z = Column(Numeric(14, 6))
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class VwHyStress(Base):
    __tablename__ = "vw_hy_stress"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    benchmark_key = Column(Integer, primary_key=True)
    date_key = Column(Integer)
    benchmark_name = Column(Text)
    hy_stress_raw = Column(Numeric(14, 6))
    hy_stress_ma = Column(Numeric(14, 6))
    hy_stress_z = Column(Numeric(14, 6))
    load_ts = Column(DateTime)


class VwHyStressLatest(Base):
    __tablename__ = "vw_hy_stress_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    benchmark_key = Column(Integer, primary_key=True)
    date_key = Column(Integer)
    benchmark_name = Column(Text)
    hy_stress_raw = Column(Numeric(14, 6))
    hy_stress_ma = Column(Numeric(14, 6))
    hy_stress_z = Column(Numeric(14, 6))
    load_ts = Column(DateTime)


class FactFraOis(Base):
    __tablename__ = "fact_fra_ois"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    start_months = Column(Integer, primary_key=True)
    end_months = Column(Integer, primary_key=True)
    fra_source = Column(String(4), primary_key=True)
    fra_rate = Column(Numeric(10, 6))
    ois_forward = Column(Numeric(10, 6))
    spread_bp = Column(Numeric(12, 4))
    fra_ois_z = Column(Numeric(12, 6))
    load_ts = Column(DateTime)


class VwFraOisLatest(Base):
    __tablename__ = "vw_fra_ois_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    start_months = Column(Integer, primary_key=True)
    end_months = Column(Integer, primary_key=True)
    fra_source = Column(String(4), primary_key=True)
    fra_rate = Column(Numeric(10, 6))
    ois_forward = Column(Numeric(10, 6))
    spread_bp = Column(Numeric(12, 4))
    fra_ois_z = Column(Numeric(12, 6))


class VwRegimeMarketStructure(Base):
    __tablename__ = "vw_regime_market_structure"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    date_key = Column(Integer)
    trend_raw = Column(Numeric(14, 6))
    rv20_ann = Column(Numeric(14, 6))
    corr_pca1_share = Column(Numeric(14, 6))
    disp_cs_mad = Column(Numeric(14, 6))
    trend_z = Column(Numeric(14, 6))
    rv20_z = Column(Numeric(14, 6))
    corr_z = Column(Numeric(14, 6))
    disp_z = Column(Numeric(14, 6))
    label = Column(Text)


class VwBreadthSignal(Base):
    __tablename__ = "vw_breadth_signals"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    series_code = Column(Text, primary_key=True)
    series_name = Column(Text)
    category = Column(Text)
    frequency = Column(Text)
    units = Column(Text)
    value = Column(Numeric(20, 6))
    source_key = Column(Integer)
    load_ts = Column(DateTime)


class MvRankRegimeDaily(Base):
    __tablename__ = "mv_rank_regime_daily"
    __table_args__ = {"schema": "rankalpha"}

    as_of_date = Column(Date, primary_key=True)
    universe_size = Column(Integer)
    momentum_breadth = Column(Numeric(12, 6))
    value_breadth = Column(Numeric(12, 6))
    breadth_spread = Column(Numeric(12, 6))
    val_to_mom_raw = Column(Numeric(12, 6))
    mom_to_val_raw = Column(Numeric(12, 6))
    top_bucket_turnover = Column(Numeric(12, 6))
    val_to_mom_norm = Column(Numeric(12, 6))
    mom_to_val_norm = Column(Numeric(12, 6))
    fri_z = Column(Numeric(12, 6))
    fri_log = Column(Numeric(12, 6))
    tenure_m_median_days = Column(Numeric(12, 6))
    tenure_v_median_days = Column(Numeric(12, 6))
    hazard_m = Column(Numeric(12, 6))
    hazard_v = Column(Numeric(12, 6))
    factor_skew_mean = Column(Numeric(12, 6))
    dispersion_m_std = Column(Numeric(12, 6))
    dispersion_v_std = Column(Numeric(12, 6))
    regime_label = Column(Text)
    regime_confidence = Column(Numeric(12, 6))


class RegimeRulesConfig(Base):
    __tablename__ = "regime_rules_config"
    __table_args__ = {"schema": "rankalpha"}

    config_key = Column(String(50), primary_key=True)
    z_window_days = Column(Integer, nullable=False, server_default=text("252"))
    rs_window_days = Column(Integer, nullable=False, server_default=text("126"))
    rs_weight_mb = Column(Numeric(8, 4), nullable=False, server_default=text("1.0"))
    rs_weight_bb = Column(Numeric(8, 4), nullable=False, server_default=text("-0.9"))
    rs_weight_mri = Column(Numeric(8, 4), nullable=False, server_default=text("-0.4"))
    rs_weight_db = Column(Numeric(8, 4), nullable=False, server_default=text("-0.5"))
    rs_trend_threshold = Column(Numeric(8, 4), nullable=False, server_default=text("0.5"))
    rs_riskoff_threshold = Column(Numeric(8, 4), nullable=False, server_default=text("-0.5"))
    defensive_pct_threshold = Column(Numeric(8, 4), nullable=False, server_default=text("0.8"))
    mania_pct_threshold = Column(Numeric(8, 4), nullable=False, server_default=text("0.9"))
    ps_veto_threshold = Column(Numeric(8, 4), nullable=False, server_default=text("0.0"))
    hysteresis_days = Column(Integer, nullable=False, server_default=text("3"))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(DateTime, nullable=False, server_default=func.now())


class VwLatestTechnicals(Base):
    __tablename__ = "vw_latest_technicals"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date, primary_key=True)
    symbol = Column(String(20), primary_key=True)
    company_name = Column(Text)
    sma20 = Column(Numeric(20, 6))
    sma50 = Column(Numeric(20, 6))
    sma200 = Column(Numeric(20, 6))
    ema12 = Column(Numeric(20, 6))
    ema26 = Column(Numeric(20, 6))
    rsi14 = Column(Numeric(20, 6))
    atr14 = Column(Numeric(20, 6))
    bb_upper = Column(Numeric(20, 6))
    bb_middle = Column(Numeric(20, 6))
    bb_lower = Column(Numeric(20, 6))
    macd = Column(Numeric(20, 6))
    macd_signal = Column(Numeric(20, 6))
    macd_hist = Column(Numeric(20, 6))
    ret_5d = Column(Numeric(20, 6))
    ret_20d = Column(Numeric(20, 6))
    ret_60d = Column(Numeric(20, 6))
    ret_120d = Column(Numeric(20, 6))
    vol_z20 = Column(Numeric(20, 6))
    dist_52w_high = Column(Numeric(20, 6))


class VwFinFundamentals(Base):
    __tablename__ = "vw_fin_fundamentals"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    company_name = Column(Text)
    metric_code = Column(String(60))
    metric_name = Column(Text)
    fiscal_year = Column(SmallInteger)
    fiscal_period = Column(String(3))
    metric_value = Column(Numeric(20, 4))
    source_name = Column(String(50))
    load_ts = Column(DateTime)


class VwPortfolioPerformance(Base):
    __tablename__ = "vw_portfolio_performance"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date)
    portfolio_id = Column(UUID(as_uuid=True))
    portfolio_name = Column(String(50))
    nav_base_ccy = Column(Numeric(20, 4))
    nav_prev = Column(Numeric(20, 4))
    daily_return = Column(Numeric(12, 6))


class VwPortfolioSnapshot(Base):
    __tablename__ = "vw_portfolio_snapshot"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    portfolio_id = Column(UUID(as_uuid=True), primary_key=True)
    portfolio_name = Column(String(50))
    symbol = Column(String(20))
    company_name = Column(Text)
    quantity = Column(Numeric(20, 4))
    avg_cost = Column(Numeric(20, 4))
    last_close = Column(Numeric(20, 4))
    market_value = Column(Numeric(20, 4))
    nav = Column(Numeric(20, 4))
    weight_pct = Column(Numeric(8, 6))
    last_update_ts = Column(DateTime)


class VwPortfolioTopContrib(Base):
    __tablename__ = "vw_portfolio_top_contrib"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    portfolio_id = Column(UUID(as_uuid=True), primary_key=True)
    portfolio_name = Column(String(50))
    symbol = Column(String(20))
    company_name = Column(Text)
    quantity = Column(Numeric(20, 4))
    close_px = Column(Numeric(20, 4))
    unreal_pnl = Column(Numeric(20, 4))


class VwPortfolioTurnover(Base):
    __tablename__ = "vw_portfolio_turnover"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    full_date = Column(Date, primary_key=True)
    portfolio_id = Column(UUID(as_uuid=True))
    portfolio_name = Column(String(50))
    notional_traded = Column(Numeric(20, 4))
    nav_base_ccy = Column(Numeric(20, 4))
    turnover_pct = Column(Numeric(10, 6))


class VwRiskDashboard(Base):
    __tablename__ = "vw_risk_dashboard"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    full_date = Column(Date)
    portfolio_name = Column(String(50))
    var_95_1d = Column(Numeric(20, 4))
    beta_spx = Column(Numeric(12, 6))
    liq_days = Column(Numeric(12, 6))


class VwScoreHistory(Base):
    __tablename__ = "vw_score_history"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    score_type_name = Column(String(50))
    score = Column(Numeric(10, 2))
    source_name = Column(String(50))
    load_ts = Column(DateTime)


class VwScreenerRank(Base):
    __tablename__ = "vw_screener_rank"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    style_name = Column(String(50))
    rank_value = Column(Integer)
    screening_runid = Column(UUID(as_uuid=True))
    load_ts = Column(DateTime)
    source_name = Column(String(50))


class VwStockStyleScores(Base):
    __tablename__ = "vw_stock_style_scores"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    date_key = Column(Integer, primary_key=True)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    style_name = Column(String(50))
    score_value = Column(Numeric(5, 2))
    rank_value = Column(Integer)
    score_runid = Column(UUID(as_uuid=True))
    load_ts = Column(DateTime)


class MvLatestGrades(Base):
    __tablename__ = "mv_latest_grades"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date)
    symbol = Column(String(20), primary_key=True)
    company_name = Column(Text)
    sector = Column(Text)
    exchange = Column(Text)
    momentum_score = Column(Numeric(10, 2))
    value_score = Column(Numeric(10, 2))
    sentiment_score = Column(Numeric(10, 2))
    avg_score = Column(Numeric(10, 2))
    grade = Column(String(2))
    grade_order = Column(Integer)


class MvSentimentProxy(Base):
    __tablename__ = "mv_sentiment_proxy"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    symbol = Column(String(20), primary_key=True)
    px_date_key = Column(Integer)
    expected_return = Column(Numeric(14, 6))
    sentiment_proxy_score = Column(Numeric(14, 2))


# ---------- AI SCENARIO PROXIMITY (materialized) --------------------
class MvAiScenarioProximity(Base):
    __tablename__ = "mv_ai_scenario_proximity"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True)
    symbol = Column(String(20))
    px_date_key = Column(Integer)
    price_date = Column(Date)
    close_px = Column(Numeric(20, 4))
    delta_bull_pct = Column(Numeric(12, 4))
    delta_base_pct = Column(Numeric(12, 4))
    delta_bear_pct = Column(Numeric(12, 4))
    nearest_scenario = Column(String(10))
    nearest_distance_pct = Column(Numeric(12, 4))


class MvAiAnalysisLatestList(Base):
    __tablename__ = "mv_ai_analysis_latest_list"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    analysis_id = Column(UUID(as_uuid=True), primary_key=True)
    date_key = Column(Integer)
    as_of_date = Column(Date)
    symbol = Column(String(20))
    company_name = Column(Text)
    asset_type = Column(String(20))
    overall_rating = Column(String(20))
    confidence = Column(String(20))
    commentary = Column(Text)
    bull_price_target = Column(Numeric(20, 4))
    bull_probability_pct = Column(Numeric(12, 4))
    base_price_target = Column(Numeric(20, 4))
    base_probability_pct = Column(Numeric(12, 4))
    bear_price_target = Column(Numeric(20, 4))
    bear_probability_pct = Column(Numeric(12, 4))
    price_date = Column(Date)
    close_px = Column(Numeric(20, 4))
    delta_bull_pct = Column(Numeric(12, 4))
    delta_base_pct = Column(Numeric(12, 4))
    delta_bear_pct = Column(Numeric(12, 4))
    nearest_scenario = Column(String(10))
    nearest_distance_pct = Column(Numeric(12, 4))
    load_ts = Column(DateTime)


# ---------- PRICE HISTORY VIEWS (read‑only) ---------------------------
class VwStockPriceHistory(Base):
    __tablename__ = "vw_stock_price_history"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    symbol = Column(String(20), primary_key=True)
    company_name = Column(Text)
    price_date = Column(Date, primary_key=True)
    open_px = Column(Numeric(20, 4))
    high_px = Column(Numeric(20, 4))
    low_px = Column(Numeric(20, 4))
    close_px = Column(Numeric(20, 4))
    adj_close_px = Column(Numeric(20, 4))
    volume = Column(BigInteger)


class VwLatestAdjClose(Base):
    __tablename__ = "vw_latest_adj_close"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    symbol = Column(String(20), primary_key=True)
    company_name = Column(Text)
    price_date = Column(Date)
    close_px = Column(Numeric(20, 4))
    adj_close_px = Column(Numeric(20, 4))


# ---------- UNIVERSE ELIGIBILITY (materialized) ----------------------
class MvUniverseEligible(Base):
    __tablename__ = "mv_universe_eligible"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    symbol = Column(String(20), primary_key=True)
    stock_key = Column(Integer)
    exchange = Column(Text)
    asset_type = Column(String(20))
    latest_adj_close = Column(Numeric(20, 4))
    med_addv_30_usd = Column(Numeric(20, 4))
    med_vol_30_sh = Column(Numeric(20, 4))
    bars_22 = Column(Integer)
    eligible = Column(Boolean)


# ---------- NEWSWIRE MATERIAL EVENTS (read‑only views + facts) ------
class MvLatestMaterialNews(Base):
    __tablename__ = "mv_latest_material_news"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    event_id = Column(UUID(as_uuid=True), primary_key=True)
    cluster_id = Column(UUID(as_uuid=True))
    first_seen_ts = Column(DateTime)
    decided_at = Column(DateTime)
    materiality_score = Column(Numeric(5, 2))
    event_type = Column(Text)
    direction = Column(String(20))
    timescale = Column(String(20))
    summary = Column(Text)
    title = Column(Text)
    url = Column(Text)
    source_domain = Column(Text)
    symbol = Column(String(20))
    company_name = Column(Text)
    role = Column(Text)
    confidence = Column(Numeric(5, 2))


# ---------- Screener presence & scores -------------------------------
class FactScreenerPresence(Base):
    __tablename__ = "fact_screener_presence"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    style_key = Column(Integer, ForeignKey("rankalpha.dim_style.style_key"), primary_key=True)
    present_today = Column(Boolean, nullable=False)
    consec_days_family = Column(SmallInteger, nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class FactScreenerPresenceSide(Base):
    __tablename__ = "fact_screener_presence_side"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), primary_key=True)
    position_side = Column(String(10), primary_key=True)
    present_any_side = Column(Boolean, nullable=False)
    consec_days_any_side = Column(SmallInteger, nullable=False)
    load_ts = Column(DateTime, server_default=func.now(), nullable=False)


class MVScreenerScoresLatest(Base):
    __tablename__ = "mv_screener_scores_latest"
    __table_args__ = {"schema": "rankalpha"}

    as_of_date = Column(Date, primary_key=True)
    symbol = Column(String(20), primary_key=True)

    long_score_raw = Column(Numeric(12, 4))
    short_score_raw = Column(Numeric(12, 4))
    net_score_raw = Column(Numeric(12, 4))

    families_count_long = Column(Integer)
    screens_count_long = Column(Integer)
    tier12_hits_long = Column(Integer)
    families_count_short = Column(Integer)
    screens_count_short = Column(Integer)
    tier12_hits_short = Column(Integer)

    breadth_bonus_long = Column(Numeric(12, 6))
    any_bonus_long = Column(Numeric(12, 6))
    family_streak_bonus_long = Column(Numeric(12, 6))
    any_bonus_short = Column(Numeric(12, 6))
    family_streak_bonus_short = Column(Numeric(12, 6))

    long_pct = Column(Numeric(6, 2))
    short_pct = Column(Numeric(6, 2))
    net_pct = Column(Numeric(6, 2))


class VwNewsBySymbol(Base):
    __tablename__ = "vw_news_by_symbol"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    # Composite PK to avoid collapsing multiple events per symbol in SQLAlchemy's identity map
    symbol = Column(String(20), primary_key=True)
    company_name = Column(Text)
    event_id = Column(UUID(as_uuid=True), primary_key=True)
    first_seen_ts = Column(DateTime)
    decided_at = Column(DateTime)
    materiality_score = Column(Numeric(5, 2))
    event_type = Column(Text)
    direction = Column(String(20))
    timescale = Column(String(20))
    summary = Column(Text)
    title = Column(Text)
    url = Column(Text)
    source_domain = Column(Text)
    role = Column(Text)
    confidence = Column(Numeric(5, 2))


class NewsCursor(Base):
    __tablename__ = "news_cursor"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    source_name = Column(String(40), primary_key=True)
    last_seen = Column(DateTime, nullable=False)
    updated_at = Column(DateTime)


class NewsSuggestion(Base):
    __tablename__ = "news_suggestion"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','accepted','rejected','merged')",
            name="news_suggestion_status_check",
        ),
        {"schema": "rankalpha"},
    )
    __mapper_args__ = {"eager_defaults": False}

    suggestion_id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True))
    source_name = Column(Text, nullable=False)
    submitter_reference = Column(Text)
    idempotency_key = Column(Text)
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    status_reason = Column(Text)
    url = Column(Text, nullable=False)
    url_canonical = Column(Text, nullable=False)
    url_hash = Column(String(64), nullable=False)
    title = Column(Text, nullable=False)
    snippet = Column(Text)
    body_text = Column(Text)
    body_bytes = Column(Integer)
    body_fingerprint = Column(BigInteger)
    text_fingerprint = Column(BigInteger)
    published_at = Column(DateTime(timezone=True))
    language = Column(String(20))
    country = Column(String(4))
    raw_payload = Column(JSONB)
    cluster_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.dim_news_cluster.cluster_id", ondelete="SET NULL")
    )
    event_id = Column(
        UUID(as_uuid=True), ForeignKey("rankalpha.fact_news_event.event_id", ondelete="SET NULL")
    )

    queue_entries = relationship(
        "NewsIngestQueue",
        back_populates="suggestion",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class NewsIngestQueue(Base):
    __tablename__ = "news_ingest_queue"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','in_progress','done','failed')",
            name="news_ingest_queue_status_check",
        ),
        {"schema": "rankalpha"},
    )
    __mapper_args__ = {"eager_defaults": False}

    queue_id = Column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    suggestion_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rankalpha.news_suggestion.suggestion_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(20), nullable=False, server_default=text("'pending'"))
    priority = Column(Integer, nullable=False, server_default=text("0"))
    enqueue_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    run_after_ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_ts = Column(DateTime(timezone=True))
    completed_ts = Column(DateTime(timezone=True))
    attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_error = Column(Text)
    locked_by = Column(Text)
    locked_ts = Column(DateTime(timezone=True))

    suggestion = relationship("NewsSuggestion", back_populates="queue_entries")


class SentimentAnalysisQueue(Base):
    __tablename__ = "sentiment_analysis_queue"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    queue_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stock_key = Column(Integer, ForeignKey("rankalpha.dim_stock.stock_key"), nullable=False)
    symbol = Column(String(20), nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("rankalpha.fact_news_event.event_id"))
    title = Column(Text)
    url = Column(Text)
    priority = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending")
    enqueue_ts = Column(DateTime, server_default=func.now(), nullable=False)
    run_after_ts = Column(DateTime, server_default=func.now(), nullable=False)
    run_after_date = Column(Date, nullable=True)
    started_ts = Column(DateTime)
    completed_ts = Column(DateTime)
    attempts = Column(Integer, nullable=False, default=0)
    source = Column(Text)
    force_run = Column(Boolean, nullable=False, server_default=text("false"))
    raw_id = Column(UUID(as_uuid=True), ForeignKey("rankalpha.fact_news_raw.raw_id"), nullable=True)


class FactNowcastSnapshot(Base):
    __tablename__ = "fact_nowcast_snapshot"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    model_version = Column(Text, primary_key=True)

    overall_risk_off_score = Column(Numeric(8, 3))
    nowcast_label = Column(Text)
    confidence = Column(Numeric(8, 4))
    coverage = Column(Numeric(8, 4))

    tier1_score = Column(Numeric(8, 3))
    tier2_score = Column(Numeric(8, 3))
    tier3_score = Column(Numeric(8, 3))

    cross_asset_stress_score = Column(Numeric(8, 3))
    cross_asset_label = Column(Text)

    map_liquidity_ease = Column(Numeric(8, 3))
    map_stress_score = Column(Numeric(8, 3))

    spx_tlt_corr60 = Column(Numeric(12, 6))
    spx_ret20 = Column(Numeric(12, 6))
    tlt_ret20 = Column(Numeric(12, 6))
    booster_applied = Column(Boolean, nullable=False)
    booster_amount = Column(Numeric(8, 3))

    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    date = relationship("DimDate")


class FactNowcastPillarSnapshot(Base):
    __tablename__ = "fact_nowcast_pillar_snapshot"
    __table_args__ = {"schema": "rankalpha"}

    date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"), primary_key=True)
    model_version = Column(Text, primary_key=True)
    pillar_key = Column(Text, primary_key=True)

    tier = Column(SmallInteger, nullable=False)
    score = Column(Numeric(8, 3))
    data_date_key = Column(Integer, ForeignKey("rankalpha.dim_date.date_key"))
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    date = relationship("DimDate", foreign_keys=[date_key])
    data_date = relationship("DimDate", foreign_keys=[data_date_key])


class VwNowcastSnapshotSeriesWithDeltas(Base):
    __tablename__ = "vw_nowcast_snapshot_series_with_deltas"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    as_of_date = Column(Date)
    date_key = Column(Integer, primary_key=True)
    model_version = Column(Text, primary_key=True)

    overall_risk_off_score = Column(Numeric(8, 3))
    nowcast_label = Column(Text)
    confidence = Column(Numeric(8, 4))
    coverage = Column(Numeric(8, 4))
    tier1_score = Column(Numeric(8, 3))
    tier2_score = Column(Numeric(8, 3))
    tier3_score = Column(Numeric(8, 3))
    cross_asset_stress_score = Column(Numeric(8, 3))
    cross_asset_label = Column(Text)
    map_liquidity_ease = Column(Numeric(8, 3))
    map_stress_score = Column(Numeric(8, 3))
    spx_tlt_corr60 = Column(Numeric(12, 6))
    spx_ret20 = Column(Numeric(12, 6))
    tlt_ret20 = Column(Numeric(12, 6))
    booster_applied = Column(Boolean)
    booster_amount = Column(Numeric(8, 3))
    computed_at = Column(DateTime(timezone=True))

    delta_1d = Column(Numeric(12, 6))
    delta_5d = Column(Numeric(12, 6))
    label_1d_ago = Column(Text)
    label_5d_ago = Column(Text)


class VwNowcastSnapshotLatest(Base):
    __tablename__ = "vw_nowcast_snapshot_latest"
    __table_args__ = {"schema": "rankalpha"}
    __mapper_args__ = {"eager_defaults": False}

    model_version = Column(Text, primary_key=True)
    as_of_date = Column(Date)
    date_key = Column(Integer)

    overall_risk_off_score = Column(Numeric(8, 3))
    nowcast_label = Column(Text)
    confidence = Column(Numeric(8, 4))
    coverage = Column(Numeric(8, 4))
    tier1_score = Column(Numeric(8, 3))
    tier2_score = Column(Numeric(8, 3))
    tier3_score = Column(Numeric(8, 3))
    cross_asset_stress_score = Column(Numeric(8, 3))
    cross_asset_label = Column(Text)
    map_liquidity_ease = Column(Numeric(8, 3))
    map_stress_score = Column(Numeric(8, 3))
    spx_tlt_corr60 = Column(Numeric(12, 6))
    spx_ret20 = Column(Numeric(12, 6))
    tlt_ret20 = Column(Numeric(12, 6))
    booster_applied = Column(Boolean)
    booster_amount = Column(Numeric(8, 3))
    computed_at = Column(DateTime(timezone=True))

    delta_1d = Column(Numeric(12, 6))
    delta_5d = Column(Numeric(12, 6))
    label_1d_ago = Column(Text)
    label_5d_ago = Column(Text)
