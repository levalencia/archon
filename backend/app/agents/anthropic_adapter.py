"""Anthropic adapter using the official SDK and native tool_use blocks."""

from __future__ import annotations

from collections.abc import Sequence

from app.runtime.anthropic import anthropic_request, anthropic_response
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, ModelResponse, ToolDefinition
from app.runtime.structured_output import ResponseContract


class AnthropicAdapter:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        prompt_caching_enabled: bool = True,
    ) -> None:
        from anthropic import AsyncAnthropic

        self.model = model
        self.prompt_caching_enabled = prompt_caching_enabled
        self.capabilities = ProviderCapabilities(
            native_tools=True,
            images=True,
            json_mode=True,
            prompt_caching=prompt_caching_enabled,
            usage=True,
            stop_reason=True,
        )
        self._client = AsyncAnthropic(api_key=api_key)

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
        del response_contract
        request = anthropic_request(
            messages,
            tools,
            max_tokens,
            response_format=response_format,
            prompt_caching_enabled=self.prompt_caching_enabled,
        )
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
