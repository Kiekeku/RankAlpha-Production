from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse

from apps.api.src import request_logging


class _DummySettings:
    log_slow_request_ms = 10


class _FakeLogger:
    def __init__(self):
        self.infos: list[str] = []
        self.warnings: list[str] = []
        self.exceptions: list[str] = []

    def info(self, msg: str) -> None:
        self.infos.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def exception(self, msg: str) -> None:
        self.exceptions.append(msg)


@pytest.fixture(autouse=True)
def _patch_settings_and_logger(monkeypatch):
    fake = _FakeLogger()
    monkeypatch.setattr(request_logging, "Settings", lambda: _DummySettings())
    monkeypatch.setattr(request_logging, "_logger", fake)
    yield fake


def test_request_logging_sets_req_id_for_non_docs_paths(monkeypatch):
    times = {"t": 0.0}

    def perf_counter() -> float:
        times["t"] += 0.001  # 1ms per call
        return times["t"]

    monkeypatch.setattr(request_logging.time, "perf_counter", perf_counter)

    app = FastAPI()
    app.add_middleware(request_logging.RequestLoggingMiddleware)

    @app.get("/")
    async def root(request: Request):  # type: ignore[no-untyped-def]
        return {"req_id": getattr(request.state, "req_id", None)}

    @app.get("/ping")
    async def ping(request: Request):  # type: ignore[no-untyped-def]
        return {"req_id": getattr(request.state, "req_id", None)}

    async def _run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r_root = await client.get("/")
            r_ping = await client.get("/ping")
            return r_root, r_ping

    r_root, r_ping = asyncio.run(_run())
    assert r_root.json()["req_id"] is None  # excluded path
    req_id = r_ping.json()["req_id"]
    assert isinstance(req_id, str) and len(req_id) == 8


def test_request_logging_uses_warning_for_slow_requests(monkeypatch, _patch_settings_and_logger):
    # perf_counter: start=0.0, end=1.0 -> 1000ms (>= default threshold 750ms too)
    vals = [0.0, 1.0]
    idx = {"i": 0}

    def perf_counter() -> float:
        i = idx["i"]
        idx["i"] = i + 1
        return vals[i] if i < len(vals) else vals[-1]

    monkeypatch.setattr(request_logging.time, "perf_counter", perf_counter)

    async def _run():
        async def receive():  # type: ignore[no-untyped-def]
            return {"type": "http.request", "body": b"", "more_body": False}

        req = StarletteRequest(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "path": "/slow",
                "raw_path": b"/slow",
                "query_string": b"",
                "headers": [(b"x-forwarded-for", b"1.2.3.4")],
                "client": ("1.2.3.4", 123),
                "server": ("test", 80),
                "scheme": "http",
            },
            receive,
        )

        mw = request_logging.RequestLoggingMiddleware(app=FastAPI())

        async def call_next(_request):  # type: ignore[no-untyped-def]
            return JSONResponse({"ok": True})

        resp = await mw.dispatch(req, call_next)
        assert resp.status_code == 200

    asyncio.run(_run())
    assert _patch_settings_and_logger.warnings
