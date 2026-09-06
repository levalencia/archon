"""Contracts for the bounded hybrid multi-agent pilot."""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import SecretStr, ValidationError

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.observability.log_buffer import OwnerLogBuffer
from app.orchestration.models import (
    ChildResult,
    ChildStatus,
    ExecutionMode,
    SpecialistKind,
)
from app.orchestration.profiles import build_pilot_plan
from app.orchestration.routing import resolve_execution_mode
from app.orchestration.service import HybridOrchestrationService, _safe_finding
from app.orchestration.tools import build_read_only_registry
from app.reflection.models import ReflectionPolicy
from app.runtime.engine import RuntimeBudget
from app.runtime.events import AgentEventKind, RecordingEventSink
from app.runtime.factory import RunContext, create_chat_runtime
from app.runtime.models import Message, Role, TokenUsage, ToolCall
from app.security.persistence_redactor import PersistenceRedactor
from app.security.policy import RiskClass
from app.tools.registry import SecureToolRegistry


def test_auto_routes_simple_request_to_single() -> None:
    decision = resolve_execution_mode("Explain idempotency.", ExecutionMode.AUTO, enabled=True)

    assert decision.resolved_mode is ExecutionMode.SINGLE
    assert decision.reason_code == "single_default"


def test_auto_keeps_general_complex_request_on_single() -> None:
    decision = resolve_execution_mode(
        "Investigate the implementation, compare the architecture trade-offs, "
        "and verify the evidence.",
        ExecutionMode.AUTO,
        enabled=True,
    )

    assert decision.resolved_mode is ExecutionMode.SINGLE
    assert decision.reason_code == "single_default"


def test_auto_routes_multi_signal_security_risk_analysis_to_team() -> None:
    decision = resolve_execution_mode(
        "Produce a threat model for prompt injection and data exfiltration attacks.",
        ExecutionMode.AUTO,
        enabled=True,
    )

    assert decision.resolved_mode is ExecutionMode.TEAM
    assert decision.reason_code == "security_risk_analysis"


def test_auto_does_not_route_from_one_weak_security_reference() -> None:
    decision = resolve_execution_mode(
        "Compare two architectures and mention their security trade-offs.",
        ExecutionMode.AUTO,
        enabled=True,
    )

    assert decision.resolved_mode is ExecutionMode.SINGLE
    assert decision.reason_code == "insufficient_team_evidence"


def test_auto_requires_at_least_two_security_risk_signals() -> None:
    decision = resolve_execution_mode(
        "Assess this threat.",
        ExecutionMode.AUTO,
        enabled=True,
    )

    assert decision.resolved_mode is ExecutionMode.SINGLE
    assert decision.reason_code == "insufficient_team_evidence"


def test_forced_team_degrades_to_single_when_feature_is_disabled() -> None:
    decision = resolve_execution_mode("Research this", ExecutionMode.TEAM, enabled=False)

    assert decision.resolved_mode is ExecutionMode.SINGLE
    assert decision.reason_code == "feature_disabled"
    assert decision.degraded is True


def test_hybrid_mode_requires_a_delegation_signing_key() -> None:
    with pytest.raises(ValidationError, match="delegation signing key"):
        Settings(
            verifier_enabled=False,
            hybrid_orchestration_enabled=True,
            delegation_signing_key=SecretStr(""),
        )


def test_runtime_factory_honors_explicit_child_budget_override() -> None:
    settings = Settings(llm_provider="mock", verifier_enabled=False)
    budget = RuntimeBudget(
        max_iterations=1,
        max_tool_calls=2,
        max_tokens=321,
        max_seconds=4.0,
        max_structured_retries=0,
        max_context_tokens=settings.context_length,
    )
    runtime = create_chat_runtime(
        context=RunContext.create(
            user_id="user-1",
            conversation_id="conversation-1",
            correlation_id="correlation-1",
        ),
        provider=MockLLM(),
        tools=SecureToolRegistry(),
        settings=settings,
        repository=object(),
        exporter=None,
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
        event_sink=RecordingEventSink(),
        runtime_budget=budget,
        reflection_policy=ReflectionPolicy(enabled=False),
    )

    assert runtime._budget is budget


def test_pilot_plan_contains_one_fixed_and_one_dynamic_child() -> None:
    plan = build_pilot_plan("Compare the architecture and verify its safety", max_children=2)

    assert [task.kind for task in plan.tasks] == [SpecialistKind.FIXED, SpecialistKind.DYNAMIC]
    assert plan.tasks[0].profile_id == "researcher-v1"
    assert plan.tasks[1].profile_id == "dynamic-analyst-v1"
    assert all(task.allowed_tools for task in plan.tasks)
    assert all(task.max_tool_result_chars == 3_000 for task in plan.tasks)


def test_pilot_plan_rejects_an_invalid_child_limit() -> None:
    with pytest.raises(ValueError, match="max_children"):
        build_pilot_plan("Research this", max_children=0)


def test_pilot_plan_bounds_child_goals_for_maximum_chat_input() -> None:
    plan = build_pilot_plan("x" * 10_000)

    assert all(len(task.goal) == 10_000 for task in plan.tasks)


def test_untrusted_findings_strip_unicode_format_controls() -> None:
    assert _safe_finding("safe\u202eevil\u2066text") == "safeeviltext"


