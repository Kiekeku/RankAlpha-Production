from __future__ import annotations

import asyncio
from datetime import date

from httpx import ASGITransport, AsyncClient

from apps.api.src.database import get_db
from apps.api.src.main import app
from apps.api.src.routers import backtest as backtest_router


def test_add_months_clamps_to_month_end():
    assert backtest_router._add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert backtest_router._add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)  # leap year


def _dummy_db():
    class DummySession:
        def close(self):  # pragma: no cover - compatibility
            pass

    yield DummySession()


def test_backtest_rejects_large_date_ranges(monkeypatch):
    monkeypatch.setenv("BACKTEST_MAX_RANGE_DAYS", "1")
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/v1/backtest/quick",
                    json={
                        "strategy_name": "momentum_top_n",
                        "signal_type": "LINREG_200",
                        "top_n": 10,
                        "rebalance_frequency": "daily",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-10",
                        "initial_capital": 100000,
                    },
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 400
        assert "Date range too large" in resp.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(get_db, None)

