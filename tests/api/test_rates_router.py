from __future__ import annotations

import asyncio
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.database import get_db
from apps.api.src.main import app

def _dummy_db():
    class DummyResult:
        def scalar_one(self):
            return 0

        def scalars(self):
            return self

        def all(self):
            return []

    class DummySession:
        def execute(self, stmt):
            return DummyResult()

        def close(self):
            pass

    try:
        yield DummySession()
    finally:
        pass


def test_treasury_series_accepts_lowercase_tenor():
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/rates/treasury/series", params={"tenor": "10y", "limit": 5}
                )

        resp = asyncio.run(_run())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["tenor"] == "10Y"
    assert payload["items"] == []


def test_treasury_series_accepts_overnight_tenor():
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/rates/treasury/series", params={"tenor": "O/N", "limit": 5}
                )

        resp = asyncio.run(_run())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["tenor"] == "O/N"
    assert payload["items"] == []
