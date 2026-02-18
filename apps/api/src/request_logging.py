from __future__ import annotations

import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from apps.common.src.logging import get_logger

from .settings import Settings

_logger = get_logger("api.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs each request with latency and status code.

    - Adds a short request id for correlation.
    - Warns on slow requests based on Settings.log_slow_request_ms (default 750ms).
    - Skips logging for docs and health noise paths with minimal overhead.
    """

    def __init__(self, app):
        super().__init__(app)
        s = Settings()
        self.slow_ms = int(s.log_slow_request_ms or 750)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            path in {"/", "/health", "/openapi.json"}
            or path.startswith("/docs")
            or path.startswith("/redoc")
        ):
            return await call_next(request)

        req_id = uuid.uuid4().hex[:8]
        request.state.req_id = req_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            dur_ms = int((time.perf_counter() - start) * 1000)
            _logger.exception(f"{req_id} {request.method} {path} raised after {dur_ms}ms")
            raise

        dur_ms = int((time.perf_counter() - start) * 1000)
        client = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else "-"
        )
        level = "warning" if dur_ms >= self.slow_ms else "info"
        msg = f"{req_id} {request.method} {path} {response.status_code} in {dur_ms}ms"
        if level == "warning":
            _logger.warning(msg + f" from {client}")
        else:
            _logger.info(msg)
        return response
