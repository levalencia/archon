"""Deterministic tests for the typed runtime observability adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.observability.log_buffer import OwnerLogBuffer
from app.observability.logging import redact_event
from app.observability.metrics import get_metrics_snapshot, reset_metrics
from app.observability.runtime_events import CompositeEventSink
from app.observability.tracing import Tracer
from app.runtime import AgentEvent, AgentEventKind, AgentRuntime, Message, Role, TokenUsage
from app.runtime.capabilities import ProviderCapabilities
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore, RunRow, RuntimeEventRow
from app.tools.registry import SecureToolRegistry


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_content_is_opt_in_redacted_and_logfire_renderable() -> None:
    disabled_tracer = Tracer()
    disabled = CompositeEventSink(
        conversation_id="conversation-private",
        run_id="run-private",
        model="model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=disabled_tracer,
        input_content="private user input",
        capture_message_content=False,
    )
    await disabled.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    disabled.capture_assistant_response("private assistant output")
    await disabled.emit(AgentEvent(AgentEventKind.RUN_STOPPED, 1))
    private_root = next(
        span for span in disabled_tracer.spans if span.name == "invoke_agent Cogentrex"
    )
    assert "gen_ai.input.messages" not in private_root.attributes
    assert "gen_ai.output.messages" not in private_root.attributes
    assert "pydantic_ai.all_messages" not in private_root.attributes
    assert "final_result" not in private_root.attributes

    enabled_tracer = Tracer()
    enabled = CompositeEventSink(
        conversation_id="conversation-visible",
        run_id="run-visible",
        model="model",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        tracer=enabled_tracer,
        input_content="Show this user input from alice@example.com",
        capture_message_content=True,
    )
    await enabled.emit(AgentEvent(AgentEventKind.RUN_STARTED, 0))
    enabled.capture_assistant_response("Show this assistant output for alice@example.com")
    await enabled.emit(AgentEvent(AgentEventKind.RUN_STOPPED, 1))
    visible_root = next(
        span for span in enabled_tracer.spans if span.name == "invoke_agent Cogentrex"
    )

    assert json.loads(visible_root.attributes["gen_ai.input.messages"]) == [
        {
            "role": "user",
            "parts": [{"type": "text", "content": "Show this user input from [EMAIL]"}],
        }
    ]
    assert json.loads(visible_root.attributes["gen_ai.output.messages"]) == [
        {
            "role": "assistant",
            "parts": [{"type": "text", "content": "Show this assistant output for [EMAIL]"}],
        }
    ]
    assert visible_root.attributes["final_result"] == "Show this assistant output for [EMAIL]"
    assert "alice@example.com" not in str(visible_root.attributes)
    assert len(json.loads(visible_root.attributes["pydantic_ai.all_messages"])) == 2
    schema = json.loads(visible_root.attributes["logfire.json_schema"])
    assert schema["properties"]["pydantic_ai.all_messages"] == {"type": "array"}


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
    assert [span.name for span in tracer.spans] == [
        "chat model-1",
        "execute_tool search",
        "invoke_agent Cogentrex",
    ]
    for span in tracer.spans:
        assert span.attributes["cogentrex.run.id"] == "run-1"
        assert span.attributes["cogentrex.conversation.id"] == "conversation-1"
        assert span.attributes["cogentrex.correlation.id"] == "correlation-1"
    assert tracer.spans[-1].attributes["cogentrex.stop_reason"] == "completed"
    assert tracer.spans[-1].attributes["cogentrex.tool_call_count"] == 1
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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelled_runtime_is_terminal_in_durable_ledger(tmp_path) -> None:
    class BlockingProvider:
        capabilities = ProviderCapabilities(native_tools=True)

        def __init__(self) -> None:
            self.started = asyncio.Event()

        async def complete(
            self,
            messages,
            tools=(),
            *,
            max_tokens=4096,
            response_contract=None,
            response_format=None,
        ):
            del messages, tools, max_tokens, response_contract, response_format
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    repository = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path}/cancelled-run.db", PersistenceRedactor()
    )
    await repository.initialize()
    try:
        await repository.create("conversation-cancel", "Cancellation", "alice")
        provider = BlockingProvider()
        sink = CompositeEventSink(
            conversation_id="conversation-cancel",
            user_id="alice",
            run_id="run-cancel",
            correlation_id="correlation-cancel",
            model="model",
            redactor=PersistenceRedactor(),
            log_buffer=OwnerLogBuffer(),
            repository=repository,
        )
        task = asyncio.create_task(
            AgentRuntime(provider, SecureToolRegistry(), events=sink).run(
                [Message(Role.USER, "cancel me")]
            )
        )
        await provider.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        run = await repository.runs.get("alice", "run-cancel")
        assert run is not None
        assert run.status == "cancelled"
        assert run.stop_reason == "cancelled"
        assert run.iterations == 1
        events = await repository.runs.events("alice", "run-cancel")
        assert events is not None
        assert events.items[-1].kind == AgentEventKind.RUN_STOPPED.value
    finally:
        await repository.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reported_cache_usage_is_safe_persisted_and_traced_but_absence_is_omitted() -> None:
    tracer = Tracer()
    repository = Repository()
    sink = CompositeEventSink(
        conversation_id="conversation-1",
        user_id="user-1",
        run_id="run-1",
        model="claude-sonnet-4-20250514",
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        repository=repository,
        tracer=tracer,
    )
    await sink.emit(AgentEvent(AgentEventKind.ITERATION_STARTED, 1))
    await sink.emit(
        AgentEvent(
            AgentEventKind.MODEL_RESPONSE,
            1,
            {},
            TokenUsage(12, 2, cache_read_input_tokens=7, cache_write_input_tokens=0),
        )
    )
    await sink.emit(
        AgentEvent(AgentEventKind.RUN_STOPPED, 1, {"reason": "completed"}, TokenUsage(12, 2))
    )

    response = next(event for event in repository.events if event["kind"] == "model_response")
    stopped = next(event for event in repository.events if event["kind"] == "run_stopped")
    assert response["data"] == {
        "cache_read_input_tokens": 7,
        "cache_write_input_tokens": 0,
    }
    assert "cache_read_input_tokens" not in stopped["data"]
    model_span = next(span for span in tracer.spans if span.name == "chat claude-sonnet-4-20250514")
    assert model_span.attributes["gen_ai.usage.cache_read_input_tokens"] == 7
    assert model_span.attributes["gen_ai.usage.cache_write_input_tokens"] == 0


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
async def test_runtime_event_budget_retains_active_run_and_complete_history(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/bounded-events.db")
    await store.initialize()
    try:
        for index in range(3):
            await store.append_runtime_event(
                {
                    "run_id": "active-run",
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-1",
                    "kind": "run_started" if index == 0 else "iteration_started",
                    "iteration": index,
                    "data": {},
                },
                max_events=1,
            )
        events = await store.recent_runtime_events(run_id=None, limit=10)
        assert [(event["run_id"], event["iteration"]) for event in events] == [
            ("active-run", 0),
            ("active-run", 1),
            ("active-run", 2),
        ]
        async with store.session_factory() as session:
            run = await session.get(RunRow, "active-run")
        assert run is not None
        assert run.status == "running"
    finally:
        await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runtime_event_budget_prunes_oldest_terminal_run_whole(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path}/whole-run-retention.db")
    await store.initialize()
    try:
        for run_id in ("old-terminal", "new-terminal"):
            await store.append_runtime_event(
                {
                    "run_id": run_id,
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-1",
                    "kind": "run_started",
                    "iteration": 0,
                    "data": {},
                }
            )
            await store.append_runtime_event(
                {
                    "run_id": run_id,
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-1",
                    "kind": "run_stopped",
                    "iteration": 1,
                    "data": {"reason": "completed", "error": None},
                }
            )
        async with store.session_factory() as session:
            old = datetime.now(tz=UTC) - timedelta(days=2)
            new = datetime.now(tz=UTC) - timedelta(days=1)
            await session.execute(
                update(RunRow).where(RunRow.run_id == "old-terminal").values(completed_at=old)
            )
            await session.execute(
                update(RunRow).where(RunRow.run_id == "new-terminal").values(completed_at=new)
            )
            await session.commit()

        for iteration in range(3):
            await store.append_runtime_event(
                {
                    "run_id": "active-run",
                    "conversation_id": "conversation-1",
                    "correlation_id": "correlation-1",
                    "kind": "run_started" if iteration == 0 else "iteration_started",
                    "iteration": iteration,
                    "data": {},
                },
                max_events=100 if iteration < 2 else 5,
            )

        async with store.session_factory() as session:
            runs = set((await session.scalars(select(RunRow.run_id))).all())
            histories = {
                run_id: list(
                    (
                        await session.scalars(
                            select(RuntimeEventRow.sequence)
                            .where(RuntimeEventRow.run_id == run_id)
                            .order_by(RuntimeEventRow.sequence)
                        )
                    ).all()
                )
                for run_id in runs
            }
        assert runs == {"new-terminal", "active-run"}
        assert histories == {"new-terminal": [1, 2], "active-run": [1, 2, 3]}
    finally:
        await store.close()
