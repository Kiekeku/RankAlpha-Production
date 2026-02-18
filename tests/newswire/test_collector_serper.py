from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from newswire.collector import serper


def test_make_tbs_prefers_env_when_since_missing(monkeypatch):
    monkeypatch.setenv("SERPER_TBS", "qdr:m")
    assert serper._make_tbs(None, None) == "qdr:m"


def test_make_tbs_buckets_by_hours(monkeypatch):
    fixed_now = datetime(2025, 1, 2, tzinfo=timezone.utc)

    class _FixedDatetime:
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return fixed_now if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(serper, "datetime", _FixedDatetime)
    assert serper._make_tbs(fixed_now, None) == "qdr:h"
    assert serper._make_tbs(fixed_now.replace(day=1), None) == "qdr:d"


def test_poll_serper_returns_empty_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

    async def _collect():
        out = []
        async for it in serper.poll_serper(queries=["x"], num=1):
            out.append(it)
        return out

    assert asyncio.run(_collect()) == []


def test_poll_serper_yields_rows_via_gateway(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "x")
    monkeypatch.setenv("SERPER_GL", "us")

    calls: list[dict] = []

    class _FakeGateway:
        async def call_search(self, *, provider, query, do_search, per_query_cap):  # type: ignore[no-untyped-def]
            calls.append(
                {
                    "provider": provider,
                    "query": query,
                    "per_query_cap": per_query_cap,
                }
            )
            return {
                "news": [
                    {"link": "u", "title": "t", "snippet": "s", "date": "2025-01-01", "source": "ex.com"}
                ]
            }

    monkeypatch.setattr(serper, "_SEARCH_GATEWAY", _FakeGateway())

    async def _collect():
        out = []
        async for it in serper.poll_serper(queries=["q"], num=999):
            out.append(it)
        return out

    items = asyncio.run(_collect())
    assert items and items[0]["url"] == "u"
    assert calls and calls[0]["per_query_cap"] == 50
