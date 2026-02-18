from __future__ import annotations

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.routers import admin as admin_router
from apps.api.src.security import dependencies as security_dependencies


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer admin-token"}


def test_admin_prices_cache_refresh_accepts_chunk_size(monkeypatch):
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()
    admin_router._get_settings.cache_clear()

    def dummy_warm(symbols: list[str], *, force: bool, reason: str | None, as_of: str | None) -> None:
        return None

    monkeypatch.setattr(admin_router, "_warm_price_cache_batch", dummy_warm)

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/admin/prices/cache-refresh",
                headers=_auth_headers(),
                json={"symbols": ["AAPL", "MSFT", "GOOG"], "chunk_size": 2, "reason": "test"},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    body = resp.json()
    assert body["requested"] == 3
    assert body["enqueued"] == 3
    assert body["batches"] == 2


def test_admin_prices_cache_refresh_defaults_chunk_size(monkeypatch):
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()
    admin_router._get_settings.cache_clear()

    def dummy_warm(_symbols: list[str], *, force: bool, reason: str | None, as_of: str | None) -> None:
        return None

    monkeypatch.setattr(admin_router, "_warm_price_cache_batch", dummy_warm)

    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/admin/prices/cache-refresh",
                headers=_auth_headers(),
                json={"symbols": ["AAPL", "MSFT", "GOOG"]},
            )

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.json()["batches"] == 1
