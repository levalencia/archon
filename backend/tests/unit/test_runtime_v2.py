from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
)
from app.runtime.capabilities import ProviderCapabilities
from app.tools.registry import SecureToolRegistry


def registry() -> SecureToolRegistry:
    tools = SecureToolRegistry()
    tools.register(
        "weather",
        lambda city: {"forecast": f"Sunny in {city}"},
        "Get weather",
        input_schema={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )
    return tools


@pytest.mark.asyncio
async def test_typed_tool_round_trip_and_events() -> None:
    provider = MockLLM(
        [
            ModelResponse(
                tool_calls=(ToolCall("call-1", "weather", {"city": "Brussels"}),),
                usage=TokenUsage(10, 3),
                provider_stop_reason="tool_use",
            ),
            ModelResponse("Sunny", usage=TokenUsage(15, 2), provider_stop_reason="end_turn"),
        ]
    )
    sink = RecordingEventSink()
    result = await AgentRuntime(provider, registry(), events=sink).run(
        [Message(Role.USER, "weather?")]
    )

    assert result.content == "Sunny"
    assert result.stop_reason is StopReason.COMPLETED
    assert result.usage == TokenUsage(25, 5)
    assert result.tool_calls[0]["tool"] == "weather"
    assert provider.call_history[1]["messages"][-1].tool_call_id == "call-1"
    assert [event.kind for event in sink.events] == [
        AgentEventKind.RUN_STARTED,
        AgentEventKind.ITERATION_STARTED,
        AgentEventKind.MODEL_RESPONSE,
        AgentEventKind.TOOL_CALL_REQUESTED,
        AgentEventKind.TOOL_CALL_COMPLETED,
        AgentEventKind.ITERATION_STARTED,
        AgentEventKind.MODEL_RESPONSE,
        AgentEventKind.TEXT_DELTA,
        AgentEventKind.RUN_STOPPED,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("budget", "response", "reason", "calls"),
    [
        (
            RuntimeBudget(max_iterations=1),
            ModelResponse(tool_calls=(ToolCall("1", "weather", {"city": "x"}),)),
            StopReason.ITERATION_BUDGET_EXHAUSTED,
            1,
        ),
        (
            RuntimeBudget(max_tool_calls=0),
            ModelResponse(tool_calls=(ToolCall("1", "weather", {"city": "x"}),)),
            StopReason.TOOL_BUDGET_EXHAUSTED,
            0,
        ),
        (
            RuntimeBudget(max_tokens=1),
            ModelResponse("cost", usage=TokenUsage(1, 1)),
            StopReason.TOKEN_BUDGET_EXHAUSTED,
            0,
        ),
    ],
)
async def test_explicit_budget_stop_reasons(budget, response, reason, calls) -> None:
    result = await AgentRuntime(MockLLM([response]), registry(), budget=budget).run(
        [Message(Role.USER, "x")]
    )
    assert result.stop_reason is reason
    assert len(result.tool_calls) == calls


@pytest.mark.asyncio
async def test_timeout_stop_reason() -> None:
    class Slow:
        capabilities = ProviderCapabilities(native_tools=True)

        async def complete(self, messages, tools=(), *, max_tokens=4096, response_contract=None):
            del response_contract
            await asyncio.sleep(0.1)
            return ModelResponse("late")

    result = await AgentRuntime(Slow(), registry(), budget=RuntimeBudget(max_seconds=0.001)).run(
        [Message(Role.USER, "x")]
    )
    assert result.stop_reason is StopReason.TIME_BUDGET_EXHAUSTED


@pytest.mark.asyncio
async def test_anthropic_native_tool_schema_and_tool_use(monkeypatch) -> None:
    import anthropic

    captured = {}

    class Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="tool_use", id="t1", name="weather", input={"city": "Ghent"}
                    )
                ],
                usage=SimpleNamespace(input_tokens=4, output_tokens=2),
                stop_reason="tool_use",
            )

    class Client:
        def __init__(self, **kwargs):
            self.messages = Messages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", Client)
    from app.agents.anthropic_adapter import AnthropicAdapter

    response = await AnthropicAdapter("secret").complete(
        [Message(Role.SYSTEM, "system"), Message(Role.USER, "weather")],
        registry().definitions(),
    )
    assert captured["tools"][0]["input_schema"]["required"] == ["city"]
    assert response.tool_calls == (ToolCall("t1", "weather", {"city": "Ghent"}),)
    assert response.usage == TokenUsage(4, 2)


@pytest.mark.asyncio
async def test_concurrent_runs_are_isolated() -> None:
    async def one(label: str):
        provider = MockLLM([ModelResponse(label)])
        sink = RecordingEventSink()
        result = await AgentRuntime(provider, registry(), events=sink).run(
            [Message(Role.USER, label)]
        )
        return result, sink

    (a, sink_a), (b, sink_b) = await asyncio.gather(one("alpha"), one("beta"))
    assert (a.content, b.content) == ("alpha", "beta")
    assert sink_a.events is not sink_b.events
    assert len(sink_a.events) == len(sink_b.events) == 5
