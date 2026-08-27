"""Shared construction and compatibility helpers for typed chat runs."""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any, cast

from app.runtime.capabilities import (
    TEXT_ONLY_CAPABILITIES,
    ProviderCapabilities,
    get_provider_capabilities,
)
from app.runtime.context import build_effective_context, build_messages
from app.runtime.context_provenance import EffectiveContext
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition
from app.runtime.ports import ModelProvider
from app.runtime.structured_output import ResponseContract


class JsonModeProvider:
    """Wrapper that injects response_format='json' into every complete() call."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.capabilities = get_provider_capabilities(delegate)
        self.routes_capabilities = (
            inspect.getattr_static(delegate, "routes_capabilities", False) is True
        )

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
        required_capabilities: ProviderCapabilities | None = None,
    ) -> ModelResponse:
        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")
        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if response_contract is not None:
            kwargs["response_contract"] = response_contract
        else:
            kwargs["response_format"] = "json"
        if self.routes_capabilities and required_capabilities is not None:
            kwargs["required_capabilities"] = required_capabilities
        response: ModelResponse = await self._delegate.complete(messages, tools, **kwargs)
        return response


class TextOnlyProvider:
    """Non-parsing compatibility adapter for providers without native tool support yet."""

    capabilities = TEXT_ONLY_CAPABILITIES
    routes_capabilities = False

    def __init__(self, client: Any) -> None:
        self.client = client

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
        del tools
        del response_contract
        del response_format
        legacy = [{"role": message.role.value, "content": message.content} for message in messages]
        text = await self.client.chat(legacy, max_tokens=max_tokens)
        return ModelResponse(text, usage=TokenUsage(output_tokens=max(1, len(text.split()))))


def as_model_provider(client: Any) -> ModelProvider:
    if callable(getattr(client, "complete", None)):
        return cast(ModelProvider, client)
    return TextOnlyProvider(client)


async def prepare_effective_context(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    skills_context: str,
    images: list[str] | None = None,
    user_id: str = "default",
    persistent_memory_text: str = "",
    *,
    project_id: str,
    run_id: str,
    memory_ids: tuple[str, ...] = (),
    skill_ids: tuple[str, ...] = (),
    current_message_id: int | None = None,
) -> EffectiveContext:
    return await build_effective_context(
        user_input,
        conversation_id,
        memory,
        tools,
        skills_context,
        images,
        user_id,
        persistent_memory_text,
        project_id=project_id,
        run_id=run_id,
        memory_ids=memory_ids,
        skill_ids=skill_ids,
        current_message_id=current_message_id,
    )


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
