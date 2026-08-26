"""Shared construction and compatibility helpers for typed chat runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.runtime.context import build_messages
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition


class JsonModeProvider:
    """Wrapper that injects response_format='json' into every complete() call."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        return await self._delegate.complete(
            messages, tools, max_tokens=max_tokens, response_format="json"
        )


class TextOnlyProvider:
    """Non-parsing compatibility adapter for providers without native tool support yet."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del tools
        del response_format
        legacy = [{"role": message.role.value, "content": message.content} for message in messages]
        text = await self.client.chat(legacy, max_tokens=max_tokens)
        return ModelResponse(text, usage=TokenUsage(output_tokens=max(1, len(text.split()))))


def as_model_provider(client: Any) -> Any:
    return client if callable(getattr(client, "complete", None)) else TextOnlyProvider(client)


async def prepare_messages(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    skills_context: str,
    images: list[str] | None = None,
    user_id: str = "default",
    persistent_memory_text: str = "",
) -> list[Message]:
    return await build_messages(
        user_input,
        conversation_id,
        memory,
        tools,
        skills_context,
        images,
        user_id,
        persistent_memory_text,
    )
