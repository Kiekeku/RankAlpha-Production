from __future__ import annotations

from typing import Optional

from pydantic_settings import SettingsConfigDict

from apps.common.src.settings_base import ENV_DIR, BaseAppSettings


class Settings(BaseAppSettings):
    """Portfolio engine service settings."""

    portfolio_nav_skip_zero: Optional[bool] = True

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env", ENV_DIR / "portfolio.env"],
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


__all__ = ["Settings"]
