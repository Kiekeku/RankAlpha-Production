from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root and env directory helpers reused across services
ROOT = Path(__file__).resolve().parents[3]
ENV = os.getenv("RANKALPHA_ENV", "local")
ENV_DIR = ROOT / "env" / ENV


class BaseAppSettings(BaseSettings):
    """
    Narrow shared settings used across services.

    Keep this surface intentionally small (db / redis / openai / logging) to
    avoid cross‑service collisions; service‑specific settings live alongside
    each app in apps/<service>/src/settings.py.
    """

    # Database (PostgreSQL)
    database_name: str = Field(validation_alias=AliasChoices("DATABASE_NAME"))
    db_username: str = Field(validation_alias=AliasChoices("DB_USERNAME"))
    password: str = Field(validation_alias=AliasChoices("PASSWORD", "DB_PASSWORD"))
    host: str = Field(validation_alias=AliasChoices("HOST", "DB_HOST"))
    port: int = Field(validation_alias=AliasChoices("DB_PORT", "DB_PORT_CONTAINER"))
    db_echo: Optional[bool] = False

    # SQLAlchemy connection pool tuning (optional).
    # Defaults follow SQLAlchemy's QueuePool defaults (pool_size=5, max_overflow=10, timeout=30s).
    db_pool_size: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("DB_POOL_SIZE"),
    )
    db_max_overflow: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("DB_MAX_OVERFLOW"),
    )
    db_pool_timeout_seconds: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("DB_POOL_TIMEOUT_SECONDS"),
    )
    db_pool_recycle_seconds: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("DB_POOL_RECYCLE_SECONDS"),
    )

    # Redis cache configuration
    redis_url: Optional[str] = None
    redis_host: Optional[str] = None
    redis_port: Optional[int] = None
    redis_db: Optional[int] = None
    redis_password: Optional[str] = None

    # OpenAI / LLM
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_max_completion_tokens: Optional[int] = None
    openai_max_tokens: Optional[int] = None
    openai_disable_reasoning: bool = False
    openai_reasoning_effort: Optional[str] = None  # low | medium | high
    openai_planner_model: Optional[str] = None  # optional override for planner-only model

    # Logging
    log_level: Optional[str] = None  # DEBUG, INFO, WARNING, ERROR
    log_slow_request_ms: Optional[int] = None  # warn threshold

    # Outbound email/budget alerts (shared helpers)
    gmail_sender: Optional[str] = None
    gmail_recipient: Optional[str] = None
    gmail_app_password: Optional[str] = None
    budget_alert_recipients: Optional[str] = None
    # SMTP (optional, preferred over Gmail if set)
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_secure: Optional[bool] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_to_alerts: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env"],
        case_sensitive=False,
        extra="ignore",
    )
