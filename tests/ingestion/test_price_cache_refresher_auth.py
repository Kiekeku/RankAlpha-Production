from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from apps.ingestion.src.price_cache_refresher import PriceCacheRefresher


class _StubLogger:
    def warning(self, *args, **kwargs) -> None:  # pragma: no cover
        return None

    def info(self, *args, **kwargs) -> None:  # pragma: no cover
        return None


def test_price_cache_refresh_uses_auth_service_token(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": dict(headers), "timeout": timeout})

        class _Resp:
            status_code = 200
            text = "ok"

        return _Resp()

    monkeypatch.setattr("apps.ingestion.src.price_cache_refresher.requests.post", fake_post)

    settings = SimpleNamespace(
        price_cache_refresh_url="http://example.com/refresh",
        auth_service_token="service-token",
        price_cache_refresh_timeout_seconds=1,
        price_history_cache_refresh_chunk_size=50,
    )

    PriceCacheRefresher(settings, _StubLogger()).refresh({"AAPL": date(2025, 1, 2)})

    assert calls
    headers = calls[0]["headers"]
    assert headers.get("X-RA-Service-Token") == "service-token"
    assert "Authorization" not in headers


def test_price_cache_refresh_skips_when_missing_token(monkeypatch):
    calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": dict(headers), "timeout": timeout})

        class _Resp:
            status_code = 200
            text = "ok"

        return _Resp()

    monkeypatch.setattr("apps.ingestion.src.price_cache_refresher.requests.post", fake_post)

    settings = SimpleNamespace(
        price_cache_refresh_url="http://example.com/refresh",
        auth_service_token="",
        price_cache_refresh_timeout_seconds=1,
        price_history_cache_refresh_chunk_size=50,
    )

    PriceCacheRefresher(settings, _StubLogger()).refresh({"AAPL": date(2025, 1, 2)})
    assert calls == []

