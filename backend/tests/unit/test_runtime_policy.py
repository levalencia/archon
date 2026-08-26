"""Runtime policy/authorization boundary tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.agents.mock_llm import MockLLM
from app.runtime import (
    AgentEventKind,
    AgentRuntime,
    AuthorizationOutcome,
    Message,
    ModelResponse,
    RecordingEventSink,
    Role,
    RuntimeBudget,
    StopReason,
    ToolCall,
    ToolDefinition,
)
from app.security.default_policy import default_policy_engine
from app.security.policy import (
    PolicyAction,
    PolicyDecision,
    PolicyRequest,
    RiskClass,
    canonical_arguments_hash,
)


class PolicyTools:
    def __init__(self, risks: frozenset[RiskClass] = frozenset({RiskClass.READ})) -> None:
        self.risks = risks
        self.executed: list[ToolCall] = []

    def definitions(self) -> Sequence[ToolDefinition]:
        return (ToolDefinition("reader"),)

    def policy_request(self, call: ToolCall) -> PolicyRequest:
        return PolicyRequest(call.name, (), self.risks)

    async def execute(self, call: ToolCall) -> Mapping[str, Any]:
        self.executed.append(call)
        return {"ok": True}


class FixedPolicy:
    def __init__(self, action: PolicyAction) -> None:
        self.action = action

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        return PolicyDecision(self.action, request.risk_classes, "rule-1", "sensitive detail")


def provider(call: ToolCall | None = None) -> MockLLM:
    responses = [
        ModelResponse(tool_calls=(call or ToolCall("native-1", "reader", {"token": "secret"}),))
    ]
    responses.append(ModelResponse("done"))
    return MockLLM(responses)


@pytest.mark.asyncio
async def test_allow_orders_policy_event_before_execution_and_preserves_native_id() -> None:
    tools = PolicyTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.COMPLETED
    assert [event.kind for event in sink.events][3:6] == [
        AgentEventKind.TOOL_CALL_REQUESTED,
        AgentEventKind.POLICY_DECIDED,
        AgentEventKind.TOOL_CALL_COMPLETED,
    ]
    policy_event = next(
        event for event in sink.events if event.kind is AgentEventKind.POLICY_DECIDED
    )
    assert policy_event.data["id"] == "native-1"
    assert policy_event.data["action"] == "allow"
    assert "arguments" not in policy_event.data
    assert "secret" not in repr(policy_event.data)
    assert tools.executed[0].id == "native-1"


@pytest.mark.asyncio
async def test_policy_deny_is_terminal_and_never_executes() -> None:
    tools = PolicyTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), tools, policy_engine=FixedPolicy(PolicyAction.DENY), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert [event.kind for event in sink.events][-3:] == [
        AgentEventKind.POLICY_DECIDED,
        AgentEventKind.TOOL_DENIED,
        AgentEventKind.RUN_STOPPED,
    ]
    assert sink.events[-2].data["reason_code"] == "policy_denied"
    assert "secret" not in repr(sink.events[-2].data)


@pytest.mark.asyncio
async def test_policy_mode_requires_policy_aware_executor() -> None:
    class LegacyTools:
        def definitions(self) -> tuple[ToolDefinition, ...]:
            return (ToolDefinition("reader"),)

        async def execute(self, call: ToolCall) -> Mapping[str, Any]:
            raise AssertionError("must not execute")

    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), LegacyTools(), policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert (
        next(e for e in sink.events if e.kind is AgentEventKind.POLICY_DECIDED).data["reason_code"]
        == "policy_metadata_unavailable"
    )


@pytest.mark.asyncio
async def test_metadata_error_fails_closed_without_leaking_exception() -> None:
    class BrokenTools(PolicyTools):
        def policy_request(self, call: ToolCall) -> PolicyRequest:
            raise RuntimeError(f"resolver exposed {call.arguments['token']}")

    tools = BrokenTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert "secret" not in repr([event.data for event in sink.events])


@pytest.mark.asyncio
async def test_policy_engine_exception_fails_closed_and_is_sanitized() -> None:
    class BrokenPolicy:
        def evaluate(self, request: PolicyRequest) -> PolicyDecision:
            raise RuntimeError("classified policy backend detail")

    tools = PolicyTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(provider(), tools, policy_engine=BrokenPolicy(), events=sink).run(
        [Message(Role.USER, "read")]
    )

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    decision = next(e for e in sink.events if e.kind is AgentEventKind.POLICY_DECIDED)
    assert decision.data["reason_code"] == "policy_engine_unavailable"
    assert "classified" not in repr(decision.data)


@pytest.mark.asyncio
async def test_ask_without_authorizer_fails_closed() -> None:
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), tools, policy_engine=FixedPolicy(PolicyAction.ASK), events=sink
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []
    assert AgentEventKind.APPROVAL_REQUIRED not in [e.kind for e in sink.events]
    assert sink.events[-2].data["reason_code"] == "approval_unavailable"


class Authorizer:
    def __init__(self, outcome: AuthorizationOutcome | Exception | None = None) -> None:
        self.outcome = outcome
        self.requests = []

    async def authorize(self, request):
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        if self.outcome is None:
            return AuthorizationOutcome(
                True,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved",
            )
        return self.outcome


@pytest.mark.asyncio
async def test_ask_approved_binding_executes_with_explicit_events() -> None:
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = RecordingEventSink()
    authorizer = Authorizer()
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=authorizer,
        events=sink,
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(tools.executed) == 1
    assert [event.kind for event in sink.events][3:8] == [
        AgentEventKind.TOOL_CALL_REQUESTED,
        AgentEventKind.POLICY_DECIDED,
        AgentEventKind.APPROVAL_REQUIRED,
        AgentEventKind.APPROVAL_DECIDED,
        AgentEventKind.TOOL_CALL_COMPLETED,
    ]
    assert authorizer.requests[0].arguments_hash == canonical_arguments_hash({"token": "secret"})
    assert "secret" not in repr(sink.events[5].data)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tool_call_id", "tool_name", "arguments_hash"])
async def test_mismatched_approval_binding_never_executes(field: str) -> None:
    values = {
        "tool_call_id": "native-1",
        "tool_name": "reader",
        "arguments_hash": canonical_arguments_hash({"token": "secret"}),
    }
    values[field] = "b" * 64 if field == "arguments_hash" else "mismatch"
    outcome = AuthorizationOutcome(True, **values, reason_code="user_approved")
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=Authorizer(outcome),
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []


@pytest.mark.asyncio
async def test_authorizer_denial_is_policy_denied_and_never_executes() -> None:
    call = ToolCall("native-1", "reader", {"token": "secret"})
    outcome = AuthorizationOutcome(
        False, call.id, call.name, canonical_arguments_hash(call.arguments), "user_denied"
    )
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(call),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=Authorizer(outcome),
        events=sink,
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert (
        next(e for e in sink.events if e.kind is AgentEventKind.APPROVAL_DECIDED).data["approved"]
        is False
    )


@pytest.mark.asyncio
async def test_authorizer_exception_is_unavailable() -> None:
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=Authorizer(RuntimeError("secret backend error")),
    ).run([Message(Role.USER, "write")])
    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []


@pytest.mark.asyncio
async def test_authorizer_timeout_is_bounded_and_explicit() -> None:
    class SlowAuthorizer:
        async def authorize(self, request):
            await asyncio.sleep(1)
            raise AssertionError("unreachable")

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=SlowAuthorizer(),
        approval_timeout_seconds=0.001,
        budget=RuntimeBudget(max_seconds=1),
    ).run([Message(Role.USER, "write")])
    assert result.stop_reason is StopReason.APPROVAL_TIMEOUT
    assert tools.executed == []


def test_default_policy_is_explicit_and_fail_closed() -> None:
    engine = default_policy_engine()
    assert (
        engine.evaluate(PolicyRequest("read_file", (), frozenset({RiskClass.READ}))).action
        is PolicyAction.ALLOW
    )
    assert (
        engine.evaluate(PolicyRequest("web_search", (), frozenset({RiskClass.NETWORK}))).action
        is PolicyAction.ALLOW
    )
    for risks in (
        frozenset({RiskClass.WRITE}),
        frozenset({RiskClass.EXECUTE}),
        frozenset({RiskClass.EXTERNAL_SIDE_EFFECT}),
        frozenset({RiskClass.READ, RiskClass.WRITE}),
    ):
        assert engine.evaluate(PolicyRequest("tool", (), risks)).action is PolicyAction.ASK
    assert (
        engine.evaluate(PolicyRequest("other_network", (), frozenset({RiskClass.NETWORK}))).action
        is PolicyAction.ASK
    )


def test_authorization_models_validate_reason_code() -> None:
    with pytest.raises(ValueError, match="reason_code"):
        AuthorizationOutcome(True, "id", "tool", "a" * 64, "raw secret!")
