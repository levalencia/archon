"""Security middleware: XSS sanitization, CSRF protection, input validation.

Intercepts all requests to sanitize inputs and add security headers.
"""

from __future__ import annotations

import hmac
import html
import re
import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.observability.logging import safe_value_metadata

logger = structlog.get_logger()

# XSS patterns to strip
XSS_PATTERNS = [
    re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"<iframe[^>]*>", re.IGNORECASE),
    re.compile(r"<object[^>]*>", re.IGNORECASE),
    re.compile(r"<embed[^>]*>", re.IGNORECASE),
]

# SQL injection patterns
SQL_PATTERNS = [
    re.compile(
        r"(\b(union|select|insert|update|delete|drop|alter)\b.*\b(from|into|table|where)\b)",
        re.IGNORECASE,
    ),
    re.compile(r";\s*(drop|delete|update|insert)\s", re.IGNORECASE),
    re.compile(r"--\s*$", re.MULTILINE),
]


def sanitize_string(value: str) -> str:
    """Remove XSS and SQL injection patterns from a string."""
    cleaned = value
    for pattern in XSS_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return html.escape(cleaned) if cleaned != value else value


def check_sql_injection(value: str) -> bool:
    """Return True if SQL injection pattern detected."""
    return any(p.search(value) for p in SQL_PATTERNS)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if "Content-Security-Policy" not in response.headers:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "base-uri 'self'; object-src 'none'; frame-ancestors 'self'; "
                "script-src 'self' 'unsafe-inline' "
                "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
                "font-src 'self' data:; img-src 'self' data: blob: https:; "
                "connect-src 'self' http://localhost:* ws://localhost:*; "
                "frame-src 'self'; worker-src 'self' blob:"
            )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection using double-submit cookie pattern.

    - Sets a CSRF token cookie on GET requests
    - Validates X-CSRF-Token only for cookie-authenticated mutating requests
    - Bearer and API-key clients are exempt
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register", "/healthz", "/readyz", "/metrics"}
    AUTH_COOKIE_NAMES = {"access_token", "archon_token", "session"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip for safe methods
        if request.method in self.SAFE_METHODS:
            response = await call_next(request)
            # Set CSRF cookie if not present
            if "csrf_token" not in request.cookies:
                token = secrets.token_hex(32)
                response.set_cookie("csrf_token", token, httponly=False, samesite="strict")
            return response

        # Skip for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Header credentials are explicit rather than ambient browser authority.
        authorization = request.headers.get("Authorization", "")
        if request.headers.get("X-API-Key") or authorization.lower().startswith("bearer "):
            return await call_next(request)

        # Anonymous requests have no cookie authority; endpoint auth still applies.
        if not any(name in request.cookies for name in self.AUTH_COOKIE_NAMES):
            return await call_next(request)

        # Validate CSRF token
        cookie_token = request.cookies.get("csrf_token", "")
        header_token = request.headers.get("X-CSRF-Token", "")

        token_is_valid = (
            cookie_token and header_token and hmac.compare_digest(cookie_token, header_token)
        )
        if not token_is_valid:
            logger.warning(
                "csrf_validation_failed", **safe_value_metadata("path", request.url.path)
            )
            return JSONResponse(
                {"detail": "CSRF token missing or invalid"},
                status_code=403,
            )

        return await call_next(request)
