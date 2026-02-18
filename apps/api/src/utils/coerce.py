"""Lightweight coercion helpers shared across routers/services."""

from __future__ import annotations

from typing import Any, Optional, overload


@overload
def coerce_float(value: Any, default: None = None) -> Optional[float]: ...


@overload
def coerce_float(value: Any, default: float) -> float: ...


def coerce_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


@overload
def coerce_int(value: Any, default: None = None) -> Optional[int]: ...


@overload
def coerce_int(value: Any, default: int) -> int: ...


def coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def coerce_positive_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    val = coerce_float(value, default)
    if val is None or val <= 0:
        return default
    return val


__all__ = ["coerce_float", "coerce_int", "coerce_positive_float"]
