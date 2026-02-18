from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from apps.api.src import metrics


class _CounterSpy:
    def __init__(self) -> None:
        self.records: list[dict[str, str]] = []

    def labels(self, **labels: str):  # type: ignore[no-untyped-def]
        spy = self

        class _Labelled:
            def inc(self) -> None:
                spy.records.append(labels)

        return _Labelled()


def test_classify_client_from_scope() -> None:
    scope_bot = {
        "headers": [(b"user-agent", b"python-requests/2.31.0")],
    }
    scope_browser = {
        "headers": [(b"user-agent", b"Mozilla/5.0 (Macintosh; Intel Mac OS X)")],
    }
    scope_unknown = {"headers": []}

    assert metrics.classify_client_from_scope(scope_bot) == "bot"
    assert metrics.classify_client_from_scope(scope_browser) == "browser"
    assert metrics.classify_client_from_scope(scope_unknown) == "unknown"


def test_resolve_handler_from_scope_prefers_route_template() -> None:
    route = type("Route", (), {"path": "/api/v1/prices/{symbol}"})()
    assert metrics.resolve_handler_from_scope({"route": route}) == "/api/v1/prices/{symbol}"
    assert metrics.resolve_handler_from_scope({"path": "/api/v1/prices/AAPL"}) == "/__unmatched__"


def test_api_metrics_middleware_tracks_endpoint_and_scraper_class(monkeypatch) -> None:
    requests_total = _CounterSpy()
    endpoint_total = _CounterSpy()
    endpoint_by_client_total = _CounterSpy()

    monkeypatch.setattr(metrics, "API_REQUESTS_TOTAL", requests_total)
    monkeypatch.setattr(metrics, "API_ENDPOINT_REQUESTS_TOTAL", endpoint_total)
    monkeypatch.setattr(metrics, "API_ENDPOINT_REQUESTS_BY_CLIENT_TOTAL", endpoint_by_client_total)

    app = FastAPI()
    app.add_middleware(metrics.APIMetricsMiddleware)

    @app.get("/api/v1/prices/{symbol}")
    async def _prices(symbol: str):  # type: ignore[no-untyped-def]
        return {"symbol": symbol}

    async def _run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.get(
                "/api/v1/prices/AAPL?limit=10",
                headers={"User-Agent": "python-requests/2.31.0"},
            )
            await client.get("/metrics", headers={"User-Agent": "curl/8.5.0"})

    asyncio.run(_run())

    assert requests_total.records == [
        {
            "handler": "/api/v1/prices/{symbol}",
            "method": "GET",
            "status_code": "200",
        }
    ]
    assert endpoint_total.records == [
        {
            "handler": "/api/v1/prices/{symbol}",
            "method": "GET",
        }
    ]
    assert endpoint_by_client_total.records == [
        {
            "handler": "/api/v1/prices/{symbol}",
            "method": "GET",
            "client_class": "bot",
        }
    ]
