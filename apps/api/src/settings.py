from __future__ import annotations

from typing import List, Optional

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

# Shared base (db/openai/redis/logging), service-specific settings live here
from apps.common.src.settings_base import ENV_DIR, BaseAppSettings


class Settings(BaseAppSettings):
    """API-specific Settings: read only env/{ENV}/api.env.

    This avoids HOST from ingestion/sentiment env files clobbering the API DB host
    when running locally without Docker.
    """

    # Prod hardening toggles
    # If true, dynamically mount /internal/* auto-generated CRUD routes.
    api_internal_crud_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "API_INTERNAL_CRUD_ENABLED",
            "API_API_INTERNAL_CRUD_ENABLED",
        ),
    )
    # If true, /internal/* routes appear in OpenAPI schema (otherwise hidden).
    api_internal_crud_include_in_schema: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "API_INTERNAL_CRUD_INCLUDE_IN_SCHEMA",
            "API_INTERNAL_CRUD_SCHEMA_ENABLED",
        ),
    )
    # Expose Swagger docs at docs_url (defaults to "/").
    api_docs_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("API_DOCS_ENABLED", "API_API_DOCS_ENABLED"),
    )
    # Expose OpenAPI schema at /openapi.json.
    api_openapi_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("API_OPENAPI_ENABLED", "API_API_OPENAPI_ENABLED"),
    )
    # Enable the Redis-backed HTTP cache middleware.
    http_cache_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("HTTP_CACHE_ENABLED", "API_HTTP_CACHE_ENABLED"),
    )
    # Add baseline security headers to all responses.
    security_headers_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "SECURITY_HEADERS_ENABLED",
            "API_SECURITY_HEADERS_ENABLED",
        ),
    )
    # If true, the API exposes only GET routes (no POST/PUT/DELETE) for auto-generated CRUD.
    api_read_only: bool = Field(
        default=False,
        validation_alias=AliasChoices("API_READ_ONLY", "API_API_READ_ONLY"),
    )
    # Optional Bearer token for privileged admin/service access.
    # Note: admin routes are never "open" — they require either an admin-role JWT,
    # ADMIN_BEARER_TOKEN, or AUTH_SERVICE_TOKEN (if configured).
    admin_bearer_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_BEARER_TOKEN", "API_ADMIN_BEARER_TOKEN"),
    )
    # Required Bearer token for trading ingestion routes; if unset, trading routes are disabled.
    trading_bearer_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TRADING_BEARER_TOKEN", "API_TRADING_BEARER_TOKEN"),
    )
    # NextAuth integration (frontend-issued JWT bearer authentication)
    nextauth_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NEXTAUTH_SECRET", "API_NEXTAUTH_SECRET"),
    )
    nextauth_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NEXTAUTH_ISSUER", "API_NEXTAUTH_ISSUER"),
    )
    auth_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SERVICE_TOKEN", "API_AUTH_SERVICE_TOKEN"),
    )
    auth_default_role: str = Field(
        default="viewer",
        validation_alias=AliasChoices("AUTH_DEFAULT_ROLE", "API_AUTH_DEFAULT_ROLE"),
    )

    # Broker service integration (FastAPI -> Broker -> IBKR)
    broker_service_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("BROKER_SERVICE_URL", "API_BROKER_SERVICE_URL"),
    )
    broker_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "BROKER_SERVICE_TOKEN",
            "API_BROKER_SERVICE_TOKEN",
        ),
    )
    broker_service_timeout_seconds: int = Field(
        4,
        validation_alias=AliasChoices(
            "BROKER_SERVICE_TIMEOUT_SECONDS", "API_BROKER_SERVICE_TIMEOUT_SECONDS"
        ),
    )
    broker_live_down_ttl_seconds: int = Field(
        30,
        ge=0,
        validation_alias=AliasChoices(
            "BROKER_LIVE_DOWN_TTL_SECONDS",
            "API_BROKER_LIVE_DOWN_TTL_SECONDS",
        ),
    )
    broker_price_cache_seconds: int = Field(
        90,
        validation_alias=AliasChoices(
            "BROKER_PRICE_CACHE_SECONDS", "API_BROKER_PRICE_CACHE_SECONDS"
        ),
    )
    # Cap background live-price prefetch tasks to avoid unbounded memory growth.
    prices_live_prefetch_max_tasks: int = Field(
        250,
        ge=0,
        validation_alias=AliasChoices(
            "PRICES_LIVE_PREFETCH_MAX_TASKS",
            "API_PRICES_LIVE_PREFETCH_MAX_TASKS",
        ),
    )

    # Endpoint-specific DoS guards
    ai_preview_max_symbols: int = Field(
        200,
        ge=1,
        le=2000,
        validation_alias=AliasChoices("AI_PREVIEW_MAX_SYMBOLS", "API_AI_PREVIEW_MAX_SYMBOLS"),
    )
    backtest_max_range_days: int = Field(
        365 * 5,
        ge=1,
        le=365 * 50,
        validation_alias=AliasChoices(
            "BACKTEST_MAX_RANGE_DAYS",
            "API_BACKTEST_MAX_RANGE_DAYS",
        ),
    )
    backtest_max_rebalance_points: int = Field(
        1000,
        ge=10,
        le=100_000,
        validation_alias=AliasChoices(
            "BACKTEST_MAX_REBALANCE_POINTS",
            "API_BACKTEST_MAX_REBALANCE_POINTS",
        ),
    )

    # HTTP cache TTLs (seconds)
    cache_ttl_default: Optional[int] = None
    cache_ttl_rankings: Optional[int] = None
    cache_ttl_stock_detail: Optional[int] = None
    cache_ttl_top_performers: Optional[int] = None
    cache_ttl_sectors: Optional[int] = None
    cache_ttl_prices_history: Optional[int] = None
    cache_ttl_prices_latest: Optional[int] = None
    cache_ttl_screener_changes: Optional[int] = None
    cache_ttl_screener_breadth: Optional[int] = None
    # Macro / regime dashboard TTLs (seconds)
    cache_ttl_macro: Optional[int] = None
    cache_ttl_benchmarks: Optional[int] = None
    cache_ttl_breadth: Optional[int] = None
    cache_ttl_fra_ois: Optional[int] = None
    cache_ttl_hy_stress: Optional[int] = None
    cache_ttl_vol_regime: Optional[int] = None
    cache_ttl_rates: Optional[int] = None
    cache_ttl_fx: Optional[int] = None
    cache_ttl_money_flow: Optional[int] = None
    cache_ttl_technicals: Optional[int] = None
    cache_ttl_fundamentals: Optional[int] = None

    # CORS
    cors_origins: Optional[List[str]] = None
    cors_allow_credentials: bool = True
    cors_allow_methods: Optional[List[str]] = None
    cors_allow_headers: Optional[List[str]] = None

    # Logging / observability
    api_async_logging_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "API_ASYNC_LOGGING_ENABLED",
            "ASYNC_LOGGING_ENABLED",
        ),
    )
    api_async_logging_queue_maxsize: int = Field(
        default=10000,
        ge=0,
        validation_alias=AliasChoices(
            "API_ASYNC_LOGGING_QUEUE_MAXSIZE",
            "ASYNC_LOGGING_QUEUE_MAXSIZE",
        ),
    )

    # For the API service the container's port environment variable is used for the
    # HTTP listener; the DB port comes only from DB_PORT_CONTAINER (Compose override)
    # or DB_PORT (env file).
    port: int = Field(
        validation_alias=AliasChoices("DB_PORT_CONTAINER", "DB_PORT"),
    )
    # HTTP listen port for uvicorn (not used in DB connections)
    api_listen_port: int | None = Field(default=None, alias="API_PORT")

    # Pipeline health configuration
    # Max business days considered "healthy" for sentiment recency in /pipeline/health
    pipeline_sentiment_healthy_max_bdays: int = Field(
        7,
        validation_alias=AliasChoices(
            "PIPELINE_SENTIMENT_HEALTHY_MAX_BDAYS", "API_PIPELINE_SENTIMENT_HEALTHY_MAX_BDAYS"
        ),
    )
    # Ingestion thresholds (business days) for /pipeline/health
    pipeline_ingestion_healthy_max_bdays: int = Field(
        1,
        validation_alias=AliasChoices(
            "PIPELINE_INGESTION_HEALTHY_MAX_BDAYS", "API_PIPELINE_INGESTION_HEALTHY_MAX_BDAYS"
        ),
    )
    pipeline_ingestion_warning_max_bdays: int = Field(
        3,
        validation_alias=AliasChoices(
            "PIPELINE_INGESTION_WARNING_MAX_BDAYS", "API_PIPELINE_INGESTION_WARNING_MAX_BDAYS"
        ),
    )
    # Scorer healthy threshold (business days)
    pipeline_scorer_healthy_max_bdays: int = Field(
        1,
        validation_alias=AliasChoices(
            "PIPELINE_SCORER_HEALTHY_MAX_BDAYS", "API_PIPELINE_SCORER_HEALTHY_MAX_BDAYS"
        ),
    )

    # Price / AI cache admin warmers
    price_history_cache_ttl_seconds: Optional[int] = None
    price_history_cache_head_items: int = Field(
        800,
        ge=50,
        le=5000,
        validation_alias=AliasChoices(
            "PRICE_HISTORY_CACHE_HEAD_ITEMS",
            "API_PRICE_HISTORY_CACHE_HEAD_ITEMS",
        ),
    )
    price_history_cache_refresh_chunk_size: Optional[int] = None
    price_cache_refresh_timeout_seconds: Optional[int] = None
    ai_analysis_cache_ttl_seconds: Optional[int] = None
    ai_analysis_cache_refresh_chunk_size: Optional[int] = None
    ai_analysis_cache_url: Optional[str] = None
    ai_analysis_cache_token: Optional[str] = None
    ai_analysis_cache_timeout_seconds: Optional[int] = None

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env", ENV_DIR / "api.env"],
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )
