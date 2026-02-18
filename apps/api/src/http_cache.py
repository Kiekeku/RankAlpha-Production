from __future__ import annotations

import hashlib
import json

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .cache import get_json, is_cache_disabled, make_key, ping_redis, set_json
from .settings import Settings


def _ttl_for_path(path: str, settings: Settings) -> int:
    # Specific TTLs for known heavy endpoints
    if path.startswith("/api/v1/grading/grades/batch"):
        return int(settings.cache_ttl_rankings or 300)
    if path.startswith("/api/v1/grading/grades"):
        return int(settings.cache_ttl_rankings or 300)
    if path.startswith("/api/v1/grading/sectors"):
        # sectors change infrequently – cache longer
        return int(getattr(settings, "cache_ttl_sectors", None) or 3600)
    if path.startswith("/api/v1/grading/asset/") or path.startswith("/api/v1/grading/grades/"):
        return int(settings.cache_ttl_stock_detail or 600)
    if path.startswith("/api/v1/ai-analysis"):
        return int(settings.cache_ttl_top_performers or 300)
    if path.startswith("/api/v1/prices/history"):
        # Price history is frequently requested by the dashboard; prefer a longer TTL to reduce DB fan-out.
        return int(getattr(settings, "cache_ttl_prices_history", None) or 600)
    if path.startswith("/api/v1/prices/latest"):
        return int(getattr(settings, "cache_ttl_prices_latest", None) or 300)
    if path.startswith("/api/v1/prices/live/"):
        # Live quotes: respect broker_price_cache_seconds (small TTL)
        return int(getattr(settings, "broker_price_cache_seconds", None) or 90)
    if path.startswith("/api/v1/screener/changes"):
        return int(getattr(settings, "cache_ttl_screener_changes", None) or 300)
    if path.startswith("/api/v1/screener/breadth"):
        return int(getattr(settings, "cache_ttl_screener_breadth", None) or 600)
    # Macro / regime dashboard endpoints (reduce DB fan-out from homepage)
    if path.startswith("/api/v1/macro"):
        # Macro series are EOD; cache longer and rely on nightly refresh / explicit purges for freshness.
        return int(getattr(settings, "cache_ttl_macro", None) or 21600)
    if path.startswith("/api/v1/benchmarks"):
        # Benchmarks used on the macro dashboard are typically EOD.
        return int(getattr(settings, "cache_ttl_benchmarks", None) or 21600)
    if path.startswith("/api/v1/breadth"):
        # Breadth signals are daily/EOD.
        return int(getattr(settings, "cache_ttl_breadth", None) or 21600)
    if path.startswith("/api/v1/fra-ois"):
        return int(getattr(settings, "cache_ttl_fra_ois", None) or 21600)
    if path.startswith("/api/v1/hy-stress"):
        return int(getattr(settings, "cache_ttl_hy_stress", None) or 21600)
    if path.startswith("/api/v1/vol-regime"):
        return int(getattr(settings, "cache_ttl_vol_regime", None) or 21600)
    if path.startswith("/api/v1/rates"):
        return int(getattr(settings, "cache_ttl_rates", None) or 21600)
    if path.startswith("/api/v1/fx"):
        return int(getattr(settings, "cache_ttl_fx", None) or 21600)
    if path.startswith("/api/v1/money-flow"):
        return int(getattr(settings, "cache_ttl_money_flow", None) or 21600)
    if path.startswith("/api/v1/technicals"):
        return int(getattr(settings, "cache_ttl_technicals", None) or 21600)
    if path.startswith("/api/v1/fundamentals"):
        return int(getattr(settings, "cache_ttl_fundamentals", None) or 21600)
    # Fallback default
    return int(getattr(settings, "cache_ttl_default", None) or 3600)


class RedisHTTPCacheMiddleware(BaseHTTPMiddleware):
    """Simple read‑through cache for idempotent GET endpoints.

    - Caches JSON 200 responses in Redis keyed by method+path+sorted query.
    - Honors per‑path TTLs; default TTL if none specified.
    - Skips caching if the client sends Cache-Control: no-cache.
    - Skips caching for refresh/invalidation endpoints.
    """

    def __init__(self, app):
        super().__init__(app)
        self.settings = Settings()
        self.enabled = bool(getattr(self.settings, "http_cache_enabled", True))
        if self.enabled:
            # tiny health probe – if Redis not reachable, disable middleware
            try:
                if not ping_redis():
                    self.enabled = False
            except Exception:
                self.enabled = False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Allow disabling via env for local dev
        if not self.enabled or is_cache_disabled():
            return await call_next(request)
        # Only cache GETs and allow opt-out
        if request.method != "GET":
            return await call_next(request)

        if "no-cache" in request.headers.get("Cache-Control", "").lower():
            return await call_next(request)

        # Skip caching for refresh endpoint (explicit invalidation path)
        if request.url.path.startswith("/api/v1/grading/refresh"):
            return await call_next(request)

        # Build cache key from path and query params.
        # Keep duplicate query keys (e.g. ?ratings=buy&ratings=sell) to avoid key collisions.
        params: dict[str, object] = {"_query_items": sorted(request.query_params.multi_items())}

        # Safety: vary cache by auth/cookies so protected endpoints can't leak across callers.
        # We hash values to avoid storing secrets in keys.
        def _hash_header(val: str) -> str:
            return hashlib.sha256(val.encode("utf-8")).hexdigest()[:16]

        auth = request.headers.get("authorization") or ""
        cookie = request.headers.get("cookie") or ""
        x_api_key = request.headers.get("x-api-key") or ""
        if auth:
            params["_auth"] = _hash_header(auth)
        if cookie:
            params["_cookie"] = _hash_header(cookie)
        if x_api_key:
            params["_x_api_key"] = _hash_header(x_api_key)

        key = make_key(f"httpcache:{request.method}:{request.url.path}", params)

        cached = get_json(key)
        if cached is not None:
            # Assume JSON payload and 200 OK
            return JSONResponse(content=cached, status_code=200)

        # No cache – execute request
        response = await call_next(request)

        # Cache only JSON 200 responses
        ctype = (
            (response.headers.get("content-type") or "") or (response.media_type or "")
        ).lower()
        if response.status_code == 200 and "application/json" in ctype:
            try:
                body_bytes = getattr(response, "body", None)
                if body_bytes is None:
                    # Consume body_iterator if needed
                    body_chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]
                    body_bytes = b"".join(body_chunks)
                    # rebuild response so it can be sent to client
                    response = Response(
                        content=body_bytes,
                        media_type=response.media_type,
                        status_code=response.status_code,
                    )

                payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else None
                if payload is not None:
                    ttl = _ttl_for_path(request.url.path, self.settings)
                    set_json(key, payload, ttl_secs=ttl)
            except Exception:
                # ignore cache errors and continue
                pass

        return response
