"""Vendor-neutral OpenTelemetry export to the local Collector."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

from app.observability.tracing import Span

logger = structlog.get_logger()


class OTLPExporter:
    """Own the application OTel provider and export one stream to the Collector.

    When opentelemetry SDK is installed, uses real OTLP exporter.
    Otherwise collects spans in memory (same as Tracer).
    """

    def __init__(
        self,
        service_name: str = "cogentrex",
        endpoint: str = "http://localhost:4317",
    ) -> None:
        self.service_name = service_name
        self.endpoint = endpoint
        self._real_tracer: Any | None = None
        self._provider: Any | None = None
        self._fastapi_instrumentation: Any | None = None
        self._active_agent_spans: dict[str, Any] = {}
        self._setup_otel()

    def _setup_otel(self) -> None:
        """Initialize one standard provider exporting OTLP to the Collector."""
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(
                endpoint=self.endpoint,
                insecure=self.endpoint.startswith("http://"),
            )
            collector_processor = BatchSpanProcessor(exporter)
            resource = Resource.create({"service.name": self.service_name})
            provider: Any = TracerProvider(resource=resource)
            provider.add_span_processor(collector_processor)
            self._provider = provider
            self._real_tracer = provider.get_tracer(self.service_name)
            logger.info(
                "otel_initialized",
                endpoint=self.endpoint,
                service=self.service_name,
                destination="otel-collector",
            )
        except ImportError:
            logger.info("otel_sdk_not_installed", fallback="in-memory tracer")
            self._provider = None
            self._real_tracer = None

    @property
    def is_active(self) -> bool:
        """Whether spans are backed by the real OTLP SDK/exporter."""
        return self._provider is not None and self._real_tracer is not None

    def instrument_fastapi(self, app: Any) -> bool:
        """Instrument FastAPI without request/response headers or ASGI payload spans."""
        if self._provider is None:
            return False
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        self._fastapi_instrumentation = FastAPIInstrumentor()
        self._fastapi_instrumentation.instrument_app(
            app,
            tracer_provider=self._provider,
            http_capture_headers_server_request=[],
            http_capture_headers_server_response=[],
            exclude_spans=["send", "receive"],
        )
        return True

    def force_flush(self, timeout_millis: int = 5000) -> bool:
        """Flush pending spans when the SDK is active."""
        if self._provider is None:
            return False
        return bool(self._provider.force_flush(timeout_millis=timeout_millis))

    @contextmanager
    def start_span(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Any]:
        """Create a span. Uses real OTel if available, else in-memory."""
        if self._real_tracer:
            with self._real_tracer.start_as_current_span(name) as otel_span:
                if attributes:
                    for k, v in attributes.items():
                        otel_span.set_attribute(k, v)
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
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": provider,
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": input_tokens,
            "gen_ai.usage.output_tokens": output_tokens,
            "gen_ai.usage.total_tokens": input_tokens + output_tokens,
            "duration_ms": duration_ms,
        }

        if self._real_tracer:
            with self._real_tracer.start_as_current_span(f"chat {model}") as span:
                for k, v in attrs.items():
                    span.set_attribute(k, v)
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
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
            "gen_ai.tool.type": "function",
            "tool.success": success,
            "duration_ms": duration_ms,
        }

        if self._real_tracer:
            with self._real_tracer.start_as_current_span(
                f"execute_tool {tool_name}",
                attributes=attrs,
            ) as span:
                if not success:
                    from opentelemetry.trace import StatusCode

                    span.set_status(StatusCode.ERROR)
        else:
            logger.debug("otel_tool_call", **attrs)

    def export_span(self, span: Span) -> None:
        """Export a completed runtime span under its active agent root when available."""
        if not self._real_tracer:
            return
        from opentelemetry import trace

        run_id = str(span.attributes.get("cogentrex.run.id", ""))
        parent = self._active_agent_spans.get(run_id)
        context = trace.set_span_in_context(parent) if parent is not None else None
        with self._real_tracer.start_as_current_span(
            span.name,
            attributes=span.attributes,
            context=context,
        ) as exported:
            if span.status == "error":
                from opentelemetry.trace import Status, StatusCode

                message = str(span.attributes.get("error.message", ""))
                exported.set_status(Status(StatusCode.ERROR, message))

    def start_agent_span(self, span: Span) -> None:
        """Start a long-lived agent root used to parent model and tool spans."""
        if not self._real_tracer:
            return
        run_id = str(span.attributes.get("cogentrex.run.id", ""))
        if not run_id or run_id in self._active_agent_spans:
            return
        self._active_agent_spans[run_id] = self._real_tracer.start_span(
            span.name,
            attributes=span.attributes,
        )

    def finish_agent_span(self, span: Span) -> None:
        """Apply terminal attributes and close a previously started agent root."""
        run_id = str(span.attributes.get("cogentrex.run.id", ""))
        exported = self._active_agent_spans.pop(run_id, None)
        if exported is None:
            self.export_span(span)
            return
        for key, value in span.attributes.items():
            exported.set_attribute(key, value)
        if span.status == "error":
            from opentelemetry.trace import Status, StatusCode

            message = str(span.attributes.get("error.message", ""))
            exported.set_status(Status(StatusCode.ERROR, message))
        exported.end()

    def shutdown(self) -> None:
        """Flush active agent spans and shut down the configured provider."""
        for span in self._active_agent_spans.values():
            span.end()
        self._active_agent_spans.clear()
        if self._provider is not None:
            self._provider.shutdown()


# Global instance
_exporter: OTLPExporter | None = None


def get_otel_exporter(
    endpoint: str = "http://localhost:4317",
) -> OTLPExporter:
    global _exporter
    if _exporter is None:
        _exporter = OTLPExporter(endpoint=endpoint)
    return _exporter
