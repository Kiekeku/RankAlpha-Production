from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient

from apps.api.src.database import get_db
from apps.api.src.main import app


class _DummyResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DummySession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _DummyResult(self._rows)

    def close(self):  # pragma: no cover - compatibility
        pass


def _dummy_db(rows):
    def _override():
        yield _DummySession(rows)

    return _override


def test_ai_preview_enforces_max_symbols(monkeypatch):
    monkeypatch.setenv("AI_PREVIEW_MAX_SYMBOLS", "2")
    app.dependency_overrides[get_db] = _dummy_db(
        [
            ("AAPL", 210.0, [{"id": 1}, {"id": 2}], "bull", None, None),
        ]
    )
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/ai-analysis/preview",
                    params=[("symbols", "AAPL"), ("symbols", "MSFT"), ("symbols", "GOOG")],
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 400
        assert "Too many symbols" in resp.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_ai_preview_returns_mapping(monkeypatch):
    monkeypatch.setenv("AI_PREVIEW_MAX_SYMBOLS", "10")
    app.dependency_overrides[get_db] = _dummy_db(
        [
            ("AAPL", 210.0, 2, True),
            ("MSFT", None, 0, False),
        ]
    )
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/ai-analysis/preview",
                    params=[("symbols", "AAPL"), ("symbols", "MSFT")],
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["AAPL"]["events_count"] == 2
        assert body["AAPL"]["base_price_target"] == 210.0
        assert body["AAPL"]["has_thesis"] is True
        assert body["MSFT"]["base_price_target"] is None
        assert body["MSFT"]["has_thesis"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