@pytest.mark.asyncio
async def test_child_registry_exposes_only_allowed_non_effectful_tools() -> None:
    parent = SecureToolRegistry()
    parent.register(
        "lookup",
        lambda query: {"query": query},
        input_schema={"required": ["query"]},
        risk_classes=frozenset({RiskClass.READ}),
    )
    parent.register(
        "write_file",
        lambda path: {"path": path},
        input_schema={"required": ["path"]},
        risk_classes=frozenset({RiskClass.WRITE}),
        requires_approval=True,
    )

    child = build_read_only_registry(parent, ("lookup", "write_file"))

    assert [definition.name for definition in child.definitions()] == ["lookup"]
    assert await child.execute(ToolCall("call-1", "lookup", {"query": "safe"})) == {"query": "safe"}
    with pytest.raises(ValueError, match="Unknown tool"):
        await child.execute(ToolCall("call-2", "write_file", {"path": "blocked"}))


@pytest.mark.asyncio
async def test_team_service_emits_safe_events_and_augments_parent_context() -> None:
    sink = RecordingEventSink()

    async def run_child(task):
        return ChildResult(
            child_run_id=task.child_run_id,
            profile_id=task.profile_id,
            kind=task.kind,
            status=ChildStatus.COMPLETED,
            content=f"bounded result from {task.profile_id}",
            usage=TokenUsage(10, 4),
            iterations=1,
            tool_calls=(),
        )

    service = HybridOrchestrationService(enabled=True, max_children=2)
    outcome = await service.prepare(
        query="Compare the architecture and verify the evidence across the implementation.",
        requested_mode=ExecutionMode.TEAM,
        parent_run_id="parent-run",
        messages=[Message(Role.USER, "original request")],
        events=sink,
        child_runner=run_child,
    )

    assert outcome.decision.resolved_mode is ExecutionMode.TEAM
    assert len(outcome.children) == 2
    assert len(outcome.messages) == 3
    guard = next(message for message in outcome.messages if message.role is Role.SYSTEM)
    delegated = next(
        message
        for message in outcome.messages
        if message.role is Role.USER and "DELEGATED_FINDINGS_UNTRUSTED" in message.content
    )
    assert "untrusted data" in guard.content.lower()
    assert "never emit tool_call or function_call json" in guard.content.lower()
    assert "begin directly with the final answer" in guard.content.lower()
    assert "bounded result" in delegated.content
    assert [event.kind for event in sink.events] == [
        AgentEventKind.ORCHESTRATION_ROUTED,
        AgentEventKind.DELEGATION_REQUESTED,
        AgentEventKind.DELEGATION_COMPLETED,
        AgentEventKind.DELEGATION_REQUESTED,
        AgentEventKind.DELEGATION_COMPLETED,
    ]
    assert all("content" not in event.data for event in sink.events)


@pytest.mark.asyncio
async def test_single_service_never_calls_child_runner() -> None:
    called = False

    async def run_child(task):
        nonlocal called
        called = True
        raise AssertionError(task)

    outcome = await HybridOrchestrationService(enabled=True).prepare(
        query="Explain retries.",
        requested_mode=ExecutionMode.SINGLE,
        parent_run_id="parent-run",
        messages=[Message(Role.USER, "Explain retries.")],
        events=RecordingEventSink(),
        child_runner=run_child,
    )

    assert outcome.decision.resolved_mode is ExecutionMode.SINGLE
    assert outcome.children == ()
    assert called is False


@pytest.mark.asyncio
async def test_child_failure_is_degraded_not_approved() -> None:
    async def run_child(task):
        return ChildResult(
            child_run_id=task.child_run_id,
            profile_id=task.profile_id,
            kind=task.kind,
            status=ChildStatus.FAILED,
            content="",
            usage=TokenUsage(),
            iterations=0,
            tool_calls=(),
            reason_code="provider_error",
        )

    outcome = await HybridOrchestrationService(enabled=True).prepare(
        query="Investigate and compare several independent sources for this architecture.",
        requested_mode=ExecutionMode.TEAM,
        parent_run_id="parent-run",
        messages=[Message(Role.USER, "request")],
        events=RecordingEventSink(),
        child_runner=run_child,
    )

    assert outcome.degraded is True
    assert all(child.status is ChildStatus.FAILED for child in outcome.children)
    delegated = next(
        message
        for message in outcome.messages
        if message.role is Role.USER and "DELEGATED_FINDINGS_UNTRUSTED" in message.content
    )
    assert "approved" not in delegated.content.lower()


@pytest.mark.asyncio
async def test_team_service_enforces_one_aggregate_deadline() -> None:
    async def slow_child(task):
        del task
        await asyncio.sleep(2)
        raise AssertionError("child should have been cancelled by the aggregate deadline")

    started = time.monotonic()
    outcome = await HybridOrchestrationService(
        enabled=True,
        total_timeout_seconds=1.0,
    ).prepare(
        query="Compare architecture, security, and evidence across the complete system.",
        requested_mode=ExecutionMode.TEAM,
        parent_run_id="parent-run",
        messages=[Message(Role.USER, "original request")],
        events=RecordingEventSink(),
        child_runner=slow_child,
    )

    assert time.monotonic() - started < 1.5
    assert outcome.degraded is True
    assert all(child.status is ChildStatus.TIMED_OUT for child in outcome.children)
