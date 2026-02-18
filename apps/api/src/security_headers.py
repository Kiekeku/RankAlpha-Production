from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers to every response.

    Keep this middleware lightweight and broadly compatible: the API also serves Swagger UI
    and may be called cross-origin by the frontend, so avoid an overly strict CSP here.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Prevent content-type sniffing.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Disallow framing (clickjacking).
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Avoid leaking referrers.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Reduce attack surface in modern browsers.
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )

        # HSTS: only meaningful over HTTPS; safe to set when proxied via TLS.
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
        if proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response
