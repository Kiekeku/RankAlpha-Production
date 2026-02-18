from __future__ import annotations

from typing import Callable

from apps.common.src.logging import get_logger

logger = get_logger("api.metrics")

try:  # pragma: no cover - optional dependency in some dev/test contexts
    from prometheus_client import Counter
except Exception:  # pragma: no cover - defensive
    Counter = None  # type: ignore[assignment]


API_REQUESTS_TOTAL = (
    Counter(
        "rankalpha_api_requests_total",
        "Total HTTP requests served by the RankAlpha API (excludes /metrics).",
        ["handler", "method", "status_code"],
    )
    if Counter is not None
    else None
)

API_ENDPOINT_REQUESTS_TOTAL = (
    Counter(
        "rankalpha_api_endpoint_requests_total",
        "Total API calls grouped by endpoint and method (excludes /metrics).",
        ["handler", "method"],
    )
    if Counter is not None
    else None
)

API_ENDPOINT_REQUESTS_BY_CLIENT_TOTAL = (
    Counter(
        "rankalpha_api_endpoint_requests_by_client_total",
        "Total API calls grouped by endpoint/method/client class (bot/browser/other/unknown).",
        ["handler", "method", "client_class"],
    )
    if Counter is not None
    else None
)

_BOT_UA_TOKENS = (
    "bot",
    "crawler",
    "crawl",
    "spider",
    "scrapy",
    "slurp",
    "headless",
    "python-requests",
    "python-httpx",
    "aiohttp",
    "okhttp",
    "go-http-client",
    "curl/",
    "wget/",
)
_BROWSER_UA_TOKENS = ("mozilla/", "chrome/", "safari/", "firefox/", "edg/")


def _scope_header(scope: dict, name: str) -> str | None:
    headers = scope.get("headers")
    if not isinstance(headers, list):
        return None
    needle = name.lower().encode("latin-1")
    for item in headers:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        key, value = item
        if not isinstance(key, bytes) or not isinstance(value, bytes):
            continue
        if key.lower() == needle:
            try:
                return value.decode("latin-1")
            except Exception:
                return None
    return None


def classify_client_from_scope(scope: dict) -> str:
    user_agent = (_scope_header(scope, "user-agent") or "").strip().lower()
    if not user_agent:
        return "unknown"
    if any(token in user_agent for token in _BOT_UA_TOKENS):
        return "bot"
    if any(token in user_agent for token in _BROWSER_UA_TOKENS):
        return "browser"
    return "other"


def resolve_handler_from_scope(scope: dict) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None) if route is not None else None
    if isinstance(path, str) and path:
        return path
    return "/__unmatched__"


class APIMetricsMiddleware:
    """Track API request counts with a `status_code` label for alerting."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        if path in {"/metrics"}:
            await self.app(scope, receive, send)
            return

        handler = "unknown"
        method = scope.get("method") or "UNKNOWN"
        client_class = classify_client_from_scope(scope)

        async def send_wrapper(message: dict) -> None:
            nonlocal handler
            if message.get("type") == "http.response.start":
                handler = resolve_handler_from_scope(scope)
                status_code = str(message.get("status", "0"))
                if API_REQUESTS_TOTAL is not None:
                    try:
                        API_REQUESTS_TOTAL.labels(
                            handler=handler, method=str(method), status_code=status_code
                        ).inc()
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Failed to update rankalpha_api_requests_total.")
                if API_ENDPOINT_REQUESTS_TOTAL is not None:
                    try:
                        API_ENDPOINT_REQUESTS_TOTAL.labels(
                            handler=handler, method=str(method)
                        ).inc()
                    except Exception:  # pragma: no cover - defensive
                        logger.exception("Failed to update rankalpha_api_endpoint_requests_total.")
                if API_ENDPOINT_REQUESTS_BY_CLIENT_TOTAL is not None:
                    try:
                        API_ENDPOINT_REQUESTS_BY_CLIENT_TOTAL.labels(
                            handler=handler,
                            method=str(method),
                            client_class=client_class,
                        ).inc()
                    except Exception:  # pragma: no cover - defensive
                        logger.exception(
                            "Failed to update rankalpha_api_endpoint_requests_by_client_total."
                        )
            await send(message)

        await self.app(scope, receive, send_wrapper)
