from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.database import get_db
from apps.api.src.routers import portfolios as portfolios_router
from apps.api.src.security import dependencies as security_dependencies


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(secret: str, *, user_id: int, email: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"userId": user_id, "email": email}
    signing_input = ".".join(
        _urlsafe_b64(json.dumps(segment, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        for segment in (header, payload)
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_urlsafe_b64(signature)}"


@dataclass
class StubUser:
    user_id: int
    email: str
    is_active: bool = True
    full_name: str | None = None
    provider: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StubRepo:
    def __init__(self, users: dict[int, StubUser], roles: dict[int, list[str]] | None = None):
        self._users = users
        self._roles = roles or {}

    def get_user_by_id(self, user_id: int):
        return self._users.get(user_id)

    def get_roles_for_user(self, user: StubUser) -> list[str]:
        return self._roles.get(user.user_id, [])


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()
    yield
    security_dependencies._get_settings.cache_clear()


@pytest.fixture
def db_override():
    class FakeSession:
        def __init__(self, portfolio):
            self._portfolio = portfolio

        def get(self, model, key):
            from apps.common.src.models import Portfolio as PortfolioModel

            if model is PortfolioModel and key == self._portfolio.portfolio_id:
                return self._portfolio
            return None

        def close(self):  # pragma: no cover - FastAPI calls it defensively
            pass

    def apply(portfolio):
        def _get_db():
            yield FakeSession(portfolio)

        app.dependency_overrides[get_db] = _get_db

    yield apply
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def auth_repo_override(monkeypatch):
    def apply(repo):
        monkeypatch.setattr(security_dependencies, "AuthRepository", lambda db: repo)

    yield apply


def test_public_portfolio_performance_no_auth_ok(db_override, monkeypatch):
    portfolio_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_name="Model-Public",
        portfolio_kind="MODEL",
        currency_code="USD",
        is_public=True,
        is_visible=True,
        portfolio_owner_id=None,
        description=None,
    )
    db_override(portfolio)

    stub_row = SimpleNamespace(
        full_date=date(2026, 1, 16),
        nav_base_ccy=100.0,
        daily_return=0.01,
    )
    monkeypatch.setattr(
        portfolios_router,
        "get_portfolio_performance_view",
        lambda *_args, **_kwargs: [stub_row],
    )

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(f"/api/v1/portfolios/{portfolio_id}/performance")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["nav_base_ccy"] == 100.0


def test_private_portfolio_performance_no_auth_404(db_override, monkeypatch):
    portfolio_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_name="Model-Private",
        portfolio_kind="MODEL",
        currency_code="USD",
        is_public=False,
        is_visible=False,
        portfolio_owner_id=1,
        description=None,
    )
    db_override(portfolio)

    monkeypatch.setattr(
        portfolios_router,
        "get_portfolio_performance_view",
        lambda *_args, **_kwargs: [],
    )

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(f"/api/v1/portfolios/{portfolio_id}/performance")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_private_portfolio_performance_owner_ok(db_override, auth_repo_override, monkeypatch):
    portfolio_id = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    portfolio = SimpleNamespace(
        portfolio_id=portfolio_id,
        portfolio_name="Model-Private",
        portfolio_kind="MODEL",
        currency_code="USD",
        is_public=False,
        is_visible=False,
        portfolio_owner_id=1,
        description=None,
    )
    db_override(portfolio)

    users = {1: StubUser(user_id=1, email="owner@example.com")}
    auth_repo_override(StubRepo(users, {1: ["viewer"]}))

    stub_row = SimpleNamespace(
        full_date=date(2026, 1, 16),
        nav_base_ccy=100.0,
        daily_return=None,
    )
    monkeypatch.setattr(
        portfolios_router,
        "get_portfolio_performance_view",
        lambda *_args, **_kwargs: [stub_row],
    )

    token = _make_token("test-secret", user_id=1, email="owner@example.com")

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                f"/api/v1/portfolios/{portfolio_id}/performance",
                headers={"Authorization": f"Bearer {token}"},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()[0]["nav_base_ccy"] == 100.0

