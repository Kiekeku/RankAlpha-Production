from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.database import get_db
from apps.api.src.routers import portfolio as portfolio_router
from apps.api.src.security import dependencies as security_dependencies


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()
    yield
    security_dependencies._get_settings.cache_clear()


@pytest.fixture
def dummy_db():
    class DummySession:
        def begin(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def close(self):
            pass

    def _get_db():
        yield DummySession()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def test_portfolio_list_runs_requires_admin_and_filter(dummy_db):
    async def _run_forbidden():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/portfolio/runs")

    resp = asyncio.run(_run_forbidden())
    assert resp.status_code == 403

    async def _run_ok():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v1/portfolio/runs",
                headers={"X-RA-Service-Token": "service-token"},
            )

    resp_ok = asyncio.run(_run_ok())
    assert resp_ok.status_code == 422
    assert resp_ok.json()["detail"] == "Provide portfolio_id or as_of_date"


def test_portfolio_trade_recommendations_requires_admin(dummy_db, monkeypatch):
    async def _run_forbidden():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/portfolio/trade-recommendations")

    resp = asyncio.run(_run_forbidden())
    assert resp.status_code == 403

    stub = SimpleNamespace(
        recommendation_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        recommendation_date=date(2025, 10, 7),
        symbol="AAPL",
        source_name="UnitTest",
        source_version="1",
        action="BUY",
        recommended_price=182.45,
        order_type="LIMIT",
        time_in_force="DAY",
        limit_price=182.55,
        stop_trigger_price=None,
        stop_loss_price=175.0,
        take_profit_price=195.0,
        size_shares=10,
        size_percent=2.5,
        strategy_name="Breakout-Q4",
        is_live=False,
        create_ts=None,
    )
    monkeypatch.setattr(portfolio_router, "get_trade_recommendations_view", lambda *_args, **_kwargs: [stub])

    async def _run_ok():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v1/portfolio/trade-recommendations?limit=5&is_live=false",
                headers={"X-RA-Service-Token": "service-token"},
            )

    resp_ok = asyncio.run(_run_ok())
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert len(body) == 1
    assert body[0]["symbol"] == "AAPL"
    assert body[0]["action"] == "BUY"


def test_portfolio_create_run_returns_id(dummy_db, monkeypatch):
    run_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    stub_run = SimpleNamespace(run_id=run_id, run_seq=3)
    monkeypatch.setattr(portfolio_router, "create_portfolio_run", lambda *_args, **_kwargs: stub_run)

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/portfolio/runs",
                headers={"X-RA-Service-Token": "service-token"},
                json={
                    "portfolio_id": str(uuid.uuid4()),
                    "run_kind": "MODEL_CONSTRUCTION",
                    "as_of_date": "2025-10-07",
                },
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 201
    body = resp.json()
    assert body["run_id"] == str(run_id)
    assert body["run_seq"] == 3


def test_portfolio_create_deployment_allows_over_100_allocation(dummy_db, monkeypatch):
    deployment_id = uuid.UUID("12345678-1234-1234-1234-1234567890ab")
    sleeve_id = uuid.UUID("87654321-4321-4321-4321-ba0987654321")
    captured: dict[str, object] = {}

    def fake_create_deployment(*_args, **kwargs):
        captured.update(kwargs)
        return deployment_id, sleeve_id

    monkeypatch.setattr(portfolio_router, "get_or_create_deployment", fake_create_deployment)

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/portfolio/deployments",
                headers={"X-RA-Service-Token": "service-token"},
                json={
                    "broker_portfolio_id": str(uuid.uuid4()),
                    "model_portfolio_id": str(uuid.uuid4()),
                    "allocation_pct": 150.0,
                    "effective_from": "2026-01-16",
                },
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 201
    body = resp.json()
    assert body["deployment_id"] == str(deployment_id)
    assert body["sleeve_portfolio_id"] == str(sleeve_id)
    assert float(captured["allocation_pct"]) == 150.0


def test_portfolio_approve_run_maps_value_error(dummy_db, monkeypatch):
    def fake_approve(*_args, **_kwargs):
        raise ValueError("Run has 1 unapproved order(s)")

    monkeypatch.setattr(portfolio_router, "approve_run", fake_approve)

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                f"/api/v1/portfolio/runs/{uuid.uuid4()}/approve",
                headers={"X-RA-Service-Token": "service-token"},
                json={},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Run has 1 unapproved order(s)"
