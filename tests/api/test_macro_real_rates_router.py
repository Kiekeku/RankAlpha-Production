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


def test_tips10y_real_yield_series_endpoint_returns_payload():
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/macro/real-rates/tips10y/series", params={"limit": 5}
                )

        resp = asyncio.run(_run())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["series"] == "tips10y"
    assert payload["items"] == []
