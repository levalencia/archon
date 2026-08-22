"""Tests for OpenTelemetry-compatible tracing."""

from __future__ import annotations

import pytest

from app.observability.tracing import Span, Tracer, get_tracer


class TestSpan:
    """Span tests."""

    @pytest.mark.unit
    def test_span_creation(self) -> None:
        span = Span(name="test-span")
        assert span.name == "test-span"
        assert span.status == "ok"

    @pytest.mark.unit
    def test_span_attributes(self) -> None:
        span = Span(name="test", attributes={"key": "value"})
        span.set_attribute("extra", 42)
        assert span.attributes["key"] == "value"
        assert span.attributes["extra"] == 42

    @pytest.mark.unit
    def test_span_events(self) -> None:
        span = Span(name="test")
        span.add_event("tool_called", {"tool": "search"})
        assert len(span.events) == 1
        assert span.events[0]["name"] == "tool_called"

    @pytest.mark.unit
    def test_span_error(self) -> None:
        span = Span(name="test")
        span.set_error("Connection failed")
        assert span.status == "error"
        assert span.attributes["error.message"] == "Connection failed"

    @pytest.mark.unit
    def test_span_duration(self) -> None:
        span = Span(name="test")
        span.end()
        assert span.duration_ms >= 0

    @pytest.mark.unit
    def test_span_to_dict(self) -> None:
        span = Span(name="test", attributes={"a": 1})
        span.end()
        d = span.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "ok"
        assert "duration_ms" in d


class TestTracer:
    """Tracer tests."""

    @pytest.fixture
    def tracer(self) -> Tracer:
        t = Tracer(service_name="test")
        t.clear()
        return t

    @pytest.mark.unit
    def test_start_span(self, tracer: Tracer) -> None:
        with tracer.start_span("test-op") as span:
            span.set_attribute("key", "value")

        assert tracer.get_span_count() == 1
        spans = tracer.get_recent_spans()
        assert spans[0]["name"] == "test-op"

    @pytest.mark.unit
    def test_nested_spans(self, tracer: Tracer) -> None:
        with tracer.start_span("parent") as _parent, tracer.start_span("child") as child:
            child.set_attribute("level", "child")

        spans = tracer.get_recent_spans()
        assert len(spans) == 1  # Only root span
        assert len(spans[0]["children"]) == 1
        assert spans[0]["children"][0]["name"] == "child"

    @pytest.mark.unit
    def test_span_error_propagation(self, tracer: Tracer) -> None:
        with pytest.raises(ValueError, match="boom"), tracer.start_span("failing"):
            msg = "boom"
            raise ValueError(msg)

        spans = tracer.get_recent_spans()
        assert spans[0]["status"] == "error"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_trace_decorator_async(self, tracer: Tracer) -> None:
        @tracer.trace("my-operation")
        async def my_func() -> str:
            return "result"

        result = await my_func()
        assert result == "result"
        assert tracer.get_span_count() == 1

    @pytest.mark.unit
    def test_trace_decorator_sync(self, tracer: Tracer) -> None:
        @tracer.trace("sync-op")
        def my_func() -> int:
            return 42

        result = my_func()
        assert result == 42
        assert tracer.get_span_count() == 1

    @pytest.mark.unit
    def test_clear(self, tracer: Tracer) -> None:
        with tracer.start_span("a"):
            pass
        tracer.clear()
        assert tracer.get_span_count() == 0

    @pytest.mark.unit
    def test_get_tracer_singleton(self) -> None:
        t = get_tracer()
        assert isinstance(t, Tracer)
