"""Runtime enforcement for provider capabilities and response contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.runtime import (
    AgentEventKind,
    AgentRuntime,
    Message,
    ModelResponse,
    RecordingEventSink,
    Role,
    StopReason,
    TokenUsage,
    ToolCall,
)
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.structured_output import ResponseContract


class NoTools:
    def definitions(self):
        return ()

    async def execute(self, call):
        raise AssertionError(f"unexpected tool call: {call}")


class Provider:
    def __init__(self, responses, capabilities=None):
        self.responses = list(responses)
        self.capabilities = capabilities or ProviderCapabilities()
        self.calls = []

    async def complete(
        self, messages, tools=(), *, max_tokens=4096, response_contract=None, response_format=None
    ):
        self.calls.append((messages, tools, max_tokens, response_contract, response_format))
        return self.responses.pop(0)


def contract(validator=lambda value: value):
    return ResponseContract("answer", "1", {"type": "object"}, validator)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("messages", "response_contract", "required", "missing"),
    [
        ([Message(Role.USER, "look", images=("safe-ref",))], None, None, ("images",)),
        ([Message(Role.USER, "answer")], contract(), None, ("json_mode",)),
        (
            [Message(Role.USER, "use tools")],
            None,
            ProviderCapabilities(native_tools=True),
            ("native_tools",),
        ),
    ],
)
async def test_missing_capability_stops_before_provider_call(
    messages, response_contract, required, missing
):
    provider = Provider([ModelResponse("must not run")])
    sink = RecordingEventSink()

    result = await AgentRuntime(provider, NoTools(), events=sink).run(
        messages, response_contract=response_contract, required_capabilities=required
    )

    assert provider.calls == []
    assert result.stop_reason is StopReason.PROVIDER_CAPABILITY_UNSUPPORTED
    assert result.error == f"provider_capability_unsupported:{','.join(missing)}"
    rejection = next(
        e for e in sink.events if e.kind is AgentEventKind.PROVIDER_CAPABILITY_REJECTED
    )
    assert rejection.data == {
        "code": "provider_capability_unsupported",
        "missing_capabilities": missing,
    }


@dataclass(frozen=True)
class Answer:
    value: int


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terminal_structured_content_is_locally_validated_and_returned():
    provider_value = {"value": 999}
    provider = Provider(
        [ModelResponse('{"value": 7}', structured_output=provider_value)],
        ProviderCapabilities(json_mode=True),
    )
    response_contract = contract(lambda value: Answer(value=int(value["value"])))

    result = await AgentRuntime(provider, NoTools()).run(
        [Message(Role.USER, "answer")], response_contract=response_contract
    )

    assert result.stop_reason is StopReason.COMPLETED
    assert result.structured_output == Answer(7)
    assert result.structured_output is not provider_value
    assert provider.calls[0][3] is response_contract


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "validator", "code"),
    [
        ("not json", lambda value: value, "malformed_json"),
        ('{"value":"wrong"}', lambda value: Answer(value=value["missing"]), "schema_mismatch"),
    ],
)
async def test_invalid_structured_output_is_rejected(content, validator, code):
    provider = Provider([ModelResponse(content)], ProviderCapabilities(json_mode=True))
    sink = RecordingEventSink()

    result = await AgentRuntime(provider, NoTools(), events=sink).run(
        [Message(Role.USER, "answer")], response_contract=contract(validator)
    )

    assert result.stop_reason is StopReason.STRUCTURED_OUTPUT_INVALID
    assert result.error == f"structured_output_invalid:{code}"
    assert result.structured_output is None
    rejection = next(e for e in sink.events if e.kind is AgentEventKind.STRUCTURED_OUTPUT_REJECTED)
    assert rejection.data == {"code": code}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cache_usage_and_provider_identity_are_preserved_in_runtime_events():
    sink = RecordingEventSink()
    provider = Provider(
        [
            ModelResponse(
                "first",
                tool_calls=(ToolCall("call", "noop"),),
                usage=TokenUsage(1, 2),
                provider_stop_reason="tool_use",
                actual_provider="safe-provider",
                actual_model="safe-model",
            ),
            ModelResponse(
                "done",
                usage=TokenUsage(3, 4, cache_read_input_tokens=0, cache_write_input_tokens=5),
                provider_stop_reason="end_turn",
            ),
        ],
        ProviderCapabilities(native_tools=True),
    )

    class Tools(NoTools):
        def definitions(self):
            return ()

        async def execute(self, call):
            return {"ok": True}

    result = await AgentRuntime(provider, Tools(), events=sink).run([Message(Role.USER, "go")])

    assert result.usage == TokenUsage(4, 6, cache_read_input_tokens=0, cache_write_input_tokens=5)
    response_event = next(e for e in sink.events if e.kind is AgentEventKind.MODEL_RESPONSE)
    assert response_event.usage.cache_read_input_tokens is None
    assert response_event.usage.cache_write_input_tokens is None
    assert response_event.data == {
        "provider_stop_reason": "tool_use",
        "actual_provider": "safe-provider",
        "actual_model": "safe-model",
    }


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_reason", "expected"),
    [
        ("max_tokens", StopReason.PROVIDER_LENGTH_LIMIT),
        ("length", StopReason.PROVIDER_LENGTH_LIMIT),
        ("max_output_tokens", StopReason.PROVIDER_LENGTH_LIMIT),
        ("refusal", StopReason.PROVIDER_REFUSAL),
        ("content_filter", StopReason.PROVIDER_CONTENT_FILTER),
        ("safety", StopReason.PROVIDER_CONTENT_FILTER),
        ("blocked", StopReason.PROVIDER_CONTENT_FILTER),
        ("future_reason", StopReason.PROVIDER_ERROR),
        ("tool_use", StopReason.PROVIDER_ERROR),
        ("stop", StopReason.COMPLETED),
        ("end_turn", StopReason.COMPLETED),
        ("stop_sequence", StopReason.COMPLETED),
        ("completed", StopReason.COMPLETED),
        (None, StopReason.COMPLETED),
    ],
)
async def test_terminal_provider_stop_reason_is_normalized(raw_reason, expected):
    provider = Provider([ModelResponse("answer", provider_stop_reason=raw_reason)])

    result = await AgentRuntime(provider, NoTools()).run([Message(Role.USER, "go")])

    assert result.stop_reason is expected
    if expected is not StopReason.COMPLETED:
        assert result.error == f"provider_stop_reason:{expected.value}"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_use_reason_with_calls_remains_allowed():
    provider = Provider(
        [
            ModelResponse(
                tool_calls=(ToolCall("call", "noop"),), provider_stop_reason="tool_calls"
            ),
            ModelResponse("done", provider_stop_reason="stop"),
        ]
    )

    class Tools(NoTools):
        async def execute(self, call):
            return {"ok": True}

    result = await AgentRuntime(provider, Tools()).run([Message(Role.USER, "go")])

    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.calls) == 2
