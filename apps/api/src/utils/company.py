"""Helpers for normalizing company names for display."""

from __future__ import annotations

import time
from typing import Any

from pydantic import field_validator

from apps.common.src.company_utils import _NAME_CACHE, clean_company_name


class CompanyNameSanitizerMixin:
    """Pydantic mixin that normalizes a `company_name` field."""

    @field_validator("company_name", mode="before")
    @classmethod
    def _sanitize_company_name(cls, value: Any) -> Any:  # pragma: no cover - simple passthrough
        if isinstance(value, str):
            cleaned = clean_company_name(value)
            return cleaned if cleaned is not None else value
        return value


__all__ = ["clean_company_name", "CompanyNameSanitizerMixin", "_NAME_CACHE", "time"]
