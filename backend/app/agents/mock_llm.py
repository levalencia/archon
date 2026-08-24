"""Mock LLM adapter for deterministic text and structured-tool tests."""

from __future__ import annotations

from collections.abc import Sequence

from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition


class MockLLM:
    def __init__(self, responses: Sequence[str | ModelResponse] | None = None) -> None:
        self.responses = list(responses) if responses else ["I am a mock LLM."]
        self.call_history: list[dict] = []
        self._call_count = 0

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.call_history.append(
            {"messages": tuple(messages), "tools": tuple(tools), "max_tokens": max_tokens}
        )
        response = (
            self.responses[self._call_count]
            if self._call_count < len(self.responses)
            else "I don't have more responses configured."
        )
        self._call_count += 1
        if isinstance(response, ModelResponse):
            return response
        return ModelResponse(
            response, usage=TokenUsage(output_tokens=max(1, len(response.split())))
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        del temperature
        typed = [Message(role=item["role"], content=item["content"]) for item in messages]
        response = await self.complete(typed, max_tokens=max_tokens)
        return response.content or ""
