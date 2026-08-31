from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.agents.mock_llm import MockLLM
from app.runtime import (
    AgentEventKind,
    AgentRuntime,
    Message,
    ModelResponse,
    RecordingEventSink,
    Role,
    RuntimeBudget,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from app.runtime.capabilities import ProviderCapabilities
from app.tools.registry import SecureToolRegistry


def _registry(counter: dict[str, int]) -> SecureToolRegistry:
    registry = SecureToolRegistry()

    async def search(query: str) -> dict:
        counter[query] = counter.get(query, 0) + 1
        return {"query": query, "content": "evidence " * 5000}

    registry.register(
        "web_search",
        search,
        "Search",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    return registry


@pytest.mark.asyncio
async def test_duplicate_tool_calls_execute_only_once() -> None:
    counter: dict[str, int] = {}
    duplicate = ToolCall("call-1", "web_search", {"query": "same query"})
    repeated = ToolCall("call-2", "web_search", {"query": "same query"})
    provider = MockLLM(
        [
            ModelResponse(tool_calls=(duplicate, repeated)),
            ModelResponse("Final answer from existing evidence."),
        ]
    )

    result = await AgentRuntime(provider, _registry(counter)).run([Message(Role.USER, "research")])

    assert result.stop_reason is StopReason.COMPLETED
    assert result.content == "Final answer from existing evidence."
    assert counter == {"same query": 1}
    assert len(result.tool_calls) == 1


@pytest.mark.asyncio
async def test_token_budget_exhaustion_forces_tool_free_synthesis() -> None:
    counter: dict[str, int] = {}
    provider = MockLLM(
        [
            ModelResponse(
                content="I will investigate.",
                tool_calls=(ToolCall("call-1", "web_search", {"query": "evidence"}),),
                usage=TokenUsage(input_tokens=8, output_tokens=4),
            ),
            ModelResponse("Complete synthesis with limitations stated."),
        ]
    )

    result = await AgentRuntime(
        provider,
        _registry(counter),
        budget=RuntimeBudget(max_tokens=10, final_synthesis_tokens=128),
    ).run([Message(Role.USER, "research")])

    assert result.stop_reason is StopReason.TOKEN_BUDGET_EXHAUSTED
    assert result.stop_reason.value == "token_budget_exhausted"
    assert result.content == "Complete synthesis with limitations stated."
    assert provider.call_history[-1]["tools"] == ()


@pytest.mark.asyncio
async def test_tool_results_are_bounded_before_returning_to_model() -> None:
    counter: dict[str, int] = {}
    provider = MockLLM(
        [
            ModelResponse(tool_calls=(ToolCall("call-1", "web_search", {"query": "large"}),)),
            ModelResponse("Done."),
        ]
    )

    result = await AgentRuntime(
        provider,
        _registry(counter),
        budget=RuntimeBudget(max_tool_result_chars=200),
    ).run([Message(Role.USER, "research")])

    tool_message = provider.call_history[1]["messages"][-1]
    assert result.stop_reason is StopReason.COMPLETED
    assert len(tool_message.content) <= 215
    assert tool_message.content.endswith("...[truncated]")


@pytest.mark.asyncio
async def test_runtime_deadline_detaches_cancellation_resistant_tool_and_stops_batch() -> None:
    """A timed-out in-process tool may finish later, but cannot re-enter runtime bookkeeping."""

    class CancellationResistantTools:
        def __init__(self) -> None:
            self.started: list[str] = []
            self.late_finished = asyncio.Event()

        def definitions(self) -> Sequence[ToolDefinition]:
            return (ToolDefinition("slow"), ToolDefinition("later"))

        async def execute(self, call: ToolCall) -> Mapping[str, Any]:
            self.started.append(call.name)
            if call.name == "later":
                return {"unexpected": True}
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                # Deliberately refuse cancellation. The runtime must not await this cleanup.
                await asyncio.sleep(0.2)
            self.late_finished.set()
            return {"late": "result that the runtime must ignore"}

    tools = CancellationResistantTools()
    sink = RecordingEventSink()
    model = MockLLM(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall("slow-1", "slow"),
                    ToolCall("later-1", "later"),
                )
            ),
            ModelResponse("must not be reached"),
        ]
    )
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    started_at = loop.time()
    try:
        result = await AgentRuntime(
            model,
            tools,
            events=sink,
            budget=RuntimeBudget(max_seconds=0.03),
        ).run([Message(Role.USER, "run both")])
        elapsed = loop.time() - started_at

        assert result.stop_reason is StopReason.TIME_BUDGET_EXHAUSTED
        assert elapsed < 0.15
        assert result.tool_calls == ()
        assert tools.started == ["slow"]
        assert len(model.call_history) == 1
        assert AgentEventKind.TOOL_CALL_COMPLETED not in [event.kind for event in sink.events]
        assert AgentEventKind.TOOL_PROGRESS not in [event.kind for event in sink.events]
        assert sink.events[-1].kind is AgentEventKind.RUN_STOPPED
        assert sink.events[-1].data["reason"] == StopReason.TIME_BUDGET_EXHAUSTED.value

        await asyncio.wait_for(tools.late_finished.wait(), timeout=0.5)
        await asyncio.sleep(0)
        assert result.tool_calls == ()
        assert tools.started == ["slow"]
        assert AgentEventKind.TOOL_CALL_COMPLETED not in [event.kind for event in sink.events]
        assert unhandled == []
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_adversarial_text_exceeding_context_bound_never_reaches_provider() -> None:
    provider = MockLLM([ModelResponse("must not run")])
    content = "!@#$%^&*()_+-=[]{};:,.<>?/" * 700

    result = await AgentRuntime(
        provider,
        _registry({}),
        budget=RuntimeBudget(max_context_tokens=6_000, context_output_reserve_tokens=500),
    ).run([Message(Role.USER, content)])

    assert result.stop_reason is StopReason.CONTEXT_BUDGET_EXHAUSTED
    assert provider.call_history == []


