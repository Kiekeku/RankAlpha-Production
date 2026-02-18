from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.sentiment.src import persistence


@pytest.fixture(autouse=True)
def _clear_persistence_caches():
    persistence._DIM_KEY_CACHE.clear()
    persistence._TABLE_EXISTENCE_CACHE.clear()
    yield
    persistence._DIM_KEY_CACHE.clear()
    persistence._TABLE_EXISTENCE_CACHE.clear()


def test_normalize_dim_label_and_keyish():
    assert persistence._normalize_dim_label("  6\u201112m  ") == "6-12m"
    assert persistence._normalize_dim_label("A  B") == "a b"

    assert persistence._normalize_keyish("Strong Buy") == "strong_buy"
    assert persistence._normalize_keyish("low-vol") == "low_vol"


def test_coerce_level_label_accepts_strings_and_numbers():
    assert persistence._coerce_level_label("low") == "low"
    assert persistence._coerce_level_label("2") == "medium"
    assert persistence._coerce_level_label(3) == "high"
    assert persistence._coerce_level_label(0.10) == "low"
    assert persistence._coerce_level_label(55) == "medium"
    assert persistence._coerce_level_label(0.90) == "high"
    assert persistence._coerce_level_label("n/a") is None


def test_normalize_catalyst_type():
    assert persistence._normalize_catalyst_type(None) == "short"
    assert persistence._normalize_catalyst_type("short") == "short"
    assert persistence._normalize_catalyst_type("short-term") == "short"
    assert persistence._normalize_catalyst_type("long term") == "long"
    assert persistence._normalize_catalyst_type("event") == "event"
    assert persistence._normalize_catalyst_type("major_event_risk") == "event"
    assert persistence._normalize_catalyst_type("macro") == "event"


def test_extract_json_block_supports_backticks_and_triple_quotes():
    sample1 = "prefix '''json {\"a\": 1} ''' suffix"
    assert persistence.extract_json_block(sample1) == '{"a": 1}'

    sample2 = "prefix ```json\n{\"b\": 2}\n``` suffix"
    assert persistence.extract_json_block(sample2) == '{"b": 2}'

    with pytest.raises(ValueError):
        persistence.extract_json_block("no json here")


class _CursorTableExists:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return ("rankalpha.fact_ai_stock_analysis",)


def test_table_exists_is_cached():
    cur = _CursorTableExists()
    assert persistence.table_exists(cur, "rankalpha.fact_ai_stock_analysis") is True
    assert persistence.table_exists(cur, "rankalpha.fact_ai_stock_analysis") is True
    assert len(cur.executed) == 1


class _CursorSourceKey:
    def __init__(self, *, return_row: tuple[int] | None) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._return_row = return_row

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return self._return_row


def test_get_or_create_source_key_returns_key_and_executes_insert_then_select():
    cur = _CursorSourceKey(return_row=(123,))
    out = persistence.get_or_create_source_key(cur, "RankAlpha Sentiment AI", "1")
    assert out == 123
    assert any("INSERT INTO rankalpha.dim_source" in sql for sql, _ in cur.executed)
    assert any("SELECT source_key FROM rankalpha.dim_source" in sql for sql, _ in cur.executed)


def test_get_or_create_source_key_raises_when_missing_row():
    cur = _CursorSourceKey(return_row=None)
    with pytest.raises(RuntimeError):
        persistence.get_or_create_source_key(cur, "RankAlpha Sentiment AI", "1")


def test_notify_ai_cache_refresh_sends_payload(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):  # type: ignore[no-untyped-def]
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})

        class _Resp:
            status_code = 200
            text = "ok"

        return _Resp()

    monkeypatch.setattr(persistence.requests, "post", fake_post)

    settings = SimpleNamespace(
        ai_analysis_cache_url="http://example.com/refresh",
        ai_analysis_cache_token="token",
        ai_analysis_cache_timeout_seconds="2.5",
        ai_analysis_cache_refresh_chunk_size="77",
    )
    persistence._notify_ai_cache_refresh("aapl", "abc-123", settings)
    assert calls
    assert calls[0]["url"] == "http://example.com/refresh"
    assert calls[0]["headers"]["Authorization"] == "Bearer token"
    assert calls[0]["json"]["symbols"] == ["AAPL"]
    assert calls[0]["json"]["analysis_ids"] == ["abc-123"]
    assert calls[0]["json"]["include_proximity"] is True
    assert calls[0]["json"]["chunk_size"] == 77
