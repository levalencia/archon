"""Tests for OTEL tracing wiring."""

from __future__ import annotations

import json

import pytest

from app.observability.log_buffer import OwnerLogBuffer
from app.observability.runtime_events import CompositeEventSink
from app.observability.tracing import Span, Tracer
from app.runtime import AgentEvent, AgentEventKind, TokenUsage, ToolDefinition
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
        provider="foundry",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=tracer,
        exporter=exporter,
        clock=clock,
        tool_definitions=(
            ToolDefinition(
                name="calculator",
                description="Evaluate a bounded arithmetic expression",
                input_schema={
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            ),
        ),
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

    # Exporter should receive a model span and an OTel GenAI agent invocation.
    exported_names = [s.name for s in exporter.exported]
    assert "chat test-model" in exported_names
    assert "invoke_agent Archon" in exported_names
    agent_span = next(s for s in exporter.exported if s.name == "invoke_agent Archon")
    assert agent_span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert agent_span.attributes["gen_ai.agent.name"] == "Archon"
    assert agent_span.attributes["gen_ai.agent.call.id"] == sink.run_id
    assert agent_span.attributes["gen_ai.conversation.id"] == "conv-otel-1"
    assert agent_span.attributes["gen_ai.request.model"] == "test-model"
    assert agent_span.attributes["archon.provider"] == "foundry"
    assert json.loads(agent_span.attributes["gen_ai.tool.definitions"]) == [
        {
            "type": "function",
            "name": "calculator",
            "description": "Evaluate a bounded arithmetic expression",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        }
    ]
    assert json.loads(agent_span.attributes["logfire.json_schema"])["properties"][
        "gen_ai.tool.definitions"
    ] == {"type": "array"}
    assert "gen_ai.input.messages" not in agent_span.attributes
    assert "gen_ai.output.messages" not in agent_span.attributes
    assert "gen_ai.system_instructions" not in agent_span.attributes
    model_span = next(s for s in exporter.exported if s.name == "chat test-model")
    assert (
        model_span.attributes["gen_ai.tool.definitions"]
        == agent_span.attributes["gen_ai.tool.definitions"]
    )
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
    assert "execute_tool web_search" in exported_names
    tool_span = next(s for s in exporter.exported if s.name == "execute_tool web_search")
    assert tool_span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool_span.attributes["gen_ai.tool.name"] == "web_search"
    assert tool_span.attributes["gen_ai.tool.type"] == "function"
    assert tool_span.attributes["gen_ai.tool.call.id"] == "call-42"
    assert tool_span.attributes["gen_ai.agent.name"] == "Archon"
    assert tool_span.attributes["gen_ai.agent.call.id"] == sink.run_id
    assert tool_span.attributes["gen_ai.conversation.id"] == "conv-otel-2"
    assert tool_span.attributes["logfire.msg"] == "running tool: web_search"
    assert tool_span.attributes["tool.success"] is True
    assert "gen_ai.tool.call.arguments" not in tool_span.attributes
    assert "gen_ai.tool.call.result" not in tool_span.attributes


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
    assert any(s.name == "invoke_agent Archon" for s in tracer.spans)