@pytest.mark.asyncio
async def test_runtime_deadline_bounds_cancellation_resistant_event_sink_before_provider() -> None:
    finished = asyncio.Event()

    class SlowSink(RecordingEventSink):
        async def emit(self, event) -> None:
            if event.kind is AgentEventKind.RUN_STARTED:
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    await asyncio.sleep(0.08)
                finished.set()
            await super().emit(event)

    provider = MockLLM([ModelResponse("must not run")])
    started = asyncio.get_running_loop().time()
    result = await AgentRuntime(
        provider,
        _registry({}),
        events=SlowSink(),
        budget=RuntimeBudget(max_seconds=0.01),
    ).run([Message(Role.USER, "answer")])

    assert asyncio.get_running_loop().time() - started < 0.08
    assert result.stop_reason is StopReason.TIME_BUDGET_EXHAUSTED
    assert provider.call_history == []
    await asyncio.wait_for(finished.wait(), timeout=0.3)
    assert provider.call_history == []


@pytest.mark.asyncio
async def test_runtime_deadline_detaches_cancellation_resistant_provider_exception() -> None:
    """A provider's late exception is consumed instead of becoming an event-loop warning."""

    class CancellationResistantProvider:
        capabilities = ProviderCapabilities(native_tools=True)

        def __init__(self) -> None:
            self.late_finished = asyncio.Event()

        async def complete(self, messages, tools=(), *, max_tokens=4096, response_contract=None):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.1)
            self.late_finished.set()
            raise RuntimeError("late provider failure")

    provider = CancellationResistantProvider()
    sink = RecordingEventSink()
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, Any]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    started_at = loop.time()
    try:
        result = await AgentRuntime(
            provider,
            _registry({}),
            events=sink,
            budget=RuntimeBudget(max_seconds=0.02),
        ).run([Message(Role.USER, "answer")])
        elapsed = loop.time() - started_at

        assert result.stop_reason is StopReason.TIME_BUDGET_EXHAUSTED
        assert elapsed < 0.08
        assert [event.kind for event in sink.events] == [
            AgentEventKind.RUN_STARTED,
            AgentEventKind.ITERATION_STARTED,
            AgentEventKind.RUN_STOPPED,
        ]
        await asyncio.wait_for(provider.late_finished.wait(), timeout=0.3)
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        loop.set_exception_handler(previous_handler)
