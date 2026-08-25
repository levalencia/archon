from __future__ import annotations

import pytest

from app.agents.mock_llm import MockLLM
from app.runtime import (
    AgentRuntime,
    Message,
    ModelResponse,
    Role,
    RuntimeBudget,
    StopReason,
    TokenUsage,
    ToolCall,
)
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
