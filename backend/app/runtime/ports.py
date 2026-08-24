"""Ports implemented by model and tool adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.runtime.models import Message, ModelResponse, ToolCall, ToolDefinition


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
    ) -> ModelResponse: ...


class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall) -> Mapping[str, Any]: ...

    def definitions(self) -> Sequence[ToolDefinition]: ...
