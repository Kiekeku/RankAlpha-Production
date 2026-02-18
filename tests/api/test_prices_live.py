from __future__ import annotations

import asyncio

import pytest

from apps.api.src.routers import prices


@pytest.fixture(autouse=True)
def _disable_broker_quiet_hours(monkeypatch):
    monkeypatch.setenv("BROKER_SENTRY_QUIET_HOURS_ENABLED", "false")
    yield


def test_live_price_endpoint_proxies_broker(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_service_timeout_seconds = 4
        broker_service_token = "test-broker-token"

    class DummyResponse:
        status_code = 200

        def json(self):
            return {
                "symbol": "AAPL",
                "account": "DU-changeme",
                "bid": 208.77,
                "ask": 208.79,
                "last": 208.78,
                "close": 207.99,
                "raw": {"55": "208.77"},
            }

    class DummyClient:
        async def get(self, url, params=None, headers=None, timeout=None):
            assert url == "http://broker.internal:8000/price/AAPL"
            assert params == {"account": "DU-changeme"}
            assert headers == {"X-RA-Service-Token": "test-broker-token"}
            assert timeout == 4.0
            return DummyResponse()

    monkeypatch.setattr(prices, "get_async_client", lambda: DummyClient())
    settings = StubSettings()

    async def _run():
        out = await prices._request_broker_live_price(
            "AAPL",
            account="DU-changeme",
            exchange=None,
            settings=settings,  # type: ignore[arg-type]
        )
        assert out["symbol"] == "AAPL"
        assert out["bid"] == 208.77
        assert out["ask"] == 208.79
        assert out["account"] == "DU-changeme"
        assert out["raw"] == {"55": "208.77"}

    asyncio.run(_run())


def test_live_price_requires_broker_token(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_service_timeout_seconds = 4
        broker_service_token = None

    monkeypatch.setattr(prices.httpx, "AsyncClient", object())

    async def _run():
        try:
            await prices._request_broker_live_price(
                "AAPL",
                account=None,
                exchange=None,
                settings=StubSettings(),  # type: ignore[arg-type]
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 503
            assert "BROKER_SERVICE_TOKEN" in str(getattr(exc, "detail", ""))
        else:
            raise AssertionError("Expected HTTPException")

    asyncio.run(_run())


def test_get_live_price_does_not_hit_broker_for_anonymous(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_price_cache_seconds = 10
        admin_bearer_token = None
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())
    monkeypatch.setattr(prices, "get_json", lambda _key: {"is_realtime": True, "symbol": "AAPL"})

    fallback = prices.LivePrice(
        symbol="AAPL", close=123.45, is_realtime=False, raw={"source": "close"}
    ).model_dump()
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda _db, _sym: fallback)
    monkeypatch.setattr(prices, "_schedule_live_price_prefetch", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("prefetch should not run for anonymous")))  # type: ignore[misc]

    async def _no_broker(*args, **kwargs):
        raise AssertionError("broker call should not run for anonymous")

    monkeypatch.setattr(prices, "_request_broker_live_price", _no_broker)

    async def _run():
        out = await prices.get_live_price(  # type: ignore[misc]
            "AAPL",
            account=None,
            exchange=None,
            db=object(),
            principal=None,
            authorization=None,
        )
        assert out["symbol"] == "AAPL"
        assert out["is_realtime"] is False
        assert out["close"] == 123.45

    asyncio.run(_run())


def test_get_live_price_does_not_serve_ambiguous_cache_to_anonymous(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_price_cache_seconds = 10
        admin_bearer_token = None
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())
    # Legacy/malformed cache entry without `is_realtime` must not be served to anonymous.
    monkeypatch.setattr(prices, "get_json", lambda _key: {"symbol": "AAPL", "last": 999.0})

    fallback = prices.LivePrice(
        symbol="AAPL", close=123.45, is_realtime=False, raw={"source": "close"}
    ).model_dump()
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda _db, _sym: fallback)

    async def _no_broker(*args, **kwargs):
        raise AssertionError("broker call should not run for anonymous")

    monkeypatch.setattr(prices, "_request_broker_live_price", _no_broker)

    async def _run():
        out = await prices.get_live_price(  # type: ignore[misc]
            "AAPL",
            account=None,
            exchange=None,
            db=object(),
            principal=None,
            authorization=None,
        )
        assert out["symbol"] == "AAPL"
        assert out["is_realtime"] is False
        assert out["close"] == 123.45

    asyncio.run(_run())


