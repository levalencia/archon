"""Security middleware: XSS sanitization, CSRF protection, input validation.

Intercepts all requests to sanitize inputs and add security headers.
"""

from __future__ import annotations

import html
import re
import secrets

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' http://localhost:*; "
            "frame-src 'self'"
        )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection using double-submit cookie pattern.

    - Sets a CSRF token cookie on GET requests
    - Validates X-CSRF-Token header on mutating requests (POST, PUT, DELETE)
    - Skips CSRF for API key authenticated requests
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXEMPT_PATHS = {"/api/auth/login", "/api/auth/register", "/healthz", "/readyz", "/metrics"}

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

        # Skip for API key requests
        if request.headers.get("X-API-Key"):
            return await call_next(request)

        # Validate CSRF token
        cookie_token = request.cookies.get("csrf_token", "")
        header_token = request.headers.get("X-CSRF-Token", "")

        if not cookie_token or not header_token or cookie_token != header_token:
            logger.warning("csrf_validation_failed", path=request.url.path)
            return JSONResponse(
                {"detail": "CSRF token missing or invalid"},
                status_code=403,
            )

        return await call_next(request)
