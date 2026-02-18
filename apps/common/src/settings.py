"""
Backward‑compatible shim around the new shared base settings.

Prefer importing service‑scoped settings from apps/<service>/src/settings.py.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from apps.common.src.settings_base import ENV, ENV_DIR, ROOT, BaseAppSettings


class Settings(BaseAppSettings):
    """Deprecated: use per‑service Settings classes instead."""

    model_config = SettingsConfigDict(
        env_file=[ENV_DIR / "shared.env"],
        case_sensitive=False,
        extra="ignore",
    )


__all__ = [
    "Settings",
    "BaseAppSettings",
    "ROOT",
    "ENV",
    "ENV_DIR",
]
