from __future__ import annotations

from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from apps.common.src.settings_base import ENV, ENV_DIR, ROOT, BaseAppSettings


class Settings(BaseAppSettings):
    """Ingestion service settings (parquet sync, factor capture, cache warmers)."""

    # Ingestion toggles
    ingestion_inactive_after_missing_bdays: Optional[int] = 5
    # Stale price warning threshold (business days behind peer anchor date).
    # This is intentionally smaller than inactive detection so we can alert early.
    ingestion_stale_after_missing_bdays: Optional[int] = 1
    # Alert when stale symbols exceed this ratio of the daily run.
    ingestion_stale_price_alert_ratio_threshold: Optional[float] = 0.05
    # Hard-fail run when too few active symbols were successfully covered
    # (covered = produced last_trade_date OR expected-missing classification).
    ingestion_symbol_success_min_ratio: Optional[float] = 0.85
    ingestion_reactivate_if_within_bdays: Optional[int] = 1
    ingestion_reference_symbol: Optional[str] = "SPY"
    ingestion_anchor_min_share: Optional[float] = 0.5
    ingestion_workers: Optional[int] = 2
    ingestion_progress_log_every: Optional[int] = 100
    ingestion_history_days: Optional[int] = 760
    ingestion_trading_calendar_lookback_days: Optional[int] = 365
    ingestion_trading_calendar_lookahead_days: Optional[int] = 90
    ingestion_prune_after_missing_bdays: Optional[int] = 30
    ingestion_rates_enabled: Optional[bool] = True
    ingestion_hy_stress_enabled: Optional[bool] = True
    ingestion_hy_stress_benchmark: Optional[str] = "%CCCHYS"
    ingestion_hy_stress_ma_window: Optional[int] = 10
    ingestion_hy_stress_z_window: Optional[int] = 750
    ingestion_dxy_enabled: Optional[bool] = True
    ingestion_dxy_benchmark_name: Optional[str] = "$USDX"
    ingestion_dxy_ma_days: Optional[int] = 200
    ingestion_dxy_roc_1m_days: Optional[int] = 21
    ingestion_dxy_roc_3m_days: Optional[int] = 63
    ingestion_dxy_roc_6m_days: Optional[int] = 126
    ingestion_dxy_z_window_days: Optional[int] = 500  # ~3y trading days
    ingestion_dxy_pct_window_days: Optional[int] = 756  # ~5y trading days
    ingestion_dxy_shock_threshold_pct: Optional[float] = 0.04
    ingestion_dxy_risk_score_trend_weight: Optional[float] = 0.4
    ingestion_dxy_risk_score_momo_weight: Optional[float] = 0.3
    ingestion_dxy_risk_score_level_weight: Optional[float] = 0.3
    ingestion_rrp_tga_enabled: Optional[bool] = True
    ingestion_fed_balance_sheet_enabled: Optional[bool] = True
    ingestion_tips_real_yield_enabled: Optional[bool] = True
    ingestion_fred_lookback_days: Optional[int] = 5
    ingestion_fetch_earnings: bool = True
    ingestion_earnings_window_days: Optional[int] = 7
    ingestion_yfinance_enabled: bool = True
    ingestion_yfinance_timeout_seconds: Optional[float] = 20.0
    ingestion_yfinance_max_retries: Optional[int] = 2
    ingestion_yfinance_retry_backoff_seconds: Optional[float] = 0.5

    # Broker service (prev close snapshots)
    broker_service_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("BROKER_SERVICE_URL", "INGESTION_BROKER_SERVICE_URL"),
    )
    broker_service_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "BROKER_SERVICE_TOKEN", "AUTH_SERVICE_TOKEN", "INGESTION_BROKER_SERVICE_TOKEN"
        ),
    )

    # Internal service-to-service auth (for calling API admin/operator endpoints)
    auth_service_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SERVICE_TOKEN", "INGESTION_AUTH_SERVICE_TOKEN"),
    )

    # Finnhub API
    finnhub_key: Optional[str] = Field(default=None, alias="FINNHUB_KEY")

    # Price history cache warmup configuration
    price_history_cache_ttl_seconds: Optional[int] = None
    price_history_cache_refresh_chunk_size: Optional[int] = None
    price_cache_refresh_url: Optional[str] = None
    price_cache_refresh_timeout_seconds: Optional[int] = None

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env", ENV_DIR / "ingestion.env"],
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


__all__ = ["Settings", "ENV", "ENV_DIR", "ROOT"]
