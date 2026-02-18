from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

from apps.common.src.news_utils import entity_map


@pytest.fixture(autouse=True)
def _clear_entity_cache(monkeypatch):
    entity_map._UNIVERSE_CACHE = None
    monkeypatch.delenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", raising=False)
    monkeypatch.delenv("NEWS_ENTITY_UNIVERSE_CACHE_MAX_STALE_SEC", raising=False)
    yield
    entity_map._UNIVERSE_CACHE = None


class _FakeQuery:
    def __init__(self, *, rows=None, raise_on_all: Exception | None = None):
        self._rows = rows or []
        self._raise = raise_on_all

    def join(self, *_a, **_k):  # pragma: no cover
        return self

    def filter(self, *_a, **_k):  # pragma: no cover
        return self

    def all(self):
        if self._raise:
            raise self._raise
        return self._rows


class _FakeDB:
    def __init__(self, *, rows, raise_on_query: Exception | None = None):
        self.rows = rows
        self.raise_on_query = raise_on_query
        self.query_calls = 0

    def query(self, *_a, **_k):
        self.query_calls += 1
        return _FakeQuery(rows=self.rows, raise_on_all=self.raise_on_query)


def test_normalize_name_strips_suffix_and_punctuation():
    assert entity_map._normalize_name("Acme, Inc.") == "acme"
    assert entity_map._normalize_name("Foo-Bar PLC") == "foo bar"


def test_load_universe_caches_results(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "600")
    db = _FakeDB(rows=[(1, "AAPL", "Apple Inc.")])
    u1 = entity_map.load_universe(db)
    u2 = entity_map.load_universe(db)
    assert u1 == u2
    assert db.query_calls == 1


def test_load_universe_falls_back_to_cached_snapshot_on_db_error(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "600")
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_MAX_STALE_SEC", "3600")

    t0 = 1000.0
    now = t0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr(entity_map.time, "monotonic", fake_monotonic)

    db_ok = _FakeDB(rows=[(1, "AAPL", "Apple Inc.")])
    cached = entity_map.load_universe(db_ok)

    now = t0 + 100.0
    db_fail = _FakeDB(rows=[], raise_on_query=RuntimeError("db down"))
    out = entity_map.load_universe(db_fail)
    assert out == cached


def test_load_universe_raises_when_cache_too_stale(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "600")
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_MAX_STALE_SEC", "10")

    t0 = 1000.0
    now = t0

    def fake_monotonic() -> float:
        return now

    monkeypatch.setattr(entity_map.time, "monotonic", fake_monotonic)

    db_ok = _FakeDB(rows=[(1, "AAPL", "Apple Inc.")])
    entity_map.load_universe(db_ok)

    now = t0 + 999.0
    db_fail = _FakeDB(rows=[], raise_on_query=RuntimeError("db down"))
    with pytest.raises(RuntimeError):
        entity_map.load_universe(db_fail)


def test_map_entities_to_symbols_prefers_ticker_then_name(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "0")  # disable caching for test
    db = _FakeDB(rows=[(1, "AAPL", "Apple Inc."), (2, "MSFT", "Microsoft Corporation")])

    impacts = entity_map.map_entities_to_symbols(db, "AAPL shares rise", "Apple Inc announces...")
    assert impacts
    assert impacts[0]["stock_key"] == 1
    assert impacts[0]["confidence"] == 0.8
    # Company-name match should find MSFT if name appears (without duplicating AAPL)
    impacts2 = entity_map.map_entities_to_symbols(db, "New product", "Microsoft Corporation launches...")
    assert impacts2 and impacts2[0]["stock_key"] == 2


def test_map_entities_to_symbols_ignores_short_or_stopword_tickers(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "0")
    monkeypatch.setenv("NEWS_ENTITY_MIN_TICKER_LEN", "3")
    db = _FakeDB(rows=[(1, "IT", "IT Holdings"), (2, "AAPL", "Apple Inc.")])

    impacts = entity_map.map_entities_to_symbols(db, "It looks like markets rallied", "No issuer mention")
    assert all(i["stock_key"] != 1 for i in impacts)


def test_map_entities_to_symbols_name_match_uses_word_boundaries(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "0")
    db = _FakeDB(rows=[(1, "META", "Meta"), (2, "MSFT", "Microsoft Corporation")])

    # "metaverse" should not match company name "meta" when boundary checks are enabled.
    impacts = entity_map.map_entities_to_symbols(db, "Metaverse update", "new VR launch")
    assert all(i["stock_key"] != 1 for i in impacts)


def test_map_entities_to_symbols_matches_short_single_word_company_name(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "0")
    db = _FakeDB(rows=[(1, "NKE", "Nike"), (2, "MSFT", "Microsoft Corporation")])

    impacts = entity_map.map_entities_to_symbols(db, "Nike launches new shoe", "Product reveal")
    assert impacts and impacts[0]["stock_key"] == 1


def test_map_entities_to_symbols_explicit_dollar_ticker_bypasses_stoplist(monkeypatch):
    monkeypatch.setenv("NEWS_ENTITY_UNIVERSE_CACHE_SEC", "0")
    monkeypatch.setenv("NEWS_ENTITY_TICKER_STOPLIST", "NOW")
    db = _FakeDB(rows=[(1, "NOW", "ServiceNow"), (2, "MSFT", "Microsoft Corporation")])

    impacts = entity_map.map_entities_to_symbols(db, "$NOW beats estimates", "after earnings")
    assert impacts and impacts[0]["stock_key"] == 1
