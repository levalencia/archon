"""Tests for OTEL tracing wiring."""

from __future__ import annotations

import pytest

from app.observability.log_buffer import OwnerLogBuffer
from app.observability.runtime_events import CompositeEventSink
from app.observability.tracing import Span, Tracer
from app.runtime import AgentEvent, AgentEventKind, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class FakeExporter:
    """Collects exported spans for assertions."""

    def __init__(self) -> None:
        self.exported: list[Span] = []

    def export_span(self, span: Span) -> None:
        self.exported.append(span)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_otel_exporter_receives_spans_when_wired():
    """When an exporter is passed, CompositeEventSink exports every completed span."""
    clock = Clock()
    tracer = Tracer()
    exporter = FakeExporter()

    sink = CompositeEventSink(
        conversation_id="conv-otel-1",
        model="test-model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=tracer,
        exporter=exporter,
        clock=clock,
    )

    # Full agent lifecycle: run_started -> iteration -> model_response -> run_stopped
    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    clock.value = 0.1
    await sink.emit(AgentEvent(AgentEventKind.ITERATION_STARTED, 1))
    clock.value = 0.3
    await sink.emit(
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            1,
            {"provider_stop_reason": "end_turn"},
            TokenUsage(10, 5),
        )
    )
    clock.value = 1.0
    await sink.emit(
        AgentEvent(
            AgentEventKind.RUN_STOPPED,
            1,
            {"reason": "completed", "error": None},
            TokenUsage(10, 5),
        )
    )

    # Exporter should have received: gen_ai.chat + agent.run
    exported_names = [s.name for s in exporter.exported]
    assert "gen_ai.chat" in exported_names
    assert "agent.run" in exported_names
    assert len(exporter.exported) >= 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_otel_exporter_receives_tool_spans():
    """Tool call spans are exported to the OTEL exporter."""
    clock = Clock()
    tracer = Tracer()
    exporter = FakeExporter()

    sink = CompositeEventSink(
        conversation_id="conv-otel-2",
        model="test-model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=tracer,
        exporter=exporter,
        clock=clock,
    )

    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    clock.value = 0.1
    await sink.emit(
        AgentEvent(
            AgentEventKind.TOOL_CALL_REQUESTED,
            1,
            {"id": "call-42", "name": "web_search", "arguments": {"q": "test"}},
        )
    )
    clock.value = 0.5
    await sink.emit(
        AgentEvent(
            AgentEventKind.TOOL_CALL_COMPLETED,
            1,
            {"id": "call-42", "name": "web_search", "output": "results"},
        )
    )
    clock.value = 1.0
    await sink.emit(
        AgentEvent(
            AgentEventKind.RUN_STOPPED,
            1,
            {"reason": "completed", "error": None},
            TokenUsage(10, 5),
        )
    )

    exported_names = [s.name for s in exporter.exported]
    assert "tool.web_search" in exported_names
    # Verify tool attributes
    tool_span = next(s for s in exporter.exported if s.name == "tool.web_search")
    assert tool_span.attributes["tool.name"] == "web_search"
    assert tool_span.attributes["tool.success"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_exporter_means_no_export():
    """When no exporter is passed, spans are still collected by tracer but not exported."""
    clock = Clock()
    tracer = Tracer()

    sink = CompositeEventSink(
        conversation_id="conv-otel-3",
        model="test-model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=tracer,
        exporter=None,
        clock=clock,
    )

    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    clock.value = 1.0
    await sink.emit(
        AgentEvent(
            AgentEventKind.RUN_STOPPED,
            1,
            {"reason": "completed", "error": None},
            TokenUsage(0, 0),
        )
    )

    # Tracer still collects spans even without exporter
    assert len(tracer.spans) >= 1
    assert any(s.name == "agent.run" for s in tracer.spans)
