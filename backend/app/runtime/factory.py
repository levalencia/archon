"""Shared construction of policy-aware runtimes for every live chat transport."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.observability.runtime_events import CompositeEventSink
from app.runtime.engine import AgentRuntime, RuntimeBudget
from app.runtime.events import EventSink
from app.runtime.ports import ModelProvider, ToolAuthorizer
from app.security.default_policy import default_policy_engine
from app.tools.registry import SecureToolRegistry


@dataclass(frozen=True, slots=True)
class RunContext:
    """Immutable owner and tracing identity for one runtime invocation."""

    user_id: str
    conversation_id: str
    run_id: str
    correlation_id: str
    project_id: str = "default"

    @classmethod
    def create(
        cls, *, user_id: str, conversation_id: str, correlation_id: str, project_id: str = "default"
    ) -> RunContext:
        return cls(user_id, conversation_id, str(uuid.uuid4()), correlation_id, project_id)


def create_chat_runtime(
    *,
    context: RunContext,
    provider: ModelProvider,
    tools: SecureToolRegistry,
    settings: Any,
    repository: Any,
    exporter: Any | None,
    downstream: EventSink | None = None,
    authorizer: ToolAuthorizer | None = None,
) -> AgentRuntime:
    """Build the single supported live runtime configuration.

    Provider wrappers (for example JSON mode) are deliberately applied by the caller before
    entering this factory. Sync omits an authorizer, causing ASK policy decisions to fail closed.
    """
    sink = CompositeEventSink(
        conversation_id=context.conversation_id,
        correlation_id=context.correlation_id,
        run_id=context.run_id,
        model=settings.llm_model,
        repository=repository,
        exporter=exporter,
        downstream=downstream,
    )
    return AgentRuntime(
        provider,
        tools,
        events=sink,
        budget=RuntimeBudget(
            max_iterations=settings.agent_max_iterations,
            max_tool_calls=8,
            max_tokens=settings.agent_token_budget,
            max_seconds=90,
        ),
        policy_engine=default_policy_engine(),
        authorizer=authorizer,
        approval_timeout_seconds=settings.approval_timeout_seconds,
    )
