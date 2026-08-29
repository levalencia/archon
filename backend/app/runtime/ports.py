"""Ports implemented by model and tool adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from app.runtime.models import Message, ModelResponse, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract
from app.security.approvals import AuthorizationOutcome, AuthorizationRequest
from app.security.policy import PolicyRequest


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
    ) -> ModelResponse: ...


class ToolExecutor(Protocol):
    async def execute(self, call: ToolCall) -> Mapping[str, Any]: ...

    def definitions(self) -> Sequence[ToolDefinition]: ...


@runtime_checkable
class PolicyAwareToolExecutor(ToolExecutor, Protocol):
    """Optional extension for runtimes that consume typed policy metadata."""

    def policy_request(self, call: ToolCall) -> PolicyRequest: ...


class ToolAuthorizer(Protocol):
    """Asynchronous human/host authorization boundary; implementations own no runtime policy."""

    async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome: ...


@runtime_checkable
class PreparatoryToolAuthorizer(ToolAuthorizer, Protocol):
    """Optional authorizer extension that reserves a request before it is published."""

    async def prepare(self, request: AuthorizationRequest) -> None: ...

    async def cancel(self, request: AuthorizationRequest) -> None: ...
