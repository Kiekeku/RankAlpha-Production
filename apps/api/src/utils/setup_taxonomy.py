from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, case, func, literal, or_
from sqlalchemy.sql.elements import ColumnElement

SETUP_TAXONOMY_SLUGS: tuple[str, ...] = (
    "momentum",
    "breakout",
    "growth",
    "mean_reversion",
    "pullback",
    "defensive",
    "value",
    "short",
    "earnings",
)

_BREAKOUT_TOKENS: tuple[str, ...] = (
    "breakout",
    "52w",
    "52-week",
    "newhigh",
    "new-high",
    "fresh52",
    "fresh-52",
)

_STYLE_KEYS_MEAN_REVERSION: tuple[str, ...] = ("meanrev", "meanreversion")
_STYLE_KEYS_GROWTH: tuple[str, ...] = ("growth", "qualitygrowth")
_STYLE_KEYS_VALUE: tuple[str, ...] = ("value", "valuegarp")


def compact_style_key(style_name: Optional[str]) -> str:
    return (style_name or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def compact_style_key_expr(style_name_col: ColumnElement) -> ColumnElement:
    style_name_norm = func.lower(func.trim(style_name_col))
    return func.replace(func.replace(func.replace(style_name_norm, " ", ""), "_", ""), "-", "")


def setup_is_breakout(source_name: Optional[str]) -> bool:
    if not source_name:
        return False
    s = source_name.lower()
    return any(token in s for token in _BREAKOUT_TOKENS)


def breakout_source_expr(source_name_col: ColumnElement) -> ColumnElement:
    return or_(*[source_name_col.ilike(f"%{token}%") for token in _BREAKOUT_TOKENS])


def setup_is_earnings(style_name: Optional[str], source_name: Optional[str]) -> bool:
    if style_name and style_name.lower().startswith("earnings"):
        return True
    if source_name and "earnings" in source_name.lower():
        return True
    return False


def earnings_expr(style_name_col: ColumnElement, source_name_col: ColumnElement) -> ColumnElement:
    return or_(style_name_col.ilike("Earnings%"), source_name_col.ilike("%earnings%"))


def setup_bucket_for_hit(
    *,
    style_name: Optional[str],
    source_name: Optional[str],
) -> tuple[str, Optional[str], bool]:
    style_raw = (style_name or "").strip()
    style_key = compact_style_key(style_raw)

    if setup_is_earnings(style_raw, source_name):
        return "Earnings", "earnings", True
    if style_key == "short":
        return "Short", "short", True
    if setup_is_breakout(source_name):
        return "Breakout", "breakout", True
    if style_key == "momentum":
        return "Momentum", "momentum", True
    if style_key == "pullback":
        return "Pullback", "pullback", True
    if style_key in _STYLE_KEYS_MEAN_REVERSION:
        return "Mean Reversion", "mean_reversion", True
    if style_key in _STYLE_KEYS_GROWTH:
        return "Growth", "growth", True
    if style_key == "defensive":
        return "Defensive", "defensive", True
    if style_key in _STYLE_KEYS_VALUE:
        return "Value", "value", True
    return style_raw or "Other", None, False


def setup_style_filter_expr(
    *,
    slug: str,
    style_name_col: ColumnElement,
    source_name_col: ColumnElement,
) -> ColumnElement:
    style_key_norm = compact_style_key_expr(style_name_col)

    if slug == "breakout":
        return breakout_source_expr(source_name_col)
    if slug == "momentum":
        return and_(style_key_norm == "momentum", ~breakout_source_expr(source_name_col))
    if slug == "growth":
        return style_key_norm.in_(_STYLE_KEYS_GROWTH)
    if slug == "mean_reversion":
        return style_key_norm.in_(_STYLE_KEYS_MEAN_REVERSION)
    if slug == "pullback":
        return style_key_norm == "pullback"
    if slug == "defensive":
        return style_key_norm == "defensive"
    if slug == "value":
        return style_key_norm.in_(_STYLE_KEYS_VALUE)
    if slug == "short":
        return style_key_norm == "short"
    if slug == "earnings":
        return earnings_expr(style_name_col, source_name_col)

    raise ValueError(f"Unsupported setup style: {slug}")


def setup_bucket_slug_expr(
    *,
    style_name_col: ColumnElement,
    source_name_col: ColumnElement,
) -> ColumnElement:
    style_key_norm = compact_style_key_expr(style_name_col)
    return case(
        (earnings_expr(style_name_col, source_name_col), literal("earnings")),
        (style_key_norm == "short", literal("short")),
        (breakout_source_expr(source_name_col), literal("breakout")),
        (style_key_norm == "momentum", literal("momentum")),
        (style_key_norm == "pullback", literal("pullback")),
        (style_key_norm.in_(_STYLE_KEYS_MEAN_REVERSION), literal("mean_reversion")),
        (style_key_norm.in_(_STYLE_KEYS_GROWTH), literal("growth")),
        (style_key_norm == "defensive", literal("defensive")),
        (style_key_norm.in_(_STYLE_KEYS_VALUE), literal("value")),
        else_=None,
    )


def setup_bucket_label_expr(
    *,
    style_name_col: ColumnElement,
    source_name_col: ColumnElement,
) -> ColumnElement:
    style_key_norm = compact_style_key_expr(style_name_col)
    return case(
        (earnings_expr(style_name_col, source_name_col), literal("Earnings")),
        (style_key_norm == "short", literal("Short")),
        (breakout_source_expr(source_name_col), literal("Breakout")),
        (style_key_norm == "momentum", literal("Momentum")),
        (style_key_norm == "pullback", literal("Pullback")),
        (style_key_norm.in_(_STYLE_KEYS_MEAN_REVERSION), literal("Mean Reversion")),
        (style_key_norm.in_(_STYLE_KEYS_GROWTH), literal("Growth")),
        (style_key_norm == "defensive", literal("Defensive")),
        (style_key_norm.in_(_STYLE_KEYS_VALUE), literal("Value")),
        else_=func.coalesce(style_name_col, literal("Other")),
    )
