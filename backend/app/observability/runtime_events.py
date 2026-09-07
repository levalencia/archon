"""Adapters from typed runtime events to operational observability signals."""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
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
from app.runtime.models import ToolDefinition
from app.security.persistence_redactor import PersistenceRedactor

Clock = Callable[[], float]
_AGENT_NAME = "Archon"
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


def _plain_json(value: Any) -> Any:
    """Convert trusted tool metadata into JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


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
        tool_definitions: Iterable[ToolDefinition] = (),
        input_content: str = "",
        capture_message_content: bool = False,
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
        self.tool_definitions = tuple(tool_definitions)
        self.capture_message_content = capture_message_content
        self._input_content = self._safe_message_content(input_content)
        self._assistant_content = ""
        self.clock = clock
        self.logger = logger or structlog.get_logger()
        self._run: Span | None = None
        self._model_span: Span | None = None
        self._tools: dict[str, Span] = {}
        self._tool_count = 0

    def _safe_message_content(self, content: str) -> str:
        if not self.capture_message_content or not content:
            return ""
        safe = sanitize(self.redactor.redact_value(content))
        return safe if isinstance(safe, str) else str(safe)

    @staticmethod
    def _otel_message(role: str, content: str) -> dict[str, Any]:
        return {"role": role, "parts": [{"type": "text", "content": content}]}

    def capture_assistant_response(self, content: str) -> None:
        """Capture only final assistant text when explicit content export is enabled."""
        self._assistant_content = self._safe_message_content(content)

    @staticmethod
    def _extend_json_schema(attributes: dict[str, Any], key: str, value_type: str) -> None:
        raw_schema = attributes.get("logfire.json_schema")
        schema: dict[str, Any] = (
            json.loads(raw_schema) if isinstance(raw_schema, str) else {"type": "object"}
        )
        properties: dict[str, Any] = schema.setdefault("properties", {})
        properties[key] = {"type": value_type}
        attributes["logfire.json_schema"] = json.dumps(schema, separators=(",", ":"))

    def _attach_input_content(self, attributes: dict[str, Any]) -> None:
        if not self._input_content:
            return
        attributes["gen_ai.input.messages"] = json.dumps(
            [self._otel_message("user", self._input_content)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._extend_json_schema(attributes, "gen_ai.input.messages", "array")

    def _attach_output_content(self, attributes: dict[str, Any]) -> None:
        if not self._assistant_content:
            return
        output = [self._otel_message("assistant", self._assistant_content)]
        attributes["gen_ai.output.messages"] = json.dumps(
            output, ensure_ascii=False, separators=(",", ":")
        )
        attributes["final_result"] = self._assistant_content
        messages = []
        if self._input_content:
            messages.append(self._otel_message("user", self._input_content))
        messages.extend(output)
        attributes["pydantic_ai.all_messages"] = json.dumps(
            messages, ensure_ascii=False, separators=(",", ":")
        )
        attributes["pydantic_ai.new_message_index"] = 0
        self._extend_json_schema(attributes, "gen_ai.output.messages", "array")
        self._extend_json_schema(attributes, "pydantic_ai.all_messages", "array")

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
                finish_agent = getattr(self.exporter, "finish_agent_span", None)
                if span is self._run and callable(finish_agent):
                    finish_agent(span)
                else:
                    self.exporter.export_span(span)
            except Exception as exc:
                self.logger.warning(
                    "runtime_span_export_failed",
                    **safe_exception_metadata(exc, "span_export_failed"),
                )

    def _begin_agent_export(self, span: Span) -> None:
        if self.exporter is None:
            return
        start_agent = getattr(self.exporter, "start_agent_span", None)
        if not callable(start_agent):
            return
        try:
            start_agent(span)
        except Exception as exc:
            self.logger.warning(
                "runtime_agent_span_start_failed",
                **safe_exception_metadata(exc, "agent_span_start_failed"),
            )

    def _tool_definition_attributes(self) -> dict[str, str]:
        if not self.tool_definitions:
            return {}
        return {
            "gen_ai.tool.definitions": json.dumps(
                [
                    {
                        "type": "function",
                        "name": definition.name,
                        "description": definition.description,
                        "parameters": _plain_json(definition.input_schema),
                    }
                    for definition in self.tool_definitions
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "logfire.json_schema": json.dumps(
                {
                    "type": "object",
                    "properties": {"gen_ai.tool.definitions": {"type": "array"}},
                },
                separators=(",", ":"),
            ),
        }

    def _start_agent_span(self) -> Span:
        """Create the privacy-safe OTel GenAI root span indexed by Logfire Agents."""
        attributes: dict[str, Any] = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": _AGENT_NAME,
            "gen_ai.agent.call.id": self.run_id,
            "gen_ai.conversation.id": self.conversation_id,
            "gen_ai.request.model": self.model,
            "gen_ai.output.type": "text",
            "logfire.msg": f"{_AGENT_NAME} run",
            "archon.provider": self.provider,
            **self._tool_definition_attributes(),
        }
        self._attach_input_content(attributes)
        return self._start(f"invoke_agent {_AGENT_NAME}", attributes)

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
            self._run = self._start_agent_span()
            self._begin_agent_export(self._run)
        elif event.kind is AgentEventKind.ITERATION_STARTED:
            metrics.record_iteration()
            self._model_span = self._start(
                f"chat {self.model}",
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.agent.name": _AGENT_NAME,
                    "gen_ai.agent.call.id": self.run_id,
                    "gen_ai.conversation.id": self.conversation_id,
                    "gen_ai.request.model": self.model,
                    "archon.iteration": event.iteration,
                    **self._tool_definition_attributes(),
                },
            )
        elif event.kind is AgentEventKind.MODEL_RESPONSE:
            if self._model_span is None:
                self._model_span = self._start(
                    f"chat {self.model}",
                    {
                        "gen_ai.operation.name": "chat",
                        "gen_ai.agent.name": _AGENT_NAME,
                        "gen_ai.agent.call.id": self.run_id,
                        "gen_ai.conversation.id": self.conversation_id,
                        "gen_ai.request.model": self.model,
                        **self._tool_definition_attributes(),
                    },
                )
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
                f"execute_tool {name}",
                {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": name,
                    "gen_ai.tool.type": "function",
                    "gen_ai.tool.call.id": call_id,
                    "gen_ai.agent.name": _AGENT_NAME,
                    "gen_ai.agent.call.id": self.run_id,
                    "gen_ai.conversation.id": self.conversation_id,
                    "logfire.msg": f"running tool: {name}",
                },
            )
        elif event.kind is AgentEventKind.TOOL_CALL_COMPLETED:
            call_id = str(safe_data.get("id", ""))
            name = str(safe_data.get("name", "unknown"))
            span = self._tools.pop(call_id, None)
            if span is None:
                span = self._start(
                    f"execute_tool {name}",
                    {
                        "gen_ai.operation.name": "execute_tool",
                        "gen_ai.tool.name": name,
                        "gen_ai.tool.type": "function",
                        "gen_ai.agent.name": _AGENT_NAME,
                        "gen_ai.agent.call.id": self.run_id,
                        "gen_ai.conversation.id": self.conversation_id,
                        "logfire.msg": f"running tool: {name}",
                    },
                )
            duration = round((now - span.start_time) * 1000, 3)
            metrics.record_tool_call(name, duration)
            span.attributes["tool.success"] = True
            self._finish(span)
        elif event.kind is AgentEventKind.RUN_STOPPED:
            reason = str(safe_data.get("reason", "unknown"))
            error = safe_data.get("error")
            for span in self._tools.values():
                tool_name = str(span.attributes.get("gen_ai.tool.name", "unknown"))
                metrics.record_tool_call(tool_name, 0, error=True)
                span.attributes["tool.success"] = False
                self._finish(span, error=str(error or reason))
            self._tools.clear()
            if self._model_span is not None:
                self._finish(self._model_span, error=str(error or reason))
                self._model_span = None
            if self._run is None:
                self._run = self._start_agent_span()
                self._begin_agent_export(self._run)
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
            self._attach_output_content(self._run.attributes)
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
