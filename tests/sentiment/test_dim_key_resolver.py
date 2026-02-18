from __future__ import annotations

import pytest

from apps.sentiment.src import persistence


class FakeCursor:
    def __init__(self, rows_by_sql: dict[str, list[tuple[int, str]]]):
        self._rows_by_sql = rows_by_sql
        self._last_sql: str | None = None
        self.executed: list[str] = []

    def execute(self, sql: str, _params=None):
        self._last_sql = sql
        self.executed.append(sql)

    def fetchall(self):
        assert self._last_sql is not None
        return self._rows_by_sql.get(self._last_sql, [])


@pytest.fixture(autouse=True)
def _clear_dim_cache():
    persistence._DIM_KEY_CACHE.clear()
    yield
    persistence._DIM_KEY_CACHE.clear()


def test_resolver_normalizes_unicode_dash_timeframes():
    # Note: DB migration uses a non-breaking hyphen for 6‑12m and 12‑24m.
    tf_label_db = "6\u201112m"
    cur = FakeCursor(
        rows_by_sql={
            "SELECT timeframe_key, timeframe_label FROM rankalpha.dim_timeframe": [
                (101, tf_label_db),
                (102, "3m"),
            ],
        }
    )
    resolver = persistence.DimKeyResolver(cur)

    assert resolver.timeframe_key("6-12m") == 101
    assert resolver.timeframe_key(tf_label_db) == 101


def test_resolver_normalizes_keyish_inputs_for_rating_and_style():
    cur = FakeCursor(
        rows_by_sql={
            "SELECT rating_key, rating_label FROM rankalpha.dim_rating": [
                (42, "strong_buy"),
                (43, "neutral"),
            ],
            "SELECT style_key, style_name FROM rankalpha.dim_style": [
                (55, "low_vol"),
                (56, "momentum"),
            ],
        }
    )
    resolver = persistence.DimKeyResolver(cur)

    assert resolver.rating_key("Strong Buy") == 42
    assert resolver.rating_key("strong-buy") == 42
    assert resolver.style_key("low vol") == 55
    assert resolver.style_key("low-vol") == 55


def test_resolver_buckets_confidence_numeric_to_dim_key():
    cur = FakeCursor(
        rows_by_sql={
            "SELECT confidence_key, confidence_label FROM rankalpha.dim_confidence": [
                (7, "low"),
                (8, "medium"),
                (9, "high"),
            ],
        }
    )
    resolver = persistence.DimKeyResolver(cur)

    assert resolver.confidence_key(1) == 7
    assert resolver.confidence_key(2) == 8
    assert resolver.confidence_key(3) == 9
    assert resolver.confidence_key(0.10) == 7
    assert resolver.confidence_key(55) == 8
    assert resolver.confidence_key(0.90) == 9


def test_resolver_returns_none_for_unknown_labels():
    cur = FakeCursor(
        rows_by_sql={
            "SELECT trend_key, trend_label FROM rankalpha.dim_trend_category": [
                (10, "strong up"),
            ],
        }
    )
    resolver = persistence.DimKeyResolver(cur)

    assert resolver.trend_key("not a real label") is None
