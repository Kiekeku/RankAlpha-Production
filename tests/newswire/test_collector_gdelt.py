from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from newswire.collector import gdelt


class _Resp:
    def __init__(self, *, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):  # type: ignore[no-untyped-def]
        return self._payload


class _Client:
    def __init__(self, *, resp: _Resp):
        self.resp = resp
        self.calls: list[dict] = []

    async def get(self, url: str, params=None):  # type: ignore[no-untyped-def]
        self.calls.append({"url": url, "params": dict(params or {})})
        return self.resp


def test_fmt_gdelt_dt_converts_to_utc_compact():
    dt = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-5)))
    assert gdelt._fmt_gdelt_dt(dt) == "20250102080405"


def test_fetch_window_wraps_or_query_and_yields_rows(monkeypatch):
    client = _Client(
        resp=_Resp(
            payload={
                "articles": [
                    {"url": "u", "title": "t", "seendescription": "s", "seendate": "2025-01-01", "domain": "ex.com"},
                ]
            }
        )
    )
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 1, 1, 0, 15, tzinfo=timezone.utc)

    async def _collect():
        out = []
        async for it in gdelt._fetch_window(client, "https://gdelt", start, end, "A OR B", 50):
            out.append(it)
        return out

    items = asyncio.run(_collect())
    assert items and items[0]["url"] == "u"
    assert isinstance(items[0]["text_fp"], (int, type(None)))
    assert client.calls[0]["params"]["query"] == "(A OR B)"
    assert "startdatetime" in client.calls[0]["params"]
    assert "enddatetime" in client.calls[0]["params"]


def test_fetch_window_returns_no_items_on_error_payload():
    client = _Client(resp=_Resp(payload={"error": "bad request"}))

    async def _collect():
        out = []
        async for it in gdelt._fetch_window(client, "https://gdelt", None, None, None, 50):
            out.append(it)
        return out

    assert asyncio.run(_collect()) == []


def test_poll_gdelt_iterates_windows(monkeypatch):
    calls: list[tuple[datetime | None, datetime | None]] = []

    async def fake_fetch(_client, _url, start, end, _query, _max):  # type: ignore[no-untyped-def]
        calls.append((start, end))
        yield {"url": f"{start}-{end}"}

    monkeypatch.setattr(gdelt, "_fetch_window", fake_fetch)

    since = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    until = datetime(2025, 1, 1, 0, 31, tzinfo=timezone.utc)
    monkeypatch.setenv("GDELT_STEP_MIN", "15")

    async def _collect():
        out = []
        async for it in gdelt.poll_gdelt(session=SimpleNamespace(aclose=lambda: None), since=since, until=until):
            out.append(it)
        return out

    items = asyncio.run(_collect())
    assert len(items) == 3
    assert calls[0][0] == since
