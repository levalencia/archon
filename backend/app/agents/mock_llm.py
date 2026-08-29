"""Mock LLM adapter for deterministic text and structured-tool tests."""

from __future__ import annotations

from collections.abc import Sequence

from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition
from app.runtime.structured_output import ResponseContract


class MockLLM:
    capabilities = ProviderCapabilities(native_tools=True, usage=True)
    DEFAULT_RESPONSE = (
        "Mock mode: no live model inference was performed. "
        "Restart Archon with --live-provider for real responses."
    )
    EXHAUSTED_RESPONSE = "Mock response sequence exhausted; no live model inference was performed."

    def __init__(self, responses: Sequence[str | ModelResponse] | None = None) -> None:
        self._repeat_default = responses is None
        self.responses = list(responses) if responses is not None else [self.DEFAULT_RESPONSE]
        self.call_history: list[dict] = []
        self._call_count = 0

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
    ) -> ModelResponse:
        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")
        self.call_history.append(
            {
                "messages": tuple(messages),
                "tools": tuple(tools),
                "max_tokens": max_tokens,
                "response_contract": response_contract,
                "response_format": response_format,
            }
        )
        response = (
            self.responses[0]
            if self._repeat_default
            else self.responses[self._call_count]
            if self._call_count < len(self.responses)
            else self.EXHAUSTED_RESPONSE
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
