from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest


pytest.importorskip("feedparser")

from newswire.collector import rss  # noqa: E402


class _Resp:
    def __init__(self, *, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _Client:
    def __init__(self, *, responses: dict[str, _Resp]):
        self.responses = responses
        self.closed = False
        self.get_calls: list[str] = []

    async def get(self, url: str):  # type: ignore[no-untyped-def]
        self.get_calls.append(url)
        return self.responses[url]

    async def aclose(self) -> None:
        self.closed = True


def test_parse_feeds_env_handles_json_and_bars():
    assert rss._parse_feeds_env(None) == []
    assert rss._parse_feeds_env('["a", " b "]') == ["a", "b"]
    assert rss._parse_feeds_env("a| b |") == ["a", "b"]
    # If it looks like JSON but fails to parse, we fall back to bar-separated behavior.
    assert rss._parse_feeds_env("[bad") == ["[bad"]


def test_to_dt_iso_prefers_parsed_then_falls_back_to_string():
    entry = {"published_parsed": time.gmtime(0)}
    out = rss._to_dt_iso(entry)
    assert out and out.startswith("1970-01-01T00:00:00")

    entry2 = {"published": "2025-01-02T03:04:05Z"}
    assert rss._to_dt_iso(entry2) == "2025-01-02T03:04:05Z"


def test_source_domain_prefers_entry_url_then_feed_link():
    assert rss._source_domain("https://Example.com/a", None) == "example.com"
    assert rss._source_domain(None, "https://Feed.EXAMPLE.com/x") == "feed.example.com"
    assert rss._source_domain("not a url", None) == ""


def test_poll_rss_yields_items_and_applies_window_filter(monkeypatch):
    parsed = {
        "feed": {"link": "https://feed.example.com", "language": "en"},
        "entries": [
            {"title": "A", "summary": "S", "link": "https://example.com/a", "published_parsed": time.gmtime(0)},
            {
                "title": "B",
                "summary": "S",
                "link": "https://example.com/b",
                "published_parsed": time.gmtime(int(datetime(2025, 1, 2, tzinfo=timezone.utc).timestamp())),
            },
        ],
    }

    monkeypatch.setattr(rss.feedparser, "parse", lambda _b: parsed)
    client = _Client(responses={"https://feed.example.com/rss": _Resp(content=b"<xml/>")})

    async def _collect():
        since = datetime(2024, 1, 1, tzinfo=timezone.utc)
        out = []
        async for it in rss.poll_rss(session=client, feeds=["https://feed.example.com/rss"], since=since, num_per_feed=50):
            out.append(it)
        return out

    items = asyncio.run(_collect())
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/b"
    assert items[0]["source_domain"] == "example.com"
