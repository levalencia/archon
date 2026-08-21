"""Correlation ID middleware. Injects a unique ID into every request for tracing.

Every log entry, audit record, and trace span for a single request shares the
same correlation_id. This is how you trace a user message through the entire
agent pipeline: API → Coordinator → Planner → Retriever → Validator → Synthesizer.

The ID comes from:
1. X-Correlation-ID header (if provided by client)
2. Auto-generated UUID (if not provided)
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability.logging import set_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject correlation ID into every request context."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use client-provided ID or generate one
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

        # Set in ContextVar for structlog
        set_correlation_id(correlation_id)

        # Process request
        response = await call_next(request)

        # Echo back in response headers
        response.headers["X-Correlation-ID"] = correlation_id

        return response
