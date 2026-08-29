"""Adapters from typed runtime events to operational observability signals."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

import structlog

from app.observability import metrics
from app.observability.log_buffer import OwnerLogBuffer
from app.observability.logging import (
    get_correlation_id,
    redact_sensitive,
    safe_exception_metadata,
)
from app.observability.tracing import Span, Tracer, get_tracer
from app.runtime.events import AgentEvent, AgentEventKind, EventSink
from app.security.persistence_redactor import PersistenceRedactor

Clock = Callable[[], float]
_SECRET_KEY = re.compile(
    r"(?:authorization|api[-_]?key|token|secret|password|cookie|credential)", re.IGNORECASE
)


def sanitize(value: Any, *, key: str = "") -> Any:
    """Return a bounded, log-safe representation of runtime data."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_sensitive(value)[:1000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


class CompositeEventSink:
    """Map runtime events to metrics, spans, safe logs, persistence, and another sink."""

    def __init__(
        self,
        *,
        conversation_id: str,
        model: str,
        redactor: PersistenceRedactor,
        log_buffer: OwnerLogBuffer,
        user_id: str = "",
        project_id: str = "default",
        provider: str = "unknown",
        correlation_id: str | None = None,
        run_id: str | None = None,
        repository: Any | None = None,
        downstream: EventSink | None = None,
        tracer: Tracer | None = None,
        exporter: Any | None = None,
        clock: Clock = time.monotonic,
        logger: Any | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.project_id = project_id
        self.provider = provider
        self.model = model
        self.redactor = redactor
        self.log_buffer = log_buffer
        self.correlation_id = correlation_id or get_correlation_id()
        self.run_id = run_id or str(uuid.uuid4())
        self.repository = repository
        self.downstream = downstream
        self.tracer = tracer or get_tracer()
        self.exporter = exporter
        self.clock = clock
        self.logger = logger or structlog.get_logger()
        self._run: Span | None = None
        self._model_span: Span | None = None
        self._tools: dict[str, Span] = {}
        self._tool_count = 0

    @property
    def common_attributes(self) -> dict[str, str]:
        return {
            "archon.run.id": self.run_id,
            "archon.conversation.id": self.conversation_id,
            "archon.correlation.id": self.correlation_id,
        }

    def _start(self, name: str, attributes: dict[str, Any] | None = None) -> Span:
        span = Span(name, {**self.common_attributes, **(attributes or {})})
        span.start_time = self.clock()
        return span

    def _finish(self, span: Span, *, error: str | None = None) -> None:
        span.end_time = self.clock()
        span.attributes["duration_ms"] = round((span.end_time - span.start_time) * 1000, 3)
        if error:
            span.set_error(error)
        self.tracer.spans.append(span)
        if self.exporter is not None:
            try:
                self.exporter.export_span(span)
            except Exception as exc:
                self.logger.warning(
                    "runtime_span_export_failed",
                    **safe_exception_metadata(exc, "span_export_failed"),
                )

    async def emit(self, event: AgentEvent) -> None:
        now = self.clock()
        # Raw provider output is reserved for the requesting response sink. Every
        # operational and persistence path gets an independent redacted copy.
        safe_data = sanitize(self.redactor.redact_value(event.data))
        if event.kind in (AgentEventKind.MODEL_RESPONSE, AgentEventKind.RUN_STOPPED):
            if event.usage.cache_read_input_tokens is not None:
                safe_data["cache_read_input_tokens"] = event.usage.cache_read_input_tokens
            if event.usage.cache_write_input_tokens is not None:
                safe_data["cache_write_input_tokens"] = event.usage.cache_write_input_tokens
        common_log = {
            "event_kind": event.kind.value,
            "iteration": event.iteration,
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "correlation_id": self.correlation_id,
            "data": safe_data,
        }

        if event.kind is AgentEventKind.RUN_STARTED:
            metrics.record_run_started()
            self._run = self._start("agent.run", {"gen_ai.request.model": self.model})
        elif event.kind is AgentEventKind.ITERATION_STARTED:
            metrics.record_iteration()
            self._model_span = self._start(
                "gen_ai.chat",
                {"gen_ai.request.model": self.model, "archon.iteration": event.iteration},
            )
        elif event.kind is AgentEventKind.MODEL_RESPONSE:
            if self._model_span is None:
                self._model_span = self._start("gen_ai.chat", {"gen_ai.request.model": self.model})
            self._model_span.attributes.update(
                {
                    "gen_ai.response.finish_reasons": str(
                        safe_data.get("provider_stop_reason") or ""
                    ),
                    "gen_ai.usage.input_tokens": event.usage.input_tokens,
                    "gen_ai.usage.output_tokens": event.usage.output_tokens,
                    "gen_ai.usage.total_tokens": event.usage.total_tokens,
                }
            )
            if event.usage.cache_read_input_tokens is not None:
                self._model_span.attributes["gen_ai.usage.cache_read_input_tokens"] = (
                    event.usage.cache_read_input_tokens
                )
            if event.usage.cache_write_input_tokens is not None:
                self._model_span.attributes["gen_ai.usage.cache_write_input_tokens"] = (
                    event.usage.cache_write_input_tokens
                )
            duration = round((now - self._model_span.start_time) * 1000, 3)
            metrics.record_llm_call(self.model, event.usage.total_tokens, duration)
            self._finish(self._model_span)
            self._model_span = None
        elif event.kind is AgentEventKind.TOOL_CALL_REQUESTED:
            self._tool_count += 1
            call_id = str(safe_data.get("id", ""))
            name = str(safe_data.get("name", "unknown"))
            self._tools[call_id] = self._start(
                f"tool.{name}", {"tool.name": name, "tool.call.id": call_id}
            )
        elif event.kind is AgentEventKind.TOOL_CALL_COMPLETED:
            call_id = str(safe_data.get("id", ""))
            name = str(safe_data.get("name", "unknown"))
            span = self._tools.pop(call_id, None)
            if span is None:
                span = self._start(f"tool.{name}", {"tool.name": name})
            duration = round((now - span.start_time) * 1000, 3)
            metrics.record_tool_call(name, duration)
            span.attributes["tool.success"] = True
            self._finish(span)
        elif event.kind is AgentEventKind.RUN_STOPPED:
            reason = str(safe_data.get("reason", "unknown"))
            error = safe_data.get("error")
            for span in self._tools.values():
                tool_name = str(span.attributes.get("tool.name", "unknown"))
                metrics.record_tool_call(tool_name, 0, error=True)
                span.attributes["tool.success"] = False
                self._finish(span, error=str(error or reason))
            self._tools.clear()
            if self._model_span is not None:
                self._finish(self._model_span, error=str(error or reason))
                self._model_span = None
            if self._run is None:
                self._run = self._start("agent.run", {"gen_ai.request.model": self.model})
            self._run.attributes.update(
                {
                    "archon.stop_reason": reason,
                    "archon.iteration_count": event.iteration,
                    "archon.tool_call_count": self._tool_count,
                    "gen_ai.usage.input_tokens": event.usage.input_tokens,
                    "gen_ai.usage.output_tokens": event.usage.output_tokens,
                    "gen_ai.usage.total_tokens": event.usage.total_tokens,
                }
            )
            if event.usage.cache_read_input_tokens is not None:
                self._run.attributes["gen_ai.usage.cache_read_input_tokens"] = (
                    event.usage.cache_read_input_tokens
                )
            if event.usage.cache_write_input_tokens is not None:
                self._run.attributes["gen_ai.usage.cache_write_input_tokens"] = (
                    event.usage.cache_write_input_tokens
                )
            duration = round((now - self._run.start_time) * 1000, 3)
            metrics.record_run_stopped(
                reason, event.iteration, event.usage.total_tokens, duration, bool(error)
            )
            self._finish(self._run, error=str(error) if error else None)
            self._run = None

        self.logger.info("runtime_event", **common_log)
        self.log_buffer.append(
            owner_id=self.user_id,
            level="info",
            event="runtime_event",
            data=common_log,
        )
        if self.repository is not None:
            try:
                await self.repository.append_runtime_event(
                    run_id=self.run_id,
                    user_id=self.user_id,
                    project_id=self.project_id,
                    conversation_id=self.conversation_id,
                    correlation_id=self.correlation_id,
                    provider=self.provider,
                    model=self.model,
                    kind=event.kind.value,
                    iteration=event.iteration,
                    data=safe_data,
                    input_tokens=event.usage.input_tokens,
                    output_tokens=event.usage.output_tokens,
                    total_tokens=event.usage.total_tokens,
                )
            except Exception as error:
                self.logger.warning(
                    "runtime_event_persistence_failed",
                    **safe_exception_metadata(error, "event_persistence_failed"),
                )
        if self.downstream is not None:
            await self.downstream.emit(event)
