"""Tests for Reflexion / self-correction in the agent runtime."""

from __future__ import annotations

import pytest

from app.runtime import AgentRuntime, RuntimeBudget
from app.runtime.events import AgentEvent, AgentEventKind, EventSink
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition


class _CollectorSink(EventSink):
    def __init__(self):
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


class _FailFirstThenSucceedTools:
    """Tool executor that fails the first call and succeeds the second."""

    def __init__(self):
        self.call_count = 0

    def definitions(self):
        return (
            ToolDefinition("flaky_tool", "A tool that fails once then works", {"type": "object"}),
        )

    async def execute(self, call):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("Connection timeout — server unreachable")
        return {"result": "success on retry", "attempt": self.call_count}


class _ReflexionModel:
    """Model that calls a tool, gets an error, then retries with adjusted params."""

    def __init__(self):
        self.call_count = 0

    async def complete(self, messages, tools=(), *, max_tokens=4096):
        self.call_count += 1
        # Check if the last message is a tool error
        has_error = any(m.role == Role.TOOL and "error" in m.content.lower() for m in messages)
        if self.call_count == 1:
            # First call: request the flaky tool
            return ModelResponse(
                "Let me try this tool.",
                tool_calls=(ToolCall("t1", "flaky_tool", {"param": "first"}),),
                usage=TokenUsage(input_tokens=100, output_tokens=20),
            )
        elif has_error and self.call_count == 2:
            # Second call: saw the error, retry with different params (reflexion!)
            return ModelResponse(
                "The tool failed. Let me retry with adjusted parameters.",
                tool_calls=(ToolCall("t2", "flaky_tool", {"param": "retry"}),),
                usage=TokenUsage(input_tokens=150, output_tokens=30),
            )
        else:
            # Third call: got success, produce final answer
            return ModelResponse(
                "The tool succeeded on retry. The answer is 42.",
                usage=TokenUsage(input_tokens=200, output_tokens=50),
            )


@pytest.mark.asyncio
async def test_reflexion_self_correction():
    """Agent should catch tool errors, feed them back, and let LLM retry."""
    sink = _CollectorSink()
    tools = _FailFirstThenSucceedTools()
    model = _ReflexionModel()

    runtime = AgentRuntime(
        model, tools, events=sink, budget=RuntimeBudget(max_iterations=5, max_tool_calls=4)
    )
    result = await runtime.run([Message(Role.USER, "test reflexion")])

    # Should complete successfully (not ERROR)
    assert result.stop_reason.value == "completed"
    assert "42" in result.content

    # Tool was called twice (first failed, second succeeded)
    assert tools.call_count == 2

    # Model was called 3 times (initial + retry + final)
    assert model.call_count == 3

    # Should have 2 tool_call_completed events
    tool_completed = [e for e in sink.events if e.kind == AgentEventKind.TOOL_CALL_COMPLETED]
    assert len(tool_completed) == 2

    # First tool call should have error status
    first_output = tool_completed[0].data["output"]
    assert "error" in first_output
    assert "reflexion_hint" in first_output

    # Second tool call should have success
    second_output = tool_completed[1].data["output"]
    assert second_output["result"] == "success on retry"


@pytest.mark.asyncio
async def test_reflexion_error_visible_in_result():
    """Failed tool calls should appear in the result's tool_calls list."""
    tools = _FailFirstThenSucceedTools()
    model = _ReflexionModel()

    runtime = AgentRuntime(model, tools, budget=RuntimeBudget(max_iterations=5, max_tool_calls=4))
    result = await runtime.run([Message(Role.USER, "test")])

    # Both calls (failed + succeeded) should be in the list
    assert len(result.tool_calls) == 2
    assert result.tool_calls[0]["status"] == "error"
    assert result.tool_calls[1]["status"] == "success"
