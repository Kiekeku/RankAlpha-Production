from __future__ import annotations

from types import SimpleNamespace

import pytest


pytest.importorskip("sqlalchemy")
pytest.importorskip("trafilatura")
pytest.importorskip("rapidfuzz")
pytest.importorskip("openai")

from newswire import llm  # noqa: E402


class _DB:
    def __init__(self, *, ev, cl, raw, symbols=None):
        self._ev = ev
        self._cl = cl
        self._raw = raw
        self._symbols = symbols or {}
        self.flushed = 0

    def get(self, model, pk):  # type: ignore[no-untyped-def]
        name = getattr(model, "__name__", str(model))
        if name.endswith("FactNewsEvent"):
            return self._ev
        if name.endswith("DimNewsCluster"):
            return self._cl
        if name.endswith("FactNewsRaw"):
            return self._raw
        return None

    def execute(self, _stmt):  # type: ignore[no-untyped-def]
        return [SimpleNamespace(stock_key=k, symbol=v) for k, v in self._symbols.items()]

    def flush(self) -> None:
        self.flushed += 1


def _make_min_objects():
    ev = SimpleNamespace(cluster_id=10)
    cl = SimpleNamespace(centroid_raw_id=100)
    raw = SimpleNamespace(
        title="T",
        snippet="S",
        body_text="body",
        url_canonical="https://example.com",
    )
    return ev, cl, raw


def test_analyze_event_cluster_skips_when_already_analyzed(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_FORCE_REANALYZE", "false")
    ev, cl, raw = _make_min_objects()
    ev.llm_ran_at = object()
    ev.llm_response = {"summary": "x"}
    ev.llm_error = None
    db = _DB(ev=ev, cl=cl, raw=raw, symbols={1: "AAPL"})

    out = llm.analyze_event_cluster(db, event_id=1)
    assert out["ok"] is True
    assert out["skipped"] == "already_analyzed"


def test_analyze_event_cluster_disabled_short_circuits(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_ENABLED", "false")
    ev, cl, raw = _make_min_objects()
    db = _DB(ev=ev, cl=cl, raw=raw, symbols={1: "AAPL"})

    out = llm.analyze_event_cluster(db, event_id=1)
    assert out["ok"] is False
    assert out["error"] == "newswire_llm_disabled"
    assert ev.llm_error == "disabled"
    assert db.flushed >= 1


def test_analyze_event_cluster_missing_api_key_sets_error(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ev, cl, raw = _make_min_objects()

    monkeypatch.setattr(llm, "map_entities_to_symbols", lambda *_a, **_k: [{"stock_key": 1, "confidence": 0.8}])
    db = _DB(ev=ev, cl=cl, raw=raw, symbols={1: "AAPL"})

    out = llm.analyze_event_cluster(db, event_id=1)
    assert out["ok"] is False
    assert "OPENAI_API_KEY missing" in out["error"]
    assert ev.llm_error == "api_key_missing"


def test_analyze_event_cluster_dry_run_returns_ok_without_openai_calls(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("AI_DRY_RUN", "true")
    ev, cl, raw = _make_min_objects()

    created = {"called": 0}

    class _DummyOpenAI:
        def __init__(self, api_key):  # noqa: ARG002
            created["called"] += 1

    monkeypatch.setattr(llm, "OpenAI", _DummyOpenAI)
    monkeypatch.setattr(llm, "map_entities_to_symbols", lambda *_a, **_k: [{"stock_key": 1, "confidence": 0.8}])
    db = _DB(ev=ev, cl=cl, raw=raw, symbols={1: "AAPL"})

    out = llm.analyze_event_cluster(db, event_id=1)
    assert out == {"ok": True, "dry_run": True}
    assert ev.llm_error == "dry_run"
    assert created["called"] == 1


def test_analyze_event_cluster_force_reanalyze_bypasses_skip(monkeypatch):
    monkeypatch.setenv("NEWS_LLM_ENABLED", "true")
    monkeypatch.setenv("NEWS_LLM_FORCE_REANALYZE", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ev, cl, raw = _make_min_objects()
    ev.llm_ran_at = object()
    ev.llm_response = {"summary": "x"}
    ev.llm_error = None
    monkeypatch.setattr(
        llm,
        "map_entities_to_symbols",
        lambda *_a, **_k: [{"stock_key": 1, "confidence": 0.8}],
    )
    db = _DB(ev=ev, cl=cl, raw=raw, symbols={1: "AAPL"})

    out = llm.analyze_event_cluster(db, event_id=1)
    assert out["ok"] is False
    assert out["error"] == "OPENAI_API_KEY missing"
