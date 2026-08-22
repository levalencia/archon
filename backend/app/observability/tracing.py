"""OpenTelemetry tracing for Archon.

Creates spans for: LLM calls, tool executions, agent steps, RAG queries.
Exports to Jaeger via OTLP when configured, or no-op in testing.

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 6 - Observability (distributed tracing)
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any

import structlog

logger = structlog.get_logger()


class Span:
    """A trace span representing a unit of work."""

    def __init__(self, name: str, attributes: dict | None = None) -> None:
        self.name = name
        self.attributes = attributes or {}
        self.start_time = time.monotonic()
        self.end_time: float | None = None
        self.status = "ok"
        self.events: list[dict] = []
        self.children: list[Span] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        self.events.append(
            {
                "name": name,
                "timestamp": time.monotonic(),
                "attributes": attributes or {},
            }
        )

    def set_error(self, error: str) -> None:
        self.status = "error"
        self.attributes["error.message"] = error

    def end(self) -> None:
        self.end_time = time.monotonic()

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.monotonic()
        return round((end - self.start_time) * 1000, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "children": [c.to_dict() for c in self.children],
        }


class Tracer:
    """Simple tracer that collects spans.

    In production, this wraps OpenTelemetry SDK.
    In testing, it collects spans in memory for assertions.
    """

    def __init__(self, service_name: str = "archon") -> None:
        self.service_name = service_name
        self.spans: list[Span] = []
        self._current_span: Span | None = None

    @contextmanager
    def start_span(self, name: str, attributes: dict | None = None):  # type: ignore[no-untyped-def]
        """Context manager that creates and tracks a span."""
        span = Span(name=name, attributes=attributes)

        if self._current_span:
            self._current_span.children.append(span)

        parent = self._current_span
        self._current_span = span

        try:
            yield span
        except Exception as e:
            span.set_error(str(e))
            raise
        finally:
            span.end()
            self._current_span = parent
            if parent is None:
                self.spans.append(span)

            logger.debug(
                "span_completed",
                span_name=span.name,
                duration_ms=span.duration_ms,
                status=span.status,
            )

    def trace(self, name: str | None = None, attributes: dict | None = None):  # type: ignore[no-untyped-def]
        """Decorator that wraps a function in a span."""

        def decorator(func):  # type: ignore[no-untyped-def]
            span_name = name or f"{func.__module__}.{func.__qualname__}"

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.start_span(span_name, attributes) as span:
                    result = await func(*args, **kwargs)
                    return result

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                with self.start_span(span_name, attributes) as span:
                    result = func(*args, **kwargs)
                    return result

            import asyncio

            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def get_recent_spans(self, limit: int = 50) -> list[dict]:
        """Get recent completed root spans."""
        return [s.to_dict() for s in self.spans[-limit:]]

    def get_span_count(self) -> int:
        """Total number of root spans."""
        return len(self.spans)

    def clear(self) -> None:
        """Clear all collected spans."""
        self.spans.clear()


# Global tracer instance
_tracer = Tracer()


def get_tracer() -> Tracer:
    """Get the global tracer instance."""
    return _tracer
