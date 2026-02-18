from __future__ import annotations

import json
from datetime import datetime, time, timezone
from types import SimpleNamespace

import pytest

from newswire.cursor import load_cursors, save_cursors
from newswire.schedule import _load_schedule, enqueue_analysis_for_stock
from newswire.settings import NewswireSettings


class _FakeQuery:
    def __init__(self, *, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def filter(self, *_a, **_k):  # pragma: no cover
        return self

    def all(self):
        return self._rows

    def one_or_none(self):
        return self._one


class _FakeDB:
    def __init__(self, *, cursor_rows=None, stock=None):
        self.cursor_rows = cursor_rows or []
        self.stock = stock
        self.execute_calls = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        # Heuristic: NewsCursor load uses .all()
        if hasattr(model, "__name__") and model.__name__ == "NewsCursor":
            return _FakeQuery(rows=self.cursor_rows)
        return _FakeQuery(one=self.stock)

    def execute(self, _stmt):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        return None

    def flush(self) -> None:
        return None


def test_load_cursors_normalizes_timezone_and_sets_defaults():
    rows = [
        SimpleNamespace(source_name="gdelt", last_seen=datetime(2025, 1, 1)),  # naive
        SimpleNamespace(
            source_name="serper", last_seen=datetime(2025, 1, 2, tzinfo=timezone.utc)
        ),
    ]
    db = _FakeDB(cursor_rows=rows)
    out = load_cursors(db)
    assert out["gdelt"].tzinfo == timezone.utc
    assert out["serper"].tzinfo == timezone.utc
    assert "rss" in out


def test_save_cursors_calls_execute_for_non_null(monkeypatch):
    from newswire import cursor as cursor_mod

    captured: list[dict] = []

    class _Stmt:
        def __init__(self, **vals):
            self.vals = vals

        def values(self, **vals):
            self.vals.update(vals)
            return self

        def on_conflict_do_update(self, **_k):
            return self

    def fake_pg_insert(_model):  # type: ignore[no-untyped-def]
        class _I:
            def values(self, **vals):
                captured.append(vals)
                return _Stmt(**vals)

        return _I()

    monkeypatch.setattr(cursor_mod, "pg_insert", fake_pg_insert)

    db = _FakeDB()
    save_cursors(
        db,
        {
            "gdelt": datetime(2025, 1, 1),  # naive
            "serper": None,
        },
    )
    assert db.execute_calls == 1
    assert captured
    assert captured[0]["source_name"] == "gdelt"
    assert captured[0]["last_seen"].tzinfo == timezone.utc


def test_schedule_enqueue_creates_and_is_idempotent(tmp_path, monkeypatch):
    from newswire import schedule as sched

    monkeypatch.setenv("NEWS_SENTIMENT_SCHEDULE_FILE", str(tmp_path / "schedule.json"))

    class _D:
        stock_key = 1
        symbol = "aapl"
        company_name = "Apple Inc"

    db = _FakeDB(stock=_D())

    class _FixedDatetime:
        @classmethod
        def now(cls):  # type: ignore[no-untyped-def]
            return datetime(2025, 1, 2)

    monkeypatch.setattr(sched, "datetime", _FixedDatetime)

    assert enqueue_analysis_for_stock(db, 1) is True
    assert enqueue_analysis_for_stock(db, 1) is False

    data = _load_schedule()
    assert data["1"]["symbol"] == "AAPL"
    assert data["1"]["company_name"] == "Apple Inc"
    assert data["1"]["analysis_dates"] == ["2025-01-02"]


def test_load_schedule_returns_empty_on_bad_json(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_SENTIMENT_SCHEDULE_FILE", str(tmp_path / "schedule.json"))
    (tmp_path / "schedule.json").write_text("{bad json", encoding="utf-8")
    assert _load_schedule() == {}


def test_newswire_settings_from_env_parses_defaults_and_invalid_values(monkeypatch):
    monkeypatch.setenv("NEWS_SOURCES", "gdelt, serper ,rss")
    monkeypatch.setenv("NEWS_PREMARKET_START", "bad")
    monkeypatch.setenv("NEWS_PREMARKET_END", "09:30")
    monkeypatch.setenv("NEWS_TIMEZONE", "America/New_York")
    monkeypatch.setenv("NEWS_MATERIALITY_THRESHOLD", "not-a-float")
    monkeypatch.setenv("NEWS_SERPER_PERIOD_SEC", "not-an-int")
    monkeypatch.setenv("NEWS_RSS_PERIOD_SEC", "60")

    s = NewswireSettings.from_env()
    assert s.sources == ["gdelt", "serper", "rss"]
    assert s.premkt_start == time(7, 0)  # default due to bad input
    assert s.premkt_end == time(9, 30)
    assert s.materiality_threshold == 0.80
    assert s.serper_period_sec == 300  # default due to bad input
    assert s.rss_period_sec == 60
