"""Azure AI Foundry Anthropic adapter using official SDK tool schemas."""

from __future__ import annotations

from collections.abc import Sequence

from app.runtime.anthropic import anthropic_request, anthropic_response
from app.runtime.models import Message, ModelResponse, ToolDefinition


class FoundryAdapter:
    def __init__(self, api_key: str, base_url: str, model: str = "claude-opus-4-6") -> None:
        from anthropic import AsyncAnthropic

        self.model = model
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
    ) -> ModelResponse:
        request = anthropic_request(messages, tools, max_tokens)
        if hasattr(self._client, "messages"):
            response = await self._client.messages.create(model=self.model, **request)
            return anthropic_response(response)

        # Compatibility seam for injected HTTP transports used in deterministic tests.
        response = await self._client.post("/messages", json={"model": self.model, **request})
        response.raise_for_status()
        payload = response.json()
        content = "".join(
            block.get("text", "")
            for block in payload.get("content", ())
            if block.get("type") == "text"
        )
        usage = payload.get("usage", {})
        from app.runtime.models import TokenUsage

        return ModelResponse(
            content=content or None,
            usage=TokenUsage(
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
            ),
            provider_stop_reason=payload.get("stop_reason"),
        )

    async def chat(self, messages: list[dict[str, str]], max_tokens: int = 4096, **kwargs) -> str:
        del kwargs
        typed = [Message(role=item["role"], content=item["content"]) for item in messages]
        return (await self.complete(typed, max_tokens=max_tokens)).content or ""
