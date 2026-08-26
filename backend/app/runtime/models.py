"""Typed values exchanged at the model-provider boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    images: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            object.__setattr__(self, "role", Role(self.role))

    def __getitem__(self, key: str) -> Any:
        """Temporary read-only compatibility for legacy message assertions."""
        if key == "role":
            return self.role.value
        if key == "content":
            return self.content
        if key == "tool_call_id":
            return self.tool_call_id
        raise KeyError(key)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A provider-decoded tool call. Runtime code never parses calls from text."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("tool call id and name must be non-empty")
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    provider_stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.content is None and not self.tool_calls:
            raise ValueError("a model response needs content or at least one tool call")
