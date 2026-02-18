from __future__ import annotations

import asyncio

from apps.api.src.database import get_db
from apps.api.src.main import app
from apps.api.src.routers import prices
from apps.api.src.services.prices.cache import PriceHistoryCacheEntry
from httpx import ASGITransport, AsyncClient


def _dummy_db():
    class DummySession:
        def close(self):  # pragma: no cover - compatibility
            pass

    yield DummySession()


def test_prices_history_cache_fast_path_no_date_filters(monkeypatch):
    entry = PriceHistoryCacheEntry(
        symbol="AAPL",
        items=[
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-03", "close_px": 3},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-02", "close_px": 2},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-01", "close_px": 1},
        ],
        total_count=3,
        last_trade_date="2025-01-03",
        refreshed_at="2025-01-03T00:00:00Z",
        etag="etag",
    )

    monkeypatch.setattr(prices.price_cache, "get_head", lambda _symbol: entry)
    monkeypatch.setattr(prices.price_cache, "get", lambda _symbol: None)
    monkeypatch.setattr(prices.price_cache, "warm", lambda *_args, **_kwargs: None)
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/prices/history",
                    params={"symbol": "AAPL", "skip": 1, "limit": 1},
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 3
        assert len(body["items"]) == 1
        assert body["items"][0]["price_date"] == "2025-01-02"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_prices_history_cache_filtered_path_counts_and_pages(monkeypatch):
    entry = PriceHistoryCacheEntry(
        symbol="AAPL",
        items=[
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-05", "close_px": 5},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-04", "close_px": 4},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-03", "close_px": 3},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-02", "close_px": 2},
            {"symbol": "AAPL", "company_name": "Apple", "price_date": "2025-01-01", "close_px": 1},
        ],
        total_count=5,
        last_trade_date="2025-01-05",
        refreshed_at="2025-01-05T00:00:00Z",
        etag="etag",
    )

    monkeypatch.setattr(prices.price_cache, "get_head", lambda _symbol: None)
    monkeypatch.setattr(prices.price_cache, "get", lambda _symbol: entry)
    app.dependency_overrides[get_db] = _dummy_db
    try:
        async def _run():
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.get(
                    "/api/v1/prices/history",
                    params={
                        "symbol": "AAPL",
                        "date_from": "2025-01-02",
                        "date_to": "2025-01-04",
                        "skip": 1,
                        "limit": 1,
                    },
                )

        resp = asyncio.run(_run())
        assert resp.status_code == 200
        body = resp.json()
        # Range includes 2025-01-04, 2025-01-03, 2025-01-02
        assert body["total_count"] == 3
        assert len(body["items"]) == 1
        assert body["items"][0]["price_date"] == "2025-01-03"
    finally:
        app.dependency_overrides.pop(get_db, None)
