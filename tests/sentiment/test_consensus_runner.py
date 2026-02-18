from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.sentiment.src import consensus_runner


def test_coerce_int_handles_none_and_bad_values():
    assert consensus_runner._coerce_int(None, default=5) == 5
    assert consensus_runner._coerce_int("9", default=5) == 9
    assert consensus_runner._coerce_int("bad", default=5) == 5


def test_within_recency_window():
    now = datetime.now(timezone.utc)
    assert consensus_runner._within_recency_window(now, skip_window=1) is True
    assert (
        consensus_runner._within_recency_window(now - timedelta(days=2), skip_window=1) is False
    )


class _FakeCursor:
    def __init__(self, handler):
        self._handler = handler
        self._last: tuple[str, tuple] | None = None

    def execute(self, sql: str, params: tuple) -> None:
        self._last = (sql, params)

    def fetchall(self):
        assert self._last is not None
        sql, params = self._last
        return self._handler.fetchall(sql, params)

    def fetchone(self):
        assert self._last is not None
        sql, params = self._last
        return self._handler.fetchone(sql, params)

    def close(self) -> None:
        return None


class _FakeConn:
    def __init__(self, handler):
        self._handler = handler

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._handler)

    def close(self) -> None:
        return None


class _DBHandler:
    def __init__(self, *, last_load_by_stock_key: dict[int, datetime | None]):
        self.last_load_by_stock_key = last_load_by_stock_key

    def fetchall(self, sql: str, _params: tuple):
        if "FROM rankalpha.v_latest_screener_consensus" in sql:
            return [("AAPL", "Apple Inc"), ("MSFT", "Microsoft")]
        return []

    def fetchone(self, sql: str, params: tuple):
        if "SELECT ds.stock_key" in sql:
            symbol = str(params[0]).upper()
            return (101,) if symbol == "AAPL" else ((102,) if symbol == "MSFT" else None)
        if "SELECT MAX(load_ts)" in sql:
            stock_key = int(params[0])
            return (self.last_load_by_stock_key.get(stock_key),)
        return None


@pytest.mark.asyncio
async def test_run_consensus_batch_runs_old_and_skips_recent():
    now = datetime.now(timezone.utc)
    handler = _DBHandler(
        last_load_by_stock_key={
            101: (now - timedelta(days=10)).replace(tzinfo=None),  # naive; should be normalized
            102: now.replace(tzinfo=None),  # naive recent
        }
    )

    def connection_factory():
        return _FakeConn(handler)

    settings = SimpleNamespace(
        sentiment_consensus_min_appearances=0,
        sentiment_consensus_min_styles=0,
        sentiment_consensus_limit=2,
        sentiment_skip_if_within_days=3,
    )

    calls: list[str] = []
    completed: list[int] = []

    async def ai_analysis(company_name, analyzer_app, symbol, *, trigger=None):  # type: ignore[no-untyped-def]
        calls.append(symbol)
        return True

    await consensus_runner.run_consensus_batch(
        analyzer_app=object(),
        ai_analysis=ai_analysis,
        settings=settings,
        already_completed_today=lambda _k: False,
        mark_completed_today=lambda k: completed.append(int(k)),
        schedule_file=None,
        connection_factory=connection_factory,
    )

    assert calls == ["AAPL"]
    assert completed == [101]


@pytest.mark.asyncio
async def test_run_consensus_batch_handles_timeout_without_marking_completed():
    now = datetime.now(timezone.utc)
    handler = _DBHandler(
        last_load_by_stock_key={
            101: (now - timedelta(days=10)).replace(tzinfo=None),
        }
    )

    def connection_factory():
        return _FakeConn(handler)

    settings = SimpleNamespace(
        sentiment_consensus_min_appearances=0,
        sentiment_consensus_min_styles=0,
        sentiment_consensus_limit=1,
        sentiment_skip_if_within_days=1,
    )

    completed: list[int] = []

    async def ai_analysis(_company, _app, _sym, *, trigger=None):  # type: ignore[no-untyped-def]
        raise asyncio.TimeoutError()

    await consensus_runner.run_consensus_batch(
        analyzer_app=object(),
        ai_analysis=ai_analysis,
        settings=settings,
        already_completed_today=lambda _k: False,
        mark_completed_today=lambda k: completed.append(int(k)),
        schedule_file=None,
        connection_factory=connection_factory,
    )

    assert completed == []
