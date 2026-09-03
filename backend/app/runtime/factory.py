"""Shared construction of policy-aware runtimes for every live chat transport."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.observability.log_buffer import OwnerLogBuffer
from app.observability.runtime_events import CompositeEventSink
from app.reflection.models import ReflectionPolicy
from app.reflection.service import derive_reflection_hmac_key
from app.runtime.effect_executor import DurableEffectToolExecutor, EffectRunContext
from app.runtime.engine import AgentRuntime, RuntimeBudget
from app.runtime.events import EventSink
from app.runtime.monetary_budget import (
    BudgetRunContext,
    DurableBudgetedProvider,
    PricingCandidate,
    usd_limit_to_nusd,
)
from app.runtime.ports import ModelProvider, ToolAuthorizer
from app.security.default_policy import default_policy_engine
from app.security.persistence_redactor import PersistenceRedactor
from app.services.effect_ledger import EffectRepository
from app.services.monetary_budget import MonetaryBudgetRepository
from app.tools.registry import SecureToolRegistry

_SUPPORTED_PRICING_PROVIDERS = frozenset({"mock", "openai", "anthropic", "foundry", "ollama"})
_CONTEXT_OUTPUT_RESERVE_TOKENS = 4_096


def _pricing_candidates(settings: Any) -> tuple[PricingCandidate, ...]:
    names = [settings.llm_provider]
    names.extend(
        name.strip() for name in settings.llm_fallback_providers.split(",") if name.strip()
    )
    candidates: list[PricingCandidate] = []
    seen: set[tuple[str, str]] = set()
    for raw_name in names:
        name = raw_name.strip().lower()
        if name not in _SUPPORTED_PRICING_PROVIDERS:
            continue
        candidate = PricingCandidate(name, settings.llm_model)
        pair = (candidate.provider, candidate.model)
        if pair not in seen:
            candidates.append(candidate)
            seen.add(pair)
    if not candidates:
        raise ValueError("durable budget requires at least one priced provider/model")
    return tuple(candidates)


def budget_model_provider(
    provider: ModelProvider,
    *,
    settings: Any,
    repository: Any,
    user_id: str,
    project_id: str,
    run_id: str,
) -> ModelProvider:
    """Wrap one run's provider with durable monetary enforcement when enabled."""

    if not settings.durable_monetary_budget_enabled:
        return provider
    session_factory = getattr(repository, "session_factory", None)
    if session_factory is None:
        raise RuntimeError("durable budget requires a repository session factory")
    max_input_tokens = settings.context_length - _CONTEXT_OUTPUT_RESERVE_TOKENS
    if max_input_tokens < 1:
        raise ValueError("context length must exceed the output reservation")
    return DurableBudgetedProvider(
        provider,
        MonetaryBudgetRepository(session_factory),
        BudgetRunContext(user_id, project_id, run_id),
        run_limit_nusd=usd_limit_to_nusd(settings.agent_run_budget_usd),
        project_limit_nusd=usd_limit_to_nusd(settings.agent_project_budget_usd),
        max_input_tokens=max_input_tokens,
        pricing_candidates=_pricing_candidates(settings),
        quote_input_headroom_tokens=settings.agent_model_input_quote_headroom_tokens,
    )


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
    redactor: PersistenceRedactor,
    log_buffer: OwnerLogBuffer,
    downstream: EventSink | None = None,
    authorizer: ToolAuthorizer | None = None,
    result_recorder: Callable[[str], Awaitable[None]] | None = None,
) -> AgentRuntime:
    """Build the single supported live runtime configuration.

    Provider wrappers (for example JSON mode) are deliberately applied by the caller before
    entering this factory. Sync omits an authorizer, causing ASK policy decisions to fail closed.
    """
    sink = CompositeEventSink(
        conversation_id=context.conversation_id,
        user_id=context.user_id,
        project_id=context.project_id,
        correlation_id=context.correlation_id,
        run_id=context.run_id,
        model=settings.llm_model,
        provider=settings.llm_provider,
        redactor=redactor,
        log_buffer=log_buffer,
        repository=repository,
        exporter=exporter,
        downstream=downstream,
    )
    provider = budget_model_provider(
        provider,
        settings=settings,
        repository=repository,
        user_id=context.user_id,
        project_id=context.project_id,
        run_id=context.run_id,
    )

    runtime_tools: Any = tools
    if settings.durable_effect_ledger_enabled:
        session_factory = getattr(repository, "session_factory", None)
        if session_factory is None:
            raise RuntimeError("durable effect ledger requires a repository session factory")
        runtime_tools = DurableEffectToolExecutor(
            tools,
            EffectRepository(session_factory),
            EffectRunContext(context.user_id, context.project_id, context.run_id),
            settings.effect_identity_secret.get_secret_value().encode("utf-8"),
        )

    return AgentRuntime(
        provider,
        runtime_tools,
        events=sink,
        budget=RuntimeBudget(
            max_iterations=settings.agent_max_iterations,
            max_tool_calls=8,
            max_tokens=settings.agent_token_budget,
            max_seconds=settings.agent_deadline_seconds,
            max_structured_retries=settings.structured_output_retries,
            max_context_tokens=settings.context_length,
            context_output_reserve_tokens=_CONTEXT_OUTPUT_RESERVE_TOKENS,
        ),
        policy_engine=default_policy_engine(),
        authorizer=authorizer,
        approval_timeout_seconds=settings.approval_timeout_seconds,
        result_recorder=result_recorder,
        reflection_policy=ReflectionPolicy(
            enabled=settings.reflection_enabled,
            rubric_id=settings.reflection_rubric_id,
            rubric_version=settings.reflection_rubric_version,
            max_revisions=settings.reflection_max_revisions,
            max_input_tokens=settings.reflection_input_tokens,
            max_output_tokens=settings.reflection_output_tokens,
            max_seconds=settings.reflection_timeout_seconds,
            max_cost_usd=settings.reflection_max_cost_usd,
            input_cost_per_million_usd=settings.reflection_input_cost_per_million_usd,
            output_cost_per_million_usd=settings.reflection_output_cost_per_million_usd,
        ),
        reflection_hash_key=derive_reflection_hmac_key(settings.secret_key),
        reflection_hash_scope="\0".join((context.user_id, context.project_id, context.run_id)),
    )
