from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.database import get_db
from apps.api.src.routers import trading

def _set_trading_token(monkeypatch, token: str = "test-token") -> None:
    monkeypatch.setenv("TRADING_BEARER_TOKEN", token)
    trading._get_settings.cache_clear()


def test_trading_endpoint_requires_bearer_token(monkeypatch):
    _set_trading_token(monkeypatch, "secret-token")

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/trading/signals",
                json={
                    "symbol": "MSFT",
                    "action": "BUY",
                    "as_of_date": date.today().isoformat(),
                    "recommended_price": "400.00",
                },
            )

    resp = asyncio.run(_run())

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing Bearer token"


def test_trading_endpoint_accepts_payload(monkeypatch):
    _set_trading_token(monkeypatch, "secret-token")

    captured_payload = {}

    def fake_upsert(session, payload):
        captured_payload["value"] = payload
        return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    class DummySession:
        def close(self):
            pass

    def dummy_db():
        yield DummySession()

    monkeypatch.setattr(trading, "upsert_trade_recommendation", fake_upsert)
    app.dependency_overrides[get_db] = dummy_db

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/trading/signals",
                headers={"Authorization": "Bearer secret-token"},
                json={
                    "symbol": "AAPL",
                    "action": "BUY",
                    "as_of_date": "2025-10-07",
                    "recommended_price": "182.45",
                    "order_type": "LIMIT",
                    "limit_price": "182.55",
                    "strategy_name": "Breakout-Q4",
                    "preconditions": {"max_slippage_bps": 10},
                },
            )

    resp = asyncio.run(_run())

    assert resp.status_code == 201
    body = resp.json()
    assert body["recommendation_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert body["status"] == "accepted"
    assert captured_payload["value"]["as_of_date"] == "2025-10-07"
    assert captured_payload["value"]["order_type"] == "LIMIT"
    assert captured_payload["value"]["preconditions"] == {"max_slippage_bps": 10}

    app.dependency_overrides.pop(get_db, None)


def test_trading_endpoint_returns_422_on_symbol_currency_collision(monkeypatch):
    _set_trading_token(monkeypatch, "secret-token")

    def fake_upsert(session, payload):
        raise ValueError(
            "dim_stock symbol collision: symbol='SHOP' already exists with currency_code='USD'"
        )

    class DummySession:
        def close(self):
            pass

    def dummy_db():
        yield DummySession()

    monkeypatch.setattr(trading, "upsert_trade_recommendation", fake_upsert)
    app.dependency_overrides[get_db] = dummy_db

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/trading/signals",
                headers={"Authorization": "Bearer secret-token"},
                json={
                    "symbol": "SHOP",
                    "action": "BUY",
                    "as_of_date": "2025-10-07",
                    "recommended_price": "100.00",
                    "currency_code": "CAD",
                },
            )

    resp = asyncio.run(_run())

    assert resp.status_code == 422
    assert "dim_stock symbol collision" in resp.json()["detail"]

    app.dependency_overrides.pop(get_db, None)