def test_get_live_price_returns_fallback_when_broker_not_configured(monkeypatch):
    class StubSettings:
        broker_service_url = None
        broker_service_token = None
        broker_price_cache_seconds = 10
        admin_bearer_token = None
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())
    monkeypatch.setattr(prices, "get_json", lambda _key: None)

    fallback = prices.LivePrice(
        symbol="AAPL", close=123.45, is_realtime=False, raw={"source": "close"}
    ).model_dump()
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda _db, _sym: fallback)

    monkeypatch.setattr(
        prices,
        "_schedule_live_price_prefetch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("prefetch should not run when broker is not configured")
        ),
    )

    async def _no_broker(*args, **kwargs):
        raise AssertionError("broker call should not run when broker is not configured")

    monkeypatch.setattr(prices, "_request_broker_live_price", _no_broker)

    async def _run():
        out = await prices.get_live_price(  # type: ignore[misc]
            "AAPL",
            account=None,
            exchange=None,
            db=object(),
            principal=object(),
            authorization=None,
        )
        assert out["symbol"] == "AAPL"
        assert out["is_realtime"] is False
        assert out["close"] == 123.45

    asyncio.run(_run())


def test_get_live_price_allows_internal_bearer(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_price_cache_seconds = 10
        admin_bearer_token = "admin-token"
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())
    monkeypatch.setattr(prices, "get_json", lambda _key: None)
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda _db, _sym: None)

    async def _broker(*args, **kwargs):
        return {"symbol": "AAPL", "last": 123.0, "is_realtime": True, "raw": {}}

    monkeypatch.setattr(prices, "_request_broker_live_price", _broker)
    monkeypatch.setattr(prices, "_cache_live_price", lambda *args, **kwargs: None)

    async def _run():
        out = await prices.get_live_price(  # type: ignore[misc]
            "AAPL",
            account=None,
            exchange=None,
            db=object(),
            principal=None,
            authorization="Bearer admin-token",
        )
        assert out["is_realtime"] is True
        assert out["symbol"] == "AAPL"

    asyncio.run(_run())


def test_get_live_price_requires_auth_when_no_fallback(monkeypatch):
    class StubSettings:
        broker_service_url = "http://broker.internal:8000"
        broker_price_cache_seconds = 10
        admin_bearer_token = None
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())
    monkeypatch.setattr(prices, "get_json", lambda _key: None)
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda _db, _sym: None)

    async def _no_broker(*args, **kwargs):
        raise AssertionError("broker call should not run for anonymous")

    monkeypatch.setattr(prices, "_request_broker_live_price", _no_broker)

    async def _run():
        try:
            await prices.get_live_price(  # type: ignore[misc]
                "AAPL",
                account=None,
                exchange=None,
                db=object(),
                principal=None,
                authorization=None,
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 401
        else:
            raise AssertionError("Expected HTTPException")

    asyncio.run(_run())


def test_guard_live_price_allows_realtime_outlier(monkeypatch):
    payload = {"symbol": "AAPL", "last": 1000.0, "is_realtime": True, "raw": {}}
    fallback = {"symbol": "AAPL", "close": 100.0, "is_realtime": False, "raw": {"source": "close"}}
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda *_args, **_kwargs: fallback)

    out = prices._guard_live_price(object(), "AAPL", payload)
    assert out["last"] == 1000.0
    assert out["raw"]["fallback_close"] == 100.0


def test_guard_live_price_replaces_non_realtime_outlier(monkeypatch):
    payload = {"symbol": "AAPL", "last": 1000.0, "is_realtime": False, "raw": {}}
    fallback = {"symbol": "AAPL", "close": 100.0, "is_realtime": False, "raw": {"source": "close"}}
    monkeypatch.setattr(prices, "_latest_close_snapshot", lambda *_args, **_kwargs: fallback)

    out = prices._guard_live_price(object(), "AAPL", payload)
    assert out["close"] == 100.0


def test_get_latest_skips_broker_for_anonymous(monkeypatch):
    class StubSettings:
        broker_service_timeout_seconds = 4
        cache_ttl_default = 300
        admin_bearer_token = None
        auth_service_token = None

    monkeypatch.setattr(prices, "Settings", lambda: StubSettings())

    def _should_not_call(*args, **kwargs):
        raise AssertionError("broker call should be skipped for anonymous")

    monkeypatch.setattr(prices, "_try_broker_latest", _should_not_call)

    cached = {
        "items": [{"symbol": "AAPL", "price_date": "2026-01-01", "close_px": 100, "adj_close_px": 100}],
        "total_count": 1,
        "page": 1,
        "page_size": 200,
    }
    monkeypatch.setattr(prices, "get_json", lambda _key: cached)

    out = prices.get_latest(  # type: ignore[misc]
        db=object(),
        symbol="AAPL",
        skip=0,
        limit=200,
        sort_by="symbol",
        sort_order="asc",
        prefer_live=True,
        principal=None,
        authorization=None,
    )
    assert out == cached
