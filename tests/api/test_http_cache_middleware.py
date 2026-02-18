from __future__ import annotations

import asyncio

import httpx
import pytest
from apps.api.src import http_cache
from fastapi import FastAPI, Query
from starlette.responses import JSONResponse, PlainTextResponse


class _DummySettings:
    http_cache_enabled = True
    cache_ttl_default = 180
    cache_ttl_prices_latest = 123
    broker_price_cache_seconds = 10
    cache_ttl_rankings = 300
    cache_ttl_stock_detail = 600
    cache_ttl_top_performers = 300


@pytest.fixture(autouse=True)
def _enable_cache(monkeypatch):
    monkeypatch.setattr(http_cache, "Settings", lambda: _DummySettings())
    monkeypatch.setattr(http_cache, "ping_redis", lambda: True)
    monkeypatch.setattr(http_cache, "is_cache_disabled", lambda: False)


@pytest.fixture(autouse=True)
def _restore_cache_funcs():
    orig_get = http_cache.get_json
    orig_set = http_cache.set_json
    yield
    http_cache.get_json = orig_get  # type: ignore[assignment]
    http_cache.set_json = orig_set  # type: ignore[assignment]


def test_http_cache_caches_get_json_200_and_varies_by_auth_cookie(monkeypatch):
    store: dict[str, object] = {}
    keys_written: list[str] = []
    ttls: list[int | None] = []
    keys_read: list[str] = []

    def get_json(key: str):  # type: ignore[no-untyped-def]
        keys_read.append(key)
        return store.get(key)

    def set_json(key: str, value, ttl_secs=None):  # type: ignore[no-untyped-def]
        keys_written.append(key)
        ttls.append(ttl_secs)
        store[key] = value

    monkeypatch.setattr(http_cache, "get_json", get_json)
    monkeypatch.setattr(http_cache, "set_json", set_json)

    app = FastAPI()
    app.add_middleware(http_cache.RedisHTTPCacheMiddleware)
    calls = {"n": 0}

    @app.get("/api/v1/prices/latest")
    async def latest():  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return JSONResponse({"ok": True, "n": calls["n"]})

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get(
                "/api/v1/prices/latest",
                headers={"Authorization": "Bearer A", "Cookie": "sid=1"},
            )
            r2 = await client.get(
                "/api/v1/prices/latest",
                headers={"Authorization": "Bearer A", "Cookie": "sid=1"},
            )
            r3 = await client.get(
                "/api/v1/prices/latest",
                headers={"Authorization": "Bearer B", "Cookie": "sid=1"},
            )
            return r1, r2, r3

    r1, r2, r3 = asyncio.run(_run())
    assert r1.status_code == 200 and r1.json()["n"] == 1
    assert r2.status_code == 200 and r2.json()["n"] == 1  # cached
    assert r3.status_code == 200 and r3.json()["n"] == 2  # auth differs -> new key
    assert calls["n"] == 2
    assert len(set(keys_written)) == 2
    assert all(t == _DummySettings.cache_ttl_prices_latest for t in ttls)
    assert keys_written[0] in keys_read
    assert keys_written[0] == keys_read[0] == keys_read[1]


def test_http_cache_respects_no_cache_header():
    store: dict[str, object] = {}

    http_cache.get_json = lambda key: store.get(key)  # type: ignore[assignment]
    http_cache.set_json = lambda key, value, ttl_secs=None: store.__setitem__(key, value)  # type: ignore[assignment]

    app = FastAPI()
    app.add_middleware(http_cache.RedisHTTPCacheMiddleware)
    calls = {"n": 0}

    @app.get("/api/v1/prices/latest")
    async def latest():  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {"ok": True, "n": calls["n"]}

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/api/v1/prices/latest", headers={"Cache-Control": "no-cache"})
            r2 = await client.get("/api/v1/prices/latest", headers={"Cache-Control": "no-cache"})
            return r1, r2

    r1, r2 = asyncio.run(_run())
    assert r1.json()["n"] == 1
    assert r2.json()["n"] == 2
    assert calls["n"] == 2


def test_http_cache_does_not_cache_non_json():
    store: dict[str, object] = {}
    http_cache.get_json = lambda key: store.get(key)  # type: ignore[assignment]
    http_cache.set_json = lambda key, value, ttl_secs=None: store.__setitem__(key, value)  # type: ignore[assignment]

    app = FastAPI()
    app.add_middleware(http_cache.RedisHTTPCacheMiddleware)
    calls = {"n": 0}

    @app.get("/text")
    async def text():  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return PlainTextResponse("ok")

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/text")
            r2 = await client.get("/text")
            return r1, r2

    r1, r2 = asyncio.run(_run())
    assert r1.text == "ok" and r2.text == "ok"
    assert calls["n"] == 2
    assert store == {}


def test_http_cache_preserves_multi_value_query_params_in_key():
    store: dict[str, object] = {}
    http_cache.get_json = lambda key: store.get(key)  # type: ignore[assignment]
    http_cache.set_json = lambda key, value, ttl_secs=None: store.__setitem__(key, value)  # type: ignore[assignment]

    app = FastAPI()
    app.add_middleware(http_cache.RedisHTTPCacheMiddleware)
    calls = {"n": 0}

    @app.get("/echo")
    async def echo(tags: list[str] = Query(default_factory=list)):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {"tags": tags, "n": calls["n"]}

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r1 = await client.get("/echo", params=[("tags", "a"), ("tags", "b")])
            r2 = await client.get("/echo", params=[("tags", "a"), ("tags", "b")])
            r3 = await client.get("/echo", params=[("tags", "b")])
            return r1, r2, r3

    r1, r2, r3 = asyncio.run(_run())
    assert r1.status_code == 200 and r1.json()["n"] == 1
    assert r2.status_code == 200 and r2.json()["n"] == 1  # cached first variant
    assert r3.status_code == 200 and r3.json()["n"] == 2  # distinct key for distinct multi-values
    assert calls["n"] == 2
    assert len(store) == 2
