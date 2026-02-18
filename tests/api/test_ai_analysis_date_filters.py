from __future__ import annotations

import asyncio

from apps.api.src.database import get_db
from apps.api.src.main import app
from apps.api.src.routers import ai_analysis
from httpx import ASGITransport, AsyncClient


class _DummySession:
    def close(self):  # pragma: no cover - compatibility
        pass


def _dummy_db():
    yield _DummySession()


def test_ai_analysis_list_rejects_invalid_date_from(monkeypatch):
    monkeypatch.setattr(ai_analysis, "get_json", lambda _key: None)
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/ai-analysis", params={"date_from": "2025/01/01"})

        resp = asyncio.run(_run())
        assert resp.status_code == 400
        assert resp.json().get("detail") == "Invalid date_from format. Use YYYY-MM-DD"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ai_analysis_latest_rejects_invalid_date_to(monkeypatch):
    monkeypatch.setattr(ai_analysis, "get_json", lambda _key: None)
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get("/api/v1/ai-analysis/latest", params={"date_to": "2025-13-01"})

        resp = asyncio.run(_run())
        assert resp.status_code == 400
        assert resp.json().get("detail") == "Invalid date_to format. Use YYYY-MM-DD"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ai_analysis_latest_rejects_inverted_date_range(monkeypatch):
    monkeypatch.setattr(ai_analysis, "get_json", lambda _key: None)
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/ai-analysis/latest",
                    params={"date_from": "2025-02-01", "date_to": "2025-01-31"},
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 400
        assert resp.json().get("detail") == "date_from must be <= date_to"
    finally:
        app.dependency_overrides.pop(get_db, None)
