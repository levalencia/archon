"""OpenTelemetry OTLP export to Jaeger.

Wraps the simple Tracer with real OTel SDK when available.
Falls back to in-memory tracer for testing.
"""

from __future__ import annotations

from contextlib import contextmanager

import structlog

from app.observability.tracing import Span

logger = structlog.get_logger()


class OTLPExporter:
    """Export spans to Jaeger via OTLP.

    When opentelemetry SDK is installed, uses real OTLP exporter.
    Otherwise collects spans in memory (same as Tracer).
    """

    def __init__(
        self,
        service_name: str = "archon",
        endpoint: str = "http://localhost:4317",
    ) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        self._real_tracer = None
        self._setup_otel()

    def _setup_otel(self) -> None:
        """Try to initialize real OpenTelemetry SDK."""
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({"service.name": self.service_name})
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=self.endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._real_tracer = trace.get_tracer(self.service_name)
            logger.info(
                "otel_initialized",
                endpoint=self.endpoint,
                service=self.service_name,
            )
        except ImportError:
            logger.info("otel_sdk_not_installed", fallback="in-memory tracer")
            self._real_tracer = None

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict | None = None,
    ):
        """Create a span. Uses real OTel if available, else in-memory."""
        if self._real_tracer:
            with self._real_tracer.start_as_current_span(name) as otel_span:
                if attributes:
                    for k, v in attributes.items():
                        otel_span.set_attribute(k, str(v))
                yield otel_span
        else:
            # Fallback to simple span
            span = Span(name=name, attributes=attributes)
            try:
                yield span
            finally:
                span.end()

    def trace_llm_call(
        self,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
    ) -> None:
        """Record an LLM call with gen_ai semantic conventions."""
        attrs = {
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.total_tokens": input_tokens + output_tokens,
            "duration_ms": duration_ms,
        }

        if self._real_tracer:
            with self._real_tracer.start_as_current_span("llm.chat") as span:
                for k, v in attrs.items():
                    span.set_attribute(k, str(v))
        else:
            logger.debug("otel_llm_call", **attrs)

    def trace_tool_call(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
    ) -> None:
        """Record a tool execution span."""
        attrs = {
            "tool.name": tool_name,
            "tool.success": success,
            "duration_ms": duration_ms,
        }

        if self._real_tracer:
            with self._real_tracer.start_as_current_span(f"tool.{tool_name}") as span:
                for k, v in attrs.items():
                    span.set_attribute(k, str(v))
                if not success:
                    span.set_status(__import__("opentelemetry.trace").trace.StatusCode.ERROR)
        else:
            logger.debug("otel_tool_call", **attrs)

    def export_span(self, span: Span) -> None:
        """Export an already completed runtime span when OTLP is enabled."""
        if not self._real_tracer:
            return
        with self._real_tracer.start_as_current_span(span.name) as exported:
            for key, value in span.attributes.items():
                exported.set_attribute(key, value)
            if span.status == "error":
                from opentelemetry.trace import Status, StatusCode

                message = str(span.attributes.get("error.message", ""))
                exported.set_status(Status(StatusCode.ERROR, message))

    def shutdown(self) -> None:
        """Flush the configured provider if it supports shutdown."""
        if self._real_tracer:
            shutdown = getattr(self._real_tracer.provider, "shutdown", None)
            if shutdown:
                shutdown()


# Global instance
_exporter: OTLPExporter | None = None


def get_otel_exporter(
    endpoint: str = "http://localhost:4317",
) -> OTLPExporter:
    global _exporter
    if _exporter is None:
        _exporter = OTLPExporter(endpoint=endpoint)
    return _exporter
