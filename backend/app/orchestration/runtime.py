"""Canonical-runtime execution adapter for bounded child tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import suppress
from dataclasses import replace
from typing import Any

from app.delegation.envelope import DelegationEnvelopeService
from app.orchestration.models import (
    ChildResult,
    ChildStatus,
    ChildTask,
    ExecutionMode,
    OrchestrationOutcome,
)
from app.orchestration.service import HybridOrchestrationService
from app.orchestration.tools import build_read_only_registry
from app.reflection.models import ReflectionPolicy
from app.runtime.engine import RuntimeBudget, StopReason
from app.runtime.events import AgentEvent, AgentEventKind
from app.runtime.factory import RunContext, create_chat_event_sink, create_chat_runtime
from app.runtime.models import Message, Role
from app.runtime.monetary_budget import usd_limit_to_nusd
from app.runtime.ports import ModelProvider
from app.tools.registry import SecureToolRegistry


class RuntimeChildRunner:
    """Run one depth-one child through Archon's canonical typed runtime."""

    def __init__(
        self,
        *,
        parent_context: RunContext,
        provider: ModelProvider,
        tools: SecureToolRegistry,
        settings: Any,
        repository: Any,
        exporter: Any | None,
        redactor: Any,
        log_buffer: Any,
        envelopes: DelegationEnvelopeService,
    ) -> None:
        self._parent = parent_context
        self._provider = provider
        self._tools = tools
        self._settings = settings
        self._repository = repository
        self._exporter = exporter
        self._redactor = redactor
        self._log_buffer = log_buffer
        self._envelopes = envelopes

    async def __call__(self, task: ChildTask) -> ChildResult:
        task = replace(
            task,
            max_iterations=min(
                task.max_iterations,
                getattr(self._settings, "hybrid_orchestration_child_max_iterations", 4),
            ),
            max_tool_calls=min(
                task.max_tool_calls,
                getattr(self._settings, "hybrid_orchestration_child_max_tool_calls", 6),
            ),
            max_tokens=min(
                task.max_tokens,
                getattr(self._settings, "hybrid_orchestration_child_token_budget", 64_000),
            ),
            max_tool_result_chars=min(
                task.max_tool_result_chars,
                getattr(
                    self._settings,
                    "hybrid_orchestration_child_max_tool_result_chars",
                    3_000,
                ),
            ),
            timeout_seconds=min(
                task.timeout_seconds,
                getattr(self._settings, "hybrid_orchestration_child_deadline_seconds", 120.0),
            ),
        )
        child_tools = build_read_only_registry(self._tools, task.allowed_tools)
        capability_snapshot = [
            {
                "name": definition.name,
                "schema_hash": hashlib.sha256(
                    json.dumps(
                        dict(definition.input_schema),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
            }
            for definition in child_tools.definitions()
        ]
        canonical_scope = {
            "goal_hash": hashlib.sha256(task.goal.encode("utf-8")).hexdigest(),
            "profile_id": task.profile_id,
            "specialist_kind": task.kind.value,
            "capabilities": capability_snapshot,
            "output_contract": "bounded-text-v1",
        }
        budget = {
            "cost_nusd": usd_limit_to_nusd(
                self._settings.hybrid_orchestration_child_run_budget_usd
            ),
            "input_tokens": task.max_tokens,
            "output_tokens": task.max_tokens,
            "retries": 0,
            "timeout_seconds": task.timeout_seconds,
            "max_tool_result_chars": task.max_tool_result_chars,
        }
        context_hash = self._envelopes.context_digest(canonical_scope)
        envelope = self._envelopes.issue(
            parent_run_id=self._parent.run_id,
            child_run_id=task.child_run_id,
            owner_id=self._parent.user_id,
            project_id=self._parent.project_id,
            context_hash=context_hash,
            budget=budget,
        )
        if dict(envelope.budget) != budget:
            raise RuntimeError("delegation_budget_binding_failed")
        await self._envelopes.verify_and_consume(
            envelope,
            owner_id=self._parent.user_id,
            project_id=self._parent.project_id,
            parent_run_id=self._parent.run_id,
            child_run_id=task.child_run_id,
            context_hash=context_hash,
        )
        await self._repository.runs.ensure_child_run(
            run_id=task.child_run_id,
            parent_run_id=self._parent.run_id,
            user_id=self._parent.user_id,
            project_id=self._parent.project_id,
            provider=self._settings.llm_provider,
            model=self._settings.llm_model,
            conversation_id=self._parent.conversation_id,
            correlation_id=self._parent.correlation_id,
        )
        child_context = RunContext(
            user_id=self._parent.user_id,
            conversation_id=self._parent.conversation_id,
            run_id=task.child_run_id,
            correlation_id=self._parent.correlation_id,
            project_id=self._parent.project_id,
        )
        sink = create_chat_event_sink(
            context=child_context,
            settings=self._settings,
            repository=self._repository,
            exporter=self._exporter,
            redactor=self._redactor,
            log_buffer=self._log_buffer,
        )
        runtime = create_chat_runtime(
            context=child_context,
            provider=self._provider,
            tools=child_tools,
            settings=self._settings,
            repository=self._repository,
            exporter=self._exporter,
            redactor=self._redactor,
            log_buffer=self._log_buffer,
            event_sink=sink,
            run_limit_usd=getattr(
                self._settings, "hybrid_orchestration_child_run_budget_usd", None
            ),
            runtime_budget=RuntimeBudget(
                max_iterations=task.max_iterations,
                max_tool_calls=task.max_tool_calls,
                max_tokens=task.max_tokens,
                max_seconds=task.timeout_seconds,
                max_tool_result_chars=task.max_tool_result_chars,
                max_structured_retries=0,
                max_context_tokens=self._settings.context_length,
            ),
            reflection_policy=ReflectionPolicy(enabled=False),
        )
        started = time.monotonic()
        try:
            result = await runtime.run(
                [
                    Message(Role.SYSTEM, task.system_prompt),
                    Message(Role.USER, task.goal),
                ]
            )
        except asyncio.CancelledError:
            with suppress(Exception):
                await asyncio.wait_for(
                    asyncio.shield(
                        sink.emit(
                            AgentEvent(
                                AgentEventKind.RUN_STOPPED,
                                0,
                                {"reason": "cancelled", "error": "cancelled"},
                            )
                        )
                    ),
                    timeout=2.0,
                )
            raise
        elapsed_ms = (time.monotonic() - started) * 1000
        await self._repository.runs.finalize_metadata(
            self._parent.user_id,
            task.child_run_id,
            answer=result.content,
            latency_ms=elapsed_ms,
        )
        status = (
            ChildStatus.COMPLETED
            if result.stop_reason is StopReason.COMPLETED and bool(result.content)
            else ChildStatus.TIMED_OUT
            if result.stop_reason is StopReason.TIME_BUDGET_EXHAUSTED
            else ChildStatus.CANCELLED
            if result.error == "cancelled"
            else ChildStatus.FAILED
        )
        return ChildResult(
            child_run_id=task.child_run_id,
            profile_id=task.profile_id,
            kind=task.kind,
            status=status,
            content=result.content,
            usage=result.usage,
            iterations=result.iterations,
            tool_calls=result.tool_calls,
            reason_code=None if status is ChildStatus.COMPLETED else result.stop_reason.value,
        )


async def prepare_hybrid_messages(
    *,
    query: str,
    requested_mode: ExecutionMode,
    messages: list[Message],
    parent_context: RunContext,
    provider: ModelProvider,
    tools: SecureToolRegistry,
    settings: Any,
    repository: Any,
    exporter: Any | None,
    redactor: Any,
    log_buffer: Any,
    envelopes: DelegationEnvelopeService | None,
    event_sink: Any,
) -> OrchestrationOutcome:
    """Prepare parent messages and run bounded children when Team is selected."""

    service = HybridOrchestrationService(
        enabled=bool(getattr(settings, "hybrid_orchestration_enabled", False))
        and envelopes is not None,
        max_children=int(getattr(settings, "hybrid_orchestration_max_children", 2)),
        total_timeout_seconds=float(
            getattr(settings, "hybrid_orchestration_total_deadline_seconds", 240.0)
        ),
    )

    async def unavailable_child(task: ChildTask) -> ChildResult:
        del task
        raise RuntimeError("delegation_envelopes_unavailable")

    runner = (
        RuntimeChildRunner(
            parent_context=parent_context,
            provider=provider,
            tools=tools,
            settings=settings,
            repository=repository,
            exporter=exporter,
            redactor=redactor,
            log_buffer=log_buffer,
            envelopes=envelopes,
        )
        if envelopes is not None
        else unavailable_child
    )
    return await service.prepare(
        query=query,
        requested_mode=requested_mode,
        parent_run_id=parent_context.run_id,
        messages=messages,
        events=event_sink,
        child_runner=runner,
    )
