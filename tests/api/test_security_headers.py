from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


def test_security_headers_present_on_openapi():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/openapi.json")

    resp = asyncio.run(_run())
    assert resp.status_code == 200
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"

