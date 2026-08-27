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
from app.runtime.factory import RunContext
from app.security.default_policy import default_policy_engine
from app.security.live_approvals import ApprovalBroker
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
async def test_provider_calls_are_snapshotted_before_model_events_can_mutate_them() -> None:
    original_arguments = {"operation": {"mode": "safe", "items": ["public"]}}
    call = ToolCall("native-before-events", "reader", original_arguments)

    class MutatingModelEventSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.MODEL_RESPONSE:
                object.__setattr__(call, "id", "response-attacker-id")
                object.__setattr__(call, "name", "response_attacker")
                original_arguments["operation"]["mode"] = "response-dangerous"
                original_arguments["operation"]["items"].append("response-secret")
            elif event.kind is AgentEventKind.MODEL_PROGRESS:
                object.__setattr__(call, "id", "progress-attacker-id")
                object.__setattr__(call, "name", "progress_attacker")
                original_arguments["operation"]["mode"] = "progress-dangerous"
                original_arguments["operation"]["items"].append("progress-secret")
            await asyncio.sleep(0)

    tools = PolicyTools()
    model = MockLLM([ModelResponse("working", tool_calls=(call,)), ModelResponse("done")])
    result = await AgentRuntime(
        model,
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=MutatingModelEventSink(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(tools.executed) == 1
    executed = tools.executed[0]
    assert (executed.id, executed.name) == ("native-before-events", "reader")
    assert executed.arguments["operation"] == {"mode": "safe", "items": ["public"]}


@pytest.mark.asyncio
async def test_provider_multi_call_snapshots_have_independent_nested_arguments() -> None:
    shared_operation = {"mode": "safe"}
    calls = (
        ToolCall("native-first", "reader", {"operation": shared_operation, "sequence": 1}),
        ToolCall("native-second", "reader", {"operation": shared_operation, "sequence": 2}),
    )

    class MutatingTools(PolicyTools):
        async def execute(self, call: ToolCall) -> Mapping[str, Any]:
            self.executed.append(call)
            if call.id == "native-first":
                call.arguments["operation"]["mode"] = "mutated-by-first"
            return {"ok": True}

    tools = MutatingTools()
    model = MockLLM([ModelResponse(tool_calls=calls), ModelResponse("done")])
    result = await AgentRuntime(model, tools, policy_engine=FixedPolicy(PolicyAction.ALLOW)).run(
        [Message(Role.USER, "run")]
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert len(tools.executed) == 2
    assert tools.executed[1].arguments["operation"] == {"mode": "safe"}


@pytest.mark.asyncio
async def test_provider_retained_history_cannot_observe_append_or_mutate_execution() -> None:
    original = {"operation": {"mode": "safe", "items": ["public"]}}
    provider_call = ToolCall("native-retained-history", "reader", original)

    class RetainingProvider:
        def __init__(self) -> None:
            self.inputs: list[Sequence[Message]] = []
            self.responses = [
                ModelResponse(tool_calls=(provider_call,)),
                ModelResponse("done"),
            ]

        async def complete(self, messages, tools=(), *, max_tokens=4096, response_contract=None):
            self.inputs.append(messages)
            return self.responses.pop(0)

    model = RetainingProvider()

    class MutatingSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.TOOL_CALL_REQUESTED:
                # The provider's first input must remain its original immutable one-message view;
                # it must never become the runtime's subsequently appended assistant history.
                assert isinstance(model.inputs[0], tuple)
                assert len(model.inputs[0]) == 1
                object.__setattr__(provider_call, "id", "attacker-id")
                object.__setattr__(provider_call, "name", "attacker_tool")
                original["operation"]["mode"] = "dangerous"
                original["operation"]["items"].append("secret")

    tools = PolicyTools()
    result = await AgentRuntime(
        model,
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=MutatingSink(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(tools.executed) == 1
    executed = tools.executed[0]
    assert (executed.id, executed.name) == ("native-retained-history", "reader")
    assert executed.arguments["operation"] == {"mode": "safe", "items": ["public"]}


@pytest.mark.asyncio
async def test_subsequent_provider_history_mutation_isolated_across_multiple_calls() -> None:
    first = ToolCall("native-first-history", "reader", {"nested": {"value": "first"}})
    second = ToolCall("native-second-history", "reader", {"nested": {"value": "second"}})

    class AdversarialProvider:
        def __init__(self) -> None:
            self.inputs: list[Sequence[Message]] = []
            self.iteration = 0

        async def complete(self, messages, tools=(), *, max_tokens=4096, response_contract=None):
            self.inputs.append(messages)
            self.iteration += 1
            if self.iteration == 1:
                return ModelResponse(tool_calls=(first,))
            if self.iteration == 2:
                retained_first = messages[1].tool_calls[0]
                object.__setattr__(retained_first, "id", "mutated-history-id")
                retained_first.arguments["nested"]["value"] = "mutated-history"
                return ModelResponse(tool_calls=(second,))
            # Every provider invocation gets a fresh detached view. Mutation of iteration two's
            # retained view must not corrupt the runtime's authoritative history.
            assert messages[1].tool_calls[0].id == "native-first-history"
            assert messages[1].tool_calls[0].arguments["nested"] == {"value": "first"}
            assert messages[3].tool_calls[0].id == "native-second-history"
            assert messages[3].tool_calls[0].arguments["nested"] == {"value": "second"}
            return ModelResponse("done")

    class MutatingModelEventSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.MODEL_RESPONSE and event.iteration == 2:
                retained_first = model.inputs[-1][1].tool_calls[0]
                object.__setattr__(retained_first, "name", "event_mutated_history")
                retained_first.arguments["nested"]["value"] = "event-mutated-history"

    tools = PolicyTools()
    model = AdversarialProvider()
    result = await AgentRuntime(
        model,
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=MutatingModelEventSink(),
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.COMPLETED
    assert [(call.id, call.arguments["nested"]["value"]) for call in tools.executed] == [
        ("native-first-history", "first"),
        ("native-second-history", "second"),
    ]
    assert model.inputs[0] is not model.inputs[1]
    assert model.inputs[1] is not model.inputs[2]


@pytest.mark.asyncio
async def test_invalid_later_provider_call_fails_closed_before_any_call_executes() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    calls = (
        ToolCall("native-valid", "reader", {"mode": "safe"}),
        ToolCall("native-cyclic", "reader", cyclic),
    )
    tools = PolicyTools()
    sink = RecordingEventSink()

    result = await AgentRuntime(
        MockLLM([ModelResponse(tool_calls=calls)]),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=sink,
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    denied = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    assert denied.data["id"] == "native-cyclic"
    assert denied.data["name"] == "reader"
    assert denied.data["reason_code"] == "policy_metadata_unavailable"


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
@pytest.mark.parametrize("mutation", ["id", "name", "arguments"])
@pytest.mark.parametrize("raises", [False, True])
async def test_metadata_mutation_uses_original_binding_and_fails_closed(
    mutation: str, raises: bool
) -> None:
    secret = "INITIAL_METADATA_SECRET_4f92"
    original_arguments = {"nested": {"token": secret, "mode": "safe"}}
    expected_hash = canonical_arguments_hash(original_arguments)

    class MutatingMetadataTools(PolicyTools):
        def policy_request(self, call: ToolCall) -> PolicyRequest:
            if mutation == "id":
                object.__setattr__(call, "id", "attacker-id")
            elif mutation == "name":
                object.__setattr__(call, "name", "attacker-tool")
            else:
                call.arguments["nested"]["mode"] = "dangerous"
            if raises:
                raise RuntimeError(f"metadata exposed {secret}")
            return PolicyRequest(call.name, (), self.risks)

    tools = MutatingMetadataTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(ToolCall("native-original", "reader", original_arguments)),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=sink,
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    policy_event = next(
        event for event in sink.events if event.kind is AgentEventKind.POLICY_DECIDED
    )
    denied_event = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    for event in (policy_event, denied_event):
        assert event.data["id"] == "native-original"
        assert event.data["name"] == "reader"
        assert event.data["reason_code"] == "binding_mismatch"
        assert event.data["arguments_hash"] == expected_hash
    serialized_events = json.dumps([event.data for event in sink.events], default=str)
    assert secret not in serialized_events
    assert "dangerous" not in serialized_events


@pytest.mark.asyncio
async def test_metadata_exception_without_mutation_remains_unavailable() -> None:
    class BrokenTools(PolicyTools):
        def policy_request(self, call: ToolCall) -> PolicyRequest:
            raise RuntimeError("metadata unavailable")

    tools = BrokenTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        provider(), tools, policy_engine=FixedPolicy(PolicyAction.ALLOW), events=sink
    ).run([Message(Role.USER, "read")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    failures = [
        event
        for event in sink.events
        if event.kind in {AgentEventKind.POLICY_DECIDED, AgentEventKind.TOOL_DENIED}
    ]
    assert failures
    assert all(event.data["id"] == "native-1" for event in failures)
    assert all(event.data["name"] == "reader" for event in failures)
    assert all(event.data["reason_code"] == "policy_metadata_unavailable" for event in failures)


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
    request = authorizer.requests[0]
    assert request.tool_call_id == "native-1"
    assert request.tool_name == "reader"
    assert request.arguments_hash == canonical_arguments_hash({"token": "secret"})
    assert request.risk_classes == frozenset({RiskClass.WRITE})
    assert request.matched_rule_id == "rule-1"
    assert "secret" not in repr(sink.events[5].data)


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [True, False], ids=["approved", "denied"])
async def test_approval_is_reserved_before_required_event_is_published(approved: bool) -> None:
    broker = ApprovalBroker()
    run_context = RunContext("alice", "conversation", "run", "correlation")

    class ImmediateDecisionSink(RecordingEventSink):
        accepted = False

        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.APPROVAL_REQUIRED:
                self.accepted = await broker.decide_for_owner(
                    user_id="alice",
                    run_id="run",
                    tool_call_id=event.data["id"],
                    approved=approved,
                )

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = ImmediateDecisionSink()
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=broker.authorizer(run_context),
        events=sink,
    ).run([Message(Role.USER, "write")])

    assert sink.accepted is True
    assert result.stop_reason is (StopReason.COMPLETED if approved else StopReason.POLICY_DENIED)
    assert len(tools.executed) == int(approved)
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_approval_publication_failure_cleans_prepared_reservation() -> None:
    broker = ApprovalBroker()
    run_context = RunContext("alice", "conversation", "run", "correlation")

    class FailingApprovalSink(RecordingEventSink):
        async def emit(self, event) -> None:
            if event.kind is AgentEventKind.APPROVAL_REQUIRED:
                raise RuntimeError("client disconnected")
            await super().emit(event)

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=broker.authorizer(run_context),
        events=FailingApprovalSink(),
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.ERROR
    assert tools.executed == []
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_approval_timeout_cleans_prepared_reservation() -> None:
    broker = ApprovalBroker()
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=broker.authorizer(RunContext("alice", "conversation", "run", "correlation")),
        approval_timeout_seconds=0.001,
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.APPROVAL_TIMEOUT
    assert tools.executed == []
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_runtime_cancellation_cleans_prepared_reservation() -> None:
    broker = ApprovalBroker()
    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    run = asyncio.create_task(
        AgentRuntime(
            provider(),
            tools,
            policy_engine=FixedPolicy(PolicyAction.ASK),
            authorizer=broker.authorizer(RunContext("alice", "conversation", "run", "correlation")),
        ).run([Message(Role.USER, "write")])
    )
    for _ in range(100):
        if await broker.pending_count() == 1:
            break
        await asyncio.sleep(0)
    assert await broker.pending_count() == 1

    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert tools.executed == []
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "spoofed_value"),
    [
        pytest.param("tool_call_id", "attacker-id", id="tool-call-id"),
        pytest.param("tool_name", "attacker_tool", id="tool-name"),
        pytest.param("arguments_hash", "b" * 64, id="arguments-hash"),
        pytest.param("risk_classes", frozenset({RiskClass.READ}), id="risk-classes"),
        pytest.param("matched_rule_id", "attacker-rule", id="matched-rule-id"),
    ],
)
async def test_ask_rejects_mutated_authorization_request_with_consistent_spoofed_outcome(
    field: str, spoofed_value: object
) -> None:
    class RequestMutatingAuthorizer:
        async def authorize(self, request: AuthorizationRequest) -> AuthorizationOutcome:
            object.__setattr__(request, field, spoofed_value)
            return AuthorizationOutcome(
                True,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved",
            )

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = RecordingEventSink()
    expected_hash = canonical_arguments_hash({"token": "secret"})
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=RequestMutatingAuthorizer(),
        events=sink,
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert tools.executed == []
    approval = next(event for event in sink.events if event.kind is AgentEventKind.APPROVAL_DECIDED)
    denied = next(event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED)
    for event in (approval, denied):
        assert event.data["id"] == "native-1"
        assert event.data["name"] == "reader"
        assert event.data["arguments_hash"] == expected_hash
        assert event.data["reason_code"] == "approval_binding_mismatch"


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
@pytest.mark.parametrize(
    ("approved", "reason_code", "mutated_field", "mutated_value"),
    [
        pytest.param(False, "user_denied", "approved", True, id="denied-to-approved"),
        pytest.param(True, "user_approved", "approved", False, id="approved-to-denied"),
        pytest.param(
            False,
            "user_denied",
            "reason_code",
            "attacker_reason",
            id="denial-reason",
        ),
    ],
)
async def test_authorization_outcome_is_bound_before_decision_event_mutation(
    approved: bool, reason_code: str, mutated_field: str, mutated_value: object
) -> None:
    call = ToolCall("native-1", "reader", {"token": "***"})
    outcome = AuthorizationOutcome(
        approved, call.id, call.name, canonical_arguments_hash(call.arguments), reason_code
    )

    class MutatingDecisionSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.APPROVAL_DECIDED:
                object.__setattr__(outcome, mutated_field, mutated_value)
                await asyncio.sleep(0)

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    sink = MutatingDecisionSink()
    result = await AgentRuntime(
        provider(call),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=Authorizer(outcome),
        events=sink,
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is (StopReason.COMPLETED if approved else StopReason.POLICY_DENIED)
    assert len(tools.executed) == int(approved)
    approval = next(event for event in sink.events if event.kind is AgentEventKind.APPROVAL_DECIDED)
    assert approval.data["approved"] is approved
    assert approval.data["reason_code"] == reason_code
    denied = [event for event in sink.events if event.kind is AgentEventKind.TOOL_DENIED]
    assert len(denied) == int(not approved)
    if denied:
        assert denied[0].data["reason_code"] == reason_code


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
@pytest.mark.parametrize("raises", [False, True], ids=["success", "error"])
async def test_policy_executor_mutation_cannot_spoof_results_events_or_history(
    raises: bool,
) -> None:
    argument_secret = "ORIGINAL_ARGUMENT_SECRET_15f6"
    output_secret = "EXECUTOR_OUTPUT_SECRET_27a8"
    original_arguments = {"nested": {"token": argument_secret, "items": ["public"]}}

    class MutatingTools(PolicyTools):
        async def execute(self, call: ToolCall) -> Mapping[str, Any]:
            self.executed.append(call)
            object.__setattr__(call, "id", "executor-spoofed-id")
            object.__setattr__(call, "name", "executor_spoofed_tool")
            call.arguments["nested"]["token"] = "executor-mutated-secret"
            call.arguments["nested"]["items"].append("executor-added-secret")
            if raises:
                raise RuntimeError(output_secret)
            return {"payload": output_secret * 80}

    class CapturingProvider:
        def __init__(self) -> None:
            self.inputs: list[Sequence[Message]] = []
            self.responses = [
                ModelResponse(
                    tool_calls=(ToolCall("native-before-executor", "reader", original_arguments),)
                ),
                ModelResponse("done"),
            ]

        async def complete(self, messages, tools=(), *, max_tokens=4096, response_contract=None):
            self.inputs.append(messages)
            return self.responses.pop(0)

    tools = MutatingTools()
    model = CapturingProvider()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        model,
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=sink,
    ).run([Message(Role.USER, "run")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(result.tool_calls) == 1
    record = result.tool_calls[0]
    assert record["tool"] == "reader"
    assert record["parameters"] == {"nested": {"token": argument_secret, "items": ["public"]}}
    assert record["status"] == ("error" if raises else "success")

    completed = next(e for e in sink.events if e.kind is AgentEventKind.TOOL_CALL_COMPLETED)
    assert completed.data["id"] == "native-before-executor"
    assert completed.data["name"] == "reader"
    assert completed.data["arguments_hash"] == canonical_arguments_hash(original_arguments)
    assert completed.data["status"] == ("error" if raises else "success")
    progress = [e for e in sink.events if e.kind is AgentEventKind.TOOL_PROGRESS]
    if raises:
        assert progress == []
    else:
        assert progress
        assert all(
            event.data["id"] == "native-before-executor"
            and event.data["name"] == "reader"
            and event.data["arguments_hash"] == canonical_arguments_hash(original_arguments)
            for event in progress
        )

    assert len(model.inputs) == 2
    assert model.inputs[1][-1].role is Role.TOOL
    assert model.inputs[1][-1].tool_call_id == "native-before-executor"
    serialized_events = json.dumps([event.data for event in sink.events], default=str)
    assert argument_secret not in serialized_events
    assert output_secret not in serialized_events
    assert "executor-mutated-secret" not in serialized_events
    assert "executor-added-secret" not in serialized_events
    assert "executor-spoofed" not in serialized_events


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


def batch_provider(*calls: ToolCall) -> MockLLM:
    return MockLLM([ModelResponse(tool_calls=calls), ModelResponse("done")])


class ArgumentPolicyTools(PolicyTools):
    def policy_request(self, call: ToolCall) -> PolicyRequest:
        risk = RiskClass(call.arguments.get("risk", RiskClass.READ.value))
        return PolicyRequest(call.name, (), frozenset({risk}))


class RiskPolicy:
    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        action = (
            PolicyAction.DENY if RiskClass.EXECUTE in request.risk_classes else PolicyAction.ALLOW
        )
        return PolicyDecision(action, request.risk_classes, f"rule-{action.value}", "batch")


@pytest.mark.asyncio
async def test_policy_decision_is_bound_before_policy_event_mutation() -> None:
    decision = PolicyDecision(
        PolicyAction.ASK, frozenset({RiskClass.WRITE}), "original-rule", "original-reason"
    )

    class RetainingPolicy:
        def evaluate(self, request: PolicyRequest) -> PolicyDecision:
            return decision

    class MutatingSink(RecordingEventSink):
        async def emit(self, event) -> None:
            await super().emit(event)
            if event.kind is AgentEventKind.POLICY_DECIDED:
                object.__setattr__(decision, "action", PolicyAction.ALLOW)
                object.__setattr__(decision, "risk_classes", frozenset({RiskClass.READ}))
                object.__setattr__(decision, "matched_rule_id", "attacker-rule")
                object.__setattr__(decision, "reason", "attacker-reason")

    class DenyingAuthorizer(Authorizer):
        async def authorize(self, request):
            self.requests.append(request)
            return AuthorizationOutcome(
                False,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_denied",
            )

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    authorizer = DenyingAuthorizer()
    result = await AgentRuntime(
        provider(),
        tools,
        policy_engine=RetainingPolicy(),
        authorizer=authorizer,
        events=MutatingSink(),
    ).run([Message(Role.USER, "write")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []
    assert authorizer.requests[0].risk_classes == frozenset({RiskClass.WRITE})
    assert authorizer.requests[0].matched_rule_id == "original-rule"


@pytest.mark.asyncio
async def test_policy_batch_allowed_then_denied_executes_none() -> None:
    tools = ArgumentPolicyTools()
    result = await AgentRuntime(
        batch_provider(
            ToolCall("first", "reader", {"risk": "read"}),
            ToolCall("second", "reader", {"risk": "execute"}),
        ),
        tools,
        policy_engine=RiskPolicy(),
    ).run([Message(Role.USER, "batch")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []


@pytest.mark.asyncio
async def test_policy_batch_later_metadata_failure_executes_none() -> None:
    class LaterBrokenTools(PolicyTools):
        def policy_request(self, call: ToolCall) -> PolicyRequest:
            if call.id == "second":
                raise RuntimeError("unavailable")
            return super().policy_request(call)

    tools = LaterBrokenTools()
    result = await AgentRuntime(
        batch_provider(
            ToolCall("first", "reader", {"sequence": 1}),
            ToolCall("second", "reader", {"sequence": 2}),
        ),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
    ).run([Message(Role.USER, "batch")])

    assert result.stop_reason is StopReason.POLICY_DENIED
    assert tools.executed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["denied", "timeout"])
async def test_policy_batch_later_approval_failure_executes_none(failure: str) -> None:
    class SequencedAuthorizer:
        def __init__(self) -> None:
            self.count = 0

        async def authorize(self, request):
            self.count += 1
            if self.count == 2 and failure == "timeout":
                await asyncio.sleep(1)
            approved = self.count == 1
            return AuthorizationOutcome(
                approved,
                request.tool_call_id,
                request.tool_name,
                request.arguments_hash,
                "user_approved" if approved else "user_denied",
            )

    tools = PolicyTools(frozenset({RiskClass.WRITE}))
    result = await AgentRuntime(
        batch_provider(
            ToolCall("first", "reader", {"sequence": 1}),
            ToolCall("second", "reader", {"sequence": 2}),
        ),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ASK),
        authorizer=SequencedAuthorizer(),
        approval_timeout_seconds=0.005,
    ).run([Message(Role.USER, "batch")])

    assert result.stop_reason is (
        StopReason.APPROVAL_TIMEOUT if failure == "timeout" else StopReason.POLICY_DENIED
    )
    assert tools.executed == []


@pytest.mark.asyncio
async def test_policy_batch_authorizes_all_before_executing_in_order() -> None:
    tools = PolicyTools()
    sink = RecordingEventSink()
    result = await AgentRuntime(
        batch_provider(
            ToolCall("first", "reader", {"sequence": 1}),
            ToolCall("second", "reader", {"sequence": 2}),
        ),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        events=sink,
    ).run([Message(Role.USER, "batch")])

    assert result.stop_reason is StopReason.COMPLETED
    assert [call.id for call in tools.executed] == ["first", "second"]
    kinds = [event.kind for event in sink.events]
    first_completion = kinds.index(AgentEventKind.TOOL_CALL_COMPLETED)
    assert kinds[:first_completion].count(AgentEventKind.TOOL_CALL_REQUESTED) == 2
    assert kinds[:first_completion].count(AgentEventKind.POLICY_DECIDED) == 2


@pytest.mark.asyncio
async def test_policy_batch_budget_exhaustion_prevents_first_execution() -> None:
    tools = PolicyTools()
    result = await AgentRuntime(
        batch_provider(
            ToolCall("first", "reader", {"sequence": 1}),
            ToolCall("second", "reader", {"sequence": 2}),
        ),
        tools,
        policy_engine=FixedPolicy(PolicyAction.ALLOW),
        budget=RuntimeBudget(max_tool_calls=1),
    ).run([Message(Role.USER, "batch")])

    assert result.stop_reason is StopReason.TOOL_BUDGET_EXHAUSTED
    assert tools.executed == []
