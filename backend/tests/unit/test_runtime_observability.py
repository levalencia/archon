"""Deterministic tests for the typed runtime observability adapter."""

from __future__ import annotations

import pytest

from app.observability.log_buffer import OwnerLogBuffer
from app.observability.logging import redact_event
from app.observability.metrics import get_metrics_snapshot, reset_metrics
from app.observability.runtime_events import CompositeEventSink
from app.observability.tracing import Tracer
from app.runtime import AgentEvent, AgentEventKind, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class Repository:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def append_runtime_event(self, **event) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def clean_metrics() -> None:
    reset_metrics()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_exact_event_to_metric_span_and_correlation_mapping() -> None:
    clock = Clock()
    tracer = Tracer()
    repository = Repository()
    sink = CompositeEventSink(
        conversation_id="conversation-1",
        correlation_id="correlation-1",
        run_id="run-1",
        model="model-1",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        repository=repository,
        tracer=tracer,
        clock=clock,
    )
    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    clock.value = 0.1
    await sink.emit(AgentEvent(AgentEventKind.ITERATION_STARTED, 1))
    clock.value = 0.3
    await sink.emit(
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            1,
            {"provider_stop_reason": "tool_use"},
            TokenUsage(5, 3),
        )
    )
    await sink.emit(
        AgentEvent(
            AgentEventKind.TOOL_CALL_REQUESTED,
            1,
            {"id": "call-1", "name": "search", "arguments": {"query": "safe"}},
        )
    )
    clock.value = 0.5
    await sink.emit(
        AgentEvent(
            AgentEventKind.TOOL_CALL_COMPLETED,
            1,
            {"id": "call-1", "name": "search", "output": {"result": "ok"}},
        )
    )
    clock.value = 1.0
    await sink.emit(
        AgentEvent(
            AgentEventKind.RUN_STOPPED,
            1,
            {"reason": "completed", "error": None},
            TokenUsage(5, 3),
        )
    )

    snapshot = get_metrics_snapshot()
    assert snapshot["totals"]["agent_runs"] == 1
    assert snapshot["totals"]["agent_errors"] == 0
    assert snapshot["totals"]["agent_iterations"] == 1
    assert snapshot["totals"]["agent_tokens"] == 8
    assert snapshot["totals"]["llm_calls"] == 1
    assert snapshot["totals"]["llm_tokens"] == 8
    assert snapshot["totals"]["tool_calls"] == 1
    assert snapshot["stop_reasons"] == {"completed": 1}
    assert snapshot["by_model"]["model-1"] == {"calls": 1, "tokens": 8, "latency": 200.0}
    assert snapshot["by_tool"]["search"] == {"calls": 1, "errors": 0, "latency": 200.0}
    assert [span.name for span in tracer.spans] == ["gen_ai.chat", "tool.search", "agent.run"]
    for span in tracer.spans:
        assert span.attributes["archon.run.id"] == "run-1"
        assert span.attributes["archon.conversation.id"] == "conversation-1"
        assert span.attributes["archon.correlation.id"] == "correlation-1"
    assert tracer.spans[-1].attributes["archon.stop_reason"] == "completed"
    assert tracer.spans[-1].attributes["archon.tool_call_count"] == 1
    assert {event["kind"] for event in repository.events} == {
        "run_started",
        "iteration_started",
        "model_response",
        "tool_call_requested",
        "tool_call_completed",
        "run_stopped",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_timeout_event_marks_metrics_and_spans() -> None:
    clock = Clock()
    tracer = Tracer()
    sink = CompositeEventSink(
        conversation_id="conversation-1",
        run_id="run-1",
        model="model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=tracer,
        clock=clock,
    )
    await sink.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    clock.value = 2.0
    await sink.emit(
        AgentEvent(
            AgentEventKind.RUN_STOPPED,
            1,
            {"reason": "time_budget_exhausted", "error": "TimeoutError: deadline"},
        )
    )
    assert get_metrics_snapshot()["totals"]["agent_errors"] == 1
    assert tracer.spans[-1].status == "error"
    assert tracer.spans[-1].attributes["error.message"] == "TimeoutError: deadline"


def test_log_redaction_is_recursive_and_handles_free_form_values() -> None:
    event = redact_event(
        None,
        "info",
        {
            "authorization": "Bearer top-secret",
            "arguments": {"password": "hunter2", "query": "token=abc123"},
            "output": "api_key=xyz789",
        },
    )
    rendered = repr(event)
    assert "top-secret" not in rendered
    assert "hunter2" not in rendered
    assert "abc123" not in rendered
    assert "xyz789" not in rendered
    assert rendered.count("[REDACTED]") == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recent_runtime_events_are_persisted_and_retrieved(tmp_path) -> None:
    repository = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path}/events.db", PersistenceRedactor()
    )
    await repository.initialize()
    try:
        await repository.append_runtime_event(
            run_id="run-1",
            conversation_id="conversation-1",
            correlation_id="correlation-1",
            kind="run_started",
            iteration=0,
            data={"safe": True},
        )
        assert await repository.recent_runtime_events(run_id="run-1") == [
            {
                "run_id": "run-1",
                "conversation_id": "conversation-1",
                "correlation_id": "correlation-1",
                "kind": "run_started",
                "iteration": 0,
                "data": {"safe": True},
            }
        ]
    finally:
        await repository.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_event_persistence_is_bounded(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/bounded-events.db")
    await store.initialize()
    try:
        for index in range(3):
            await store.append_runtime_event(
                {
                    "run_id": f"run-{index}",
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-1",
                    "kind": "run_started",
                    "iteration": index,
                    "data": {},
                },
                max_events=2,
            )
        events = await store.recent_runtime_events(run_id=None, limit=10)
        assert [event["run_id"] for event in events] == ["run-1", "run-2"]
    finally:
        await store.close()
