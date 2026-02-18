from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.sentiment.src import on_demand


class _FakeCursor:
    def __init__(self, shared_state: dict[str, object]) -> None:
        self._shared_state = shared_state
        self._last_sql: str = ""

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        return None

    def execute(self, sql: str, params: tuple) -> None:  # type: ignore[no-untyped-def]
        self._last_sql = sql
        self._shared_state.setdefault("sql", []).append(sql)

    def fetchone(self):  # type: ignore[no-untyped-def]
        if "FROM rankalpha.dim_stock" in self._last_sql:
            return (123, "Apple Inc")
        if "FROM rankalpha.fact_ai_stock_analysis" in self._last_sql:
            return (777,)
        return None


class _FakeConn:
    def __init__(self, shared_state: dict[str, object]) -> None:
        self._shared_state = shared_state

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._shared_state)

    def close(self) -> None:
        return None

    def commit(self) -> None:
        self._shared_state["committed"] = True


@pytest.mark.asyncio
async def test_on_demand_force_bypasses_in_process_guard(tmp_path, monkeypatch):
    state: dict[str, object] = {}

    def _connection_factory():  # type: ignore[no-untyped-def]
        return _FakeConn(state)

    calls: list[str] = []
    completed: list[int] = []
    schedule_updates: list[int] = []

    async def _ai_analysis(company_name, analyzer_app, symbol, *, trigger=None):  # type: ignore[no-untyped-def]
        calls.append(str(symbol))
        return True

    def _update_schedule(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        schedule_updates.append(1)
        return 1

    monkeypatch.setattr(on_demand, "update_schedule_with_catalysts", _update_schedule)

    settings = SimpleNamespace(sentiment_skip_if_within_days=1)
    await on_demand.handle_on_demand(
        analyzer_app=object(),
        settings=settings,  # type: ignore[arg-type]
        connection_factory=_connection_factory,
        symbol="AAPL",
        force=True,
        schedule_file=Path(tmp_path / "schedule.json"),
        ai_analysis=_ai_analysis,
        already_completed_today=lambda _k: True,
        mark_completed_today=lambda k: completed.append(int(k)),
    )

    assert calls == ["AAPL"]
    assert completed == [123]
    assert schedule_updates == [1]
