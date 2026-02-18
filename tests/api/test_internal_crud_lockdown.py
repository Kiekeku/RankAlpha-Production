from __future__ import annotations

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.database import get_db
from apps.api.src.security import dependencies as security_dependencies

def _dummy_db(items=None):
    class DummyScalarResult:
        def __init__(self, values):
            self._values = values

        def all(self):
            return list(self._values)

    class DummySession:
        def scalars(self, *_args, **_kwargs):
            return DummyScalarResult(items or [])

        def get(self, *_args, **_kwargs):
            return None

        def close(self):
            pass

    yield DummySession()


def test_public_autocrud_routes_removed():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/dim_stock/")

    resp = asyncio.run(_run())
    assert resp.status_code == 404


def test_internal_autocrud_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", "admin-token")
    security_dependencies._get_settings.cache_clear()

    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/internal/dim_stock/")

        resp_forbidden = asyncio.run(_run())
        assert resp_forbidden.status_code == 403

        async def _run_ok():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/internal/dim_stock/",
                    headers={"Authorization": "Bearer admin-token"},
                )

        resp_ok = asyncio.run(_run_ok())
        assert resp_ok.status_code == 200
        assert resp_ok.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        security_dependencies._get_settings.cache_clear()
