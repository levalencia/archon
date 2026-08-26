"""Runtime policy/authorization boundary tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.agents.mock_llm import MockLLM
from app.runtime import (
    AgentEventKind,
    AgentRuntime,
    AuthorizationOutcome,
    AuthorizationRequest,
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
@pytest.mark.parametrize("action", [PolicyAction.ALLOW, PolicyAction.ASK])
async def test_policy_execution_uses_detached_nested_argument_snapshot(
    action: PolicyAction,
) -> None:
    nested = {"operation": {"mode": "safe", "items": ["public"]}}
    call = ToolCall("native-snapshot", "reader", nested)

    class MutatingSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.TOOL_CALL_REQUESTED:
                nested["operation"]["mode"] = "dangerous"
                nested["operation"]["items"].append("secret")
                await asyncio.sleep(0)

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    authorizer = Authorizer() if action is PolicyAction.ASK else None
    result = await AgentRuntime(
        provider(call),
        tools,
        policy_engine=FixedPolicy(action),
        authorizer=authorizer,
        events=MutatingSink(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(tools.executed) == 1
    assert tools.executed[0].arguments["operation"] == {"mode": "safe", "items": ["public"]}
    expected_hash = canonical_arguments_hash({"operation": {"mode": "safe", "items": ["public"]}})
    if authorizer is not None:
        assert authorizer.requests[0].arguments_hash == expected_hash


@pytest.mark.asyncio
async def test_allow_revalidates_snapshot_mutated_via_retained_policy_reference() -> None:
    class RetainingTools(PolicyTools):
        retained_call: ToolCall | None = None

        def policy_request(self, call: ToolCall) -> PolicyRequest:
            self.retained_call = call
            return super().policy_request(call)

    tools = RetainingTools()

    class MutatingSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.POLICY_DECIDED:
                assert tools.retained_call is not None
                tools.retained_call.arguments["nested"]["mode"] = "dangerous"
                await asyncio.sleep(0)

    call = ToolCall("native-retained", "reader", {"nested": {"mode": "safe"}})
    result = await AgentRuntime(
        provider(call),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=MutatingSink(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []


@pytest.mark.asyncio
async def test_allow_rejects_native_id_mutated_by_policy_collaborator() -> None:
    class RetainingTools(PolicyTools):
        retained_call: ToolCall | None = None

        def policy_request(self, call: ToolCall) -> PolicyRequest:
            self.retained_call = call
            return super().policy_request(call)

    tools = RetainingTools()

    class MutatingPolicy(FixedPolicy):
        def evaluate(self, request: PolicyRequest) -> PolicyDecision:
            assert tools.retained_call is not None
            object.__setattr__(tools.retained_call, "id", "swapped-id")
            return super().evaluate(request)

    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(ToolCall("native-retained", "reader", {"nested": {"mode": "safe"}})),
        tools,
        policy_engine=MutatingPolicy(PolicyAction.ALLOW),
        events=sink,
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    denied = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    assert denied.data["id"] == "native-retained"
    assert denied.data["reason_code"] == "binding_mismatch"
    assert all(
        event.data.get("id") == "native-retained"
        for event in sink.events
        if event.kind in {AgentEventKind.POLICY_DECIDED, AgentEventKind.TOOL_DENIED}
    )


@pytest.mark.asyncio
async def test_ask_rejects_snapshot_mutated_during_authorization() -> None:
    class RetainingTools(PolicyTools):
        retained_call: ToolCall | None = None

        def policy_request(self, call: ToolCall) -> PolicyRequest:
            self.retained_call = call
            return super().policy_request(call)

    tools = RetainingTools(frozenset({RiskClass.WRITE}))

    class MutatingAuthorizer:
        async def authorize(self, request):
            assert tools.retained_call is not None
            tools.retained_call.arguments["nested"]["mode"] = "dangerous"
            await asyncio.sleep(0)
            return AuthorizationOutcome(
                True,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved",
            )

    call = ToolCall("native-retained", "reader", {"nested": {"mode": "safe"}})
    result = await AgentRuntime(
        provider(call),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=MutatingAuthorizer(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate_name", "mutate_arguments"),
    [(False, False), (True, False), (False, True), (True, True)],
)
async def test_ask_rejects_native_id_name_and_hash_mutation_during_authorizer_await(
    mutate_name: bool, mutate_arguments: bool
) -> None:
    class RetainingTools(PolicyTools):
        retained_call: ToolCall | None = None

        def policy_request(self, call: ToolCall) -> PolicyRequest:
            self.retained_call = call
            return super().policy_request(call)

    tools = RetainingTools(frozenset({RiskClass.WRITE}))

    class MutatingAuthorizer:
        async def authorize(self, request):
            await asyncio.sleep(0)
            assert tools.retained_call is not None
            object.__setattr__(tools.retained_call, "id", "swapped-id")
            if mutate_name:
                object.__setattr__(tools.retained_call, "name", "swapped-reader")
            if mutate_arguments:
                tools.retained_call.arguments["nested"]["mode"] = "dangerous"
            return AuthorizationOutcome(
                True,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved",
            )

    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(ToolCall("native-retained", "reader", {"nested": {"mode": "safe"}})),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=MutatingAuthorizer(),
        events=sink,
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []
    denied = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    assert denied.data["id"] == "native-retained"
    assert denied.data["name"] == "reader"
    assert denied.data["reason_code"] == "binding_mismatch"
    approval_events = [
        event for event in sink.events if event.kind is AgentEventKind.APPROVAL_DECIDED
    ]
    assert approval_events[-1].data["id"] == "native-retained"
    assert approval_events[-1].data["reason_code"] == "binding_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_value", [float("inf"), object()])
async def test_policy_rejects_non_json_arguments_before_execution(invalid_value: object) -> None:
    tools = PolicyTools()
    sink = RecordingEventSink()
    call = ToolCall("native-invalid", "reader", {"value": invalid_value})

    result = await AgentRuntime(
        provider(call), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert (
        next(e for e in sink.events if e.kind is AgentEventKind.POLICY_DECIDED).data["reason_code"]
        == "policy_metadata_unavailable"
    )


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
@pytest.mark.parametrize("native_name", ["Reader", "reader ", "re\u0301ader"])
async def test_policy_mode_rejects_noncanonical_native_tool_names(native_name: str) -> None:
    tools = PolicyTools()
    sink = RecordingEventSink()
    call = ToolCall("native-exact", native_name, {"token": "***"})
    result = await AgentRuntime(
        provider(call), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert sink.events[3].data["id"] == "native-exact"
    assert sink.events[3].data["name"] == native_name
    assert sink.events[4].data["reason_code"] == "policy_metadata_unavailable"


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


@pytest.mark.asyncio
async def test_authorizer_cannot_suppress_cancellation_and_approve_after_deadline() -> None:
    finished = asyncio.Event()

    class CancellationSuppressingAuthorizer:
        async def authorize(self, request):
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                await asyncio.sleep(0.03)
            finally:
                finished.set()
            return AuthorizationOutcome(
                True,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved",
            )

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=CancellationSuppressingAuthorizer(),
        approval_timeout_seconds=0.005,
        budget=RuntimeBudget(max_seconds=1),
    ).run([Message(Role.USER, "write")])
    elapsed = loop.time() - started

    assert result.stop_reason is StopReason.APPROVAL_TIMEOUT
    assert elapsed < 0.025
    assert tools.executed == []
    await asyncio.wait_for(finished.wait(), timeout=0.2)
    assert tools.executed == []


@pytest.mark.asyncio
async def test_policy_events_never_serialize_raw_arguments_or_output() -> None:
    argument_secret = "ARGUMENT_SECRET_7e8f"
    output_secret = "OUTPUT_SECRET_9a0b"

    class SecretTools(PolicyTools):
        async def execute(self, call: ToolCall) -> Mapping[str, Any]:
            self.executed.append(call)
            return {"payload": output_secret * 80}

    tools = SecretTools()
    sink = RecordingEventSink()
    call = ToolCall("native-secret", "reader", {"nested": {"token": argument_secret}})
    result = await AgentRuntime(
        provider(call), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.COMPLETED
    serialized_events = json.dumps(
        [{"kind": event.kind.value, "data": event.data} for event in sink.events],
        sort_keys=True,
        default=str,
    )
    assert argument_secret not in serialized_events
    assert output_secret not in serialized_events
    completed = next(e for e in sink.events if e.kind is AgentEventKind.TOOL_CALL_COMPLETED)
    assert set(completed.data) == {
        "id",
        "name",
        "arguments_hash",
        "output_hash",
        "output_size",
        "status",
    }
    progress = [e for e in sink.events if e.kind is AgentEventKind.TOOL_PROGRESS]
    assert progress
    assert all(
        "chunk" not in event.data and event.data["status"] == "success" for event in progress
    )


@pytest.mark.asyncio
async def test_policy_denial_event_never_serializes_argument_secret() -> None:
    secret = "DENIED_ARGUMENT_SECRET_c1d2"
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(ToolCall("native-denied", "reader", {"token": secret})),
        PolicyTools(),
        policy_engine=FixedPolicy(PolicyAction.DENY),
        events=sink,
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    serialized_events = json.dumps([event.data for event in sink.events], default=str)
    assert secret not in serialized_events
    denied = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    assert "arguments" not in denied.data
    assert "output" not in denied.data


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


@pytest.mark.parametrize("tool_name", ["READER", " reader", "reader ", "re\u0301ader"])
@pytest.mark.parametrize("model", [AuthorizationRequest, AuthorizationOutcome])
def test_authorization_models_reject_noncanonical_tool_names(tool_name: str, model: type) -> None:
    kwargs = {
        "tool_call_id": "native-1",
        "tool_name": tool_name,
        "arguments_hash": "a" * 64,
    }
    if model is AuthorizationOutcome:
        kwargs.update(approved=True, reason_code="user_approved")

    with pytest.raises(ValueError, match="tool_name must be canonical"):
        model(**kwargs)


def test_authorization_binding_preserves_and_compares_exact_values() -> None:
    request = AuthorizationRequest("native-1", "reader", "a" * 64)

    assert request.tool_name == "reader"
    assert AuthorizationOutcome(True, "native-1", "reader", "a" * 64, "user_approved").binds(
        request
    )
    assert not AuthorizationOutcome(True, "native-2", "reader", "a" * 64, "user_approved").binds(
        request
    )
    assert not AuthorizationOutcome(True, "native-1", "reader", "b" * 64, "user_approved").binds(
        request
    )
