from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app
from apps.api.src.database import get_db
from apps.api.src.routers import news_ingest
from apps.api.src.security import dependencies as security_dependencies

def _set_admin_token(monkeypatch, token: str = "admin-token") -> None:
    monkeypatch.setenv("ADMIN_BEARER_TOKEN", token)
    security_dependencies._get_settings.cache_clear()


def _dummy_db():
    class DummySession:
        def close(self):
            pass

    try:
        yield DummySession()
    finally:
        pass


def test_news_suggestions_requires_admin_token():
    async def _run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/news/suggestions")

    resp = asyncio.run(_run())
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin privileges required"


def test_dedupe_endpoint_returns_payload(monkeypatch):
    _set_admin_token(monkeypatch, "super-secret")
    app.dependency_overrides[get_db] = _dummy_db

    fake_match_id = uuid.uuid4()

    def fake_find_matches(db, **kwargs):
        return [
            {
                "match_type": "url",
                "url": "https://example.com/a",
                "published_at": datetime(2025, 11, 2, 14, 30, tzinfo=timezone.utc),
                "source_domain": "example.com",
                "raw_id": fake_match_id,
                "event_id": None,
            }
        ]

    monkeypatch.setattr(news_ingest, "find_existing_raw_matches", fake_find_matches)

    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.post(
                    "/api/v1/news/suggestions/dedupe-check",
                    headers={"Authorization": "Bearer super-secret"},
                    json={"url": "https://example.com/a?foo=1", "title": "Hello"},
                )

        resp = asyncio.run(_run())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["matches"][0]["match_type"] == "url"
    assert payload["matches"][0]["url"] == "https://example.com/a"
    assert payload["matches"][0]["raw_id"] == str(fake_match_id)
