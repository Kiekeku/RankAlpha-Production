from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.security import dependencies as security_dependencies

@dataclass
class StubUser:
    user_id: int
    email: str
    full_name: str | None = None
    avatar_url: str | None = None
    provider: str | None = None
    provider_account_id: str | None = None
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StubRepo:
    def __init__(self, users: Dict[int, StubUser], roles: Dict[int, List[str]] | None = None):
        self._users = users
        self._roles = roles or {}

    # AuthRepository interface subset
    def get_user_by_id(self, user_id: int):
        return self._users.get(user_id)

    def get_roles_for_user(self, user: StubUser) -> List[str]:
        return self._roles.get(user.user_id, [])

    def list_users(self, search: str | None = None) -> List[StubUser]:
        return list(self._users.values())

    def get_user_by_email(self, email: str):  # pragma: no cover - not needed in these tests
        for user in self._users.values():
            if user.email.lower() == email.lower():
                return user
        return None

    def add_user(self, *args, **kwargs):  # pragma: no cover - not used here
        raise NotImplementedError

    def set_user_roles(self, user: StubUser, target_roles, assigned_by=None):
        valid = {"viewer", "analyst", "operator", "admin"}
        normalized = [role.lower() for role in target_roles]
        unknown = sorted({role for role in normalized if role not in valid})
        if unknown:
            raise ValueError(f"Unknown roles requested: {', '.join(unknown)}")
        self._roles[user.user_id] = normalized
        return self._roles[user.user_id]


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(secret: str, *, user_id: int, email: str, roles: Iterable[str] | None = None) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "userId": user_id,
        "email": email,
        "roles": list(roles or []),
    }
    signing_input = ".".join(
        _urlsafe_b64(json.dumps(segment, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        for segment in (header, payload)
    )
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_urlsafe_b64(signature)}"


@pytest.fixture(autouse=True)
def configure_env(monkeypatch):
    monkeypatch.setenv("NEXTAUTH_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_SERVICE_TOKEN", "service-token")
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()
    yield
    security_dependencies._get_settings.cache_clear()


@pytest.fixture
def repo_override(monkeypatch):
    class DummySession:
        def close(self):
            pass

    def apply(repo):
        app.dependency_overrides[security_dependencies.get_auth_repository] = lambda: repo
        monkeypatch.setattr(security_dependencies, "AuthRepository", lambda db: repo)
        monkeypatch.setattr("apps.api.src.database.SessionLocal", lambda: DummySession())

    yield apply
    app.dependency_overrides.pop(security_dependencies.get_auth_repository, None)


def test_auth_me_requires_token(repo_override):
    users = {1: StubUser(user_id=1, email="user@example.com")}
    repo_override(StubRepo(users, {1: ["viewer"]}))

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/auth/me")

    resp = asyncio.run(_run())
    assert resp.status_code == 401


def test_auth_me_returns_principal(repo_override):
    users = {1: StubUser(user_id=1, email="user@example.com", full_name="Test User")}
    repo_override(StubRepo(users, {1: ["viewer", "analyst"]}))

    token = _make_token("test-secret", user_id=1, email="user@example.com", roles=["viewer"])
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    resp = asyncio.run(_run())

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "user@example.com"
    assert set(body["roles"]) == {"viewer", "analyst"}


def test_admin_listing_requires_admin_role(repo_override):
    users = {
        1: StubUser(user_id=1, email="admin@example.com"),
        2: StubUser(user_id=2, email="user@example.com"),
    }
    repo_override(StubRepo(users, {1: ["admin"], 2: ["viewer"]}))

    user_token = _make_token("test-secret", user_id=2, email="user@example.com", roles=["viewer"])
    async def _run_forbidden():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {user_token}"})

    resp = asyncio.run(_run_forbidden())
    assert resp.status_code == 403

    admin_token = _make_token("test-secret", user_id=1, email="admin@example.com", roles=["admin"])
    async def _run_admin():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/auth/users", headers={"Authorization": f"Bearer {admin_token}"})

    resp_admin = asyncio.run(_run_admin())
    assert resp_admin.status_code == 200
    assert len(resp_admin.json()) == 2


def test_service_token_can_access_admin_routes(repo_override):
    users = {1: StubUser(user_id=1, email="service@example.com")}
    repo_override(StubRepo(users, {1: ["viewer"]}))

    from apps.api.src.settings import Settings

    settings = Settings()
    assert settings.auth_service_token == "service-token"

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/v1/auth/users",
                headers={
                    "Authorization": "Bearer service-token",
                    "X-RA-Service-Token": "service-token",
                },
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200


def test_replace_roles_returns_400_for_unknown_roles(repo_override):
    users = {
        1: StubUser(user_id=1, email="admin@example.com"),
        2: StubUser(user_id=2, email="user@example.com"),
    }
    repo_override(StubRepo(users, {1: ["admin"], 2: ["viewer"]}))

    admin_token = _make_token("test-secret", user_id=1, email="admin@example.com", roles=["admin"])

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.put(
                "/api/v1/auth/users/2/roles",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"roles": ["bogus"]},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 400
    body = resp.json()
    assert "Unknown roles" in body["detail"]
