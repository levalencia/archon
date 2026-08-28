"""Unit coverage for the bounded final-answer reflection boundary."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from decimal import Decimal

import pytest

from app.config import Settings
from app.reflection.models import ReflectionOutcomeCode, ReflectionPolicy
from app.reflection.service import BoundedReflectionService
from app.runtime.engine import AgentRuntime, RuntimeBudget
from app.runtime.events import AgentEventKind, RecordingEventSink
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall
from app.security.persistence_redactor import PersistenceRedactor
from app.services.run_ledger import safe_event_payload

HASH_KEY = b"k" * 32


class _NoTools:
    def definitions(self):
        return ()

    async def execute(self, call):  # pragma: no cover - reflection must never reach this port
        raise AssertionError(f"unexpected tool execution: {call}")


class _QueueProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(
        self,
        messages,
        tools=(),
        *,
        max_tokens=4096,
        response_contract=None,
        response_format=None,
    ):
        del response_format
        self.calls.append((tuple(messages), tuple(tools), max_tokens, response_contract))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _response(content: str, *, input_tokens: int = 10, output_tokens: int = 5):
    return ModelResponse(content, usage=TokenUsage(input_tokens, output_tokens))


def _policy(**overrides):
    values = {
        "enabled": True,
        "max_input_tokens": 8192,
        "max_output_tokens": 2048,
        "max_seconds": 1.0,
        "max_cost_usd": Decimal("1"),
    }
    values.update(overrides)
    return ReflectionPolicy(**values)


def _service(provider, policy=None, *, events=None):
    return BoundedReflectionService(
        provider,
        policy or _policy(),
        events=events,
        hash_key=HASH_KEY,
        hash_scope="alice\0project\0run-1",
    )


def test_reflection_is_opt_in_and_requires_private_fingerprints() -> None:
    provider = _QueueProvider([])
    BoundedReflectionService(provider, ReflectionPolicy())
    with pytest.raises(ValueError, match="fingerprint key"):
        BoundedReflectionService(provider, _policy(), hash_scope="scope")


def test_reflection_settings_use_documented_archon_prefix(monkeypatch) -> None:
    monkeypatch.setenv("ARCHON_REFLECTION_ENABLED", "true")
    monkeypatch.setenv("ARCHON_REFLECTION_MAX_REVISIONS", "0")
    monkeypatch.setenv("ARCHON_REFLECTION_TIMEOUT_SECONDS", "3.5")

    settings = Settings()

    assert settings.reflection_enabled is True
    assert settings.reflection_max_revisions == 0
    assert settings.reflection_timeout_seconds == 3.5


@pytest.mark.asyncio
async def test_disabled_runtime_makes_zero_extra_provider_calls() -> None:
    provider = _QueueProvider([_response("draft")])
    runtime = AgentRuntime(provider, _NoTools())

    result = await runtime.run([Message(Role.USER, "question")])

    assert result.content == "draft"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_keep_uses_one_critique_and_no_revision() -> None:
    provider = _QueueProvider(
        [_response('{"verdict":"keep","issue_codes":[],"evidence_refs":[],"confidence":0.9}')]
    )
    sink = RecordingEventSink()
    service = _service(provider, events=sink)

    result = await service.reflect([Message(Role.USER, "question")], "private draft")

    assert result.content == "private draft"
    assert result.outcome is ReflectionOutcomeCode.KEPT
    assert result.calls == 1
    assert result.revisions == 0
    assert len(provider.calls) == 1
    assert provider.calls[0][1] == ()
    assert provider.calls[0][3] is not None
    started = next(
        event for event in sink.events if event.kind is AgentEventKind.REFLECTION_STARTED
    )
    expected_hash = hmac.new(
        HASH_KEY,
        b"archon/reflection/v1\0alice\0project\0run-1\0draft\0private draft",
        hashlib.sha256,
    ).hexdigest()
    assert started.data["draft_hash"] == expected_hash
    assert started.data["draft_hash"] != hashlib.sha256(b"private draft").hexdigest()
    other_scope_hash = hmac.new(
        HASH_KEY,
        b"archon/reflection/v1\0bob\0project\0run-1\0draft\0private draft",
        hashlib.sha256,
    ).hexdigest()
    assert started.data["draft_hash"] != other_scope_hash


@pytest.mark.asyncio
async def test_revise_is_exactly_one_critique_and_one_tool_free_revision() -> None:
    provider = _QueueProvider(
        [
            _response(
                '{"verdict":"revise","issue_codes":["factual_error"],'
                '"evidence_refs":["draft:L1"],"confidence":1.0}'
            ),
            _response("corrected final answer"),
            _response("must never be consumed"),
        ]
    )
    result = await _service(provider).reflect(
        [Message(Role.USER, "question")], "wrong draft"
    )

    assert result.content == "corrected final answer"
    assert result.outcome is ReflectionOutcomeCode.REVISED
    assert result.calls == 2
    assert result.revisions == 1
    assert len(provider.calls) == 2
    assert all(call[1] == () for call in provider.calls)
    assert provider.calls[1][3] is None


@pytest.mark.asyncio
async def test_runtime_reflects_only_at_final_answer_boundary_and_accounts_usage() -> None:
    provider = _QueueProvider(
        [
            _response("wrong draft", input_tokens=7, output_tokens=2),
            _response(
                '{"verdict":"revise","issue_codes":["factual_error"],'
                '"evidence_refs":["draft:L1"],"confidence":0.8}',
                input_tokens=11,
                output_tokens=4,
            ),
            _response("fixed", input_tokens=13, output_tokens=3),
        ]
    )
    sink = RecordingEventSink()
    runtime = AgentRuntime(
        provider,
        _NoTools(),
        events=sink,
        reflection_policy=_policy(),
        reflection_hash_key=HASH_KEY,
        reflection_hash_scope="alice\0project\0run-1",
    )

    result = await runtime.run([Message(Role.USER, "question")])

    assert result.content == "fixed"
    assert result.usage == TokenUsage(31, 9)
    assert [event.kind for event in sink.events].count(AgentEventKind.TEXT_DELTA) == 1
    text_event = next(event for event in sink.events if event.kind is AgentEventKind.TEXT_DELTA)
    assert text_event.data["text"] == "fixed"


@pytest.mark.asyncio
async def test_runtime_global_token_budget_blocks_extra_reflection_call() -> None:
    provider = _QueueProvider(
        [
            _response("bounded draft", input_tokens=7, output_tokens=2),
            _response('{"verdict":"keep","issue_codes":[],"evidence_refs":[],"confidence":1}'),
        ]
    )
    runtime = AgentRuntime(
        provider,
        _NoTools(),
        budget=RuntimeBudget(max_tokens=10),
        reflection_policy=_policy(),
        reflection_hash_key=HASH_KEY,
        reflection_hash_scope="alice\0project\0run-1",
    )

    result = await runtime.run([Message(Role.USER, "question")])

    assert result.content == "bounded draft"
    assert result.usage == TokenUsage(7, 2)
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_invalid_structured_verdict_fails_safe_to_keep() -> None:
    provider = _QueueProvider([_response('{"verdict":"revise","reason":"secret reasoning"}')])

    result = await _service(provider).reflect([], "safe draft")

    assert result.content == "safe draft"
    assert result.outcome is ReflectionOutcomeCode.INVALID_VERDICT
    assert result.calls == 1
    assert result.revisions == 0


@pytest.mark.asyncio
async def test_token_bound_blocks_before_provider_call() -> None:
    provider = _QueueProvider([_response("unused")])
    service = _service(provider, _policy(max_input_tokens=1))

    result = await service.reflect([Message(Role.USER, "large request")], "draft")

    assert result.outcome is ReflectionOutcomeCode.TOKEN_LIMIT
    assert result.calls == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_cost_bound_blocks_before_provider_call() -> None:
    provider = _QueueProvider([_response("unused")])
    service = _service(
        provider,
        _policy(
            max_cost_usd=Decimal("0.000001"),
            input_cost_per_million_usd=Decimal("100"),
            output_cost_per_million_usd=Decimal("100"),
        ),
    )

    result = await service.reflect([], "draft")

    assert result.outcome is ReflectionOutcomeCode.COST_LIMIT
    assert result.calls == 0


@pytest.mark.asyncio
async def test_deadline_is_hard_and_fails_safe_to_keep() -> None:
    class _SlowProvider(_QueueProvider):
        async def complete(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            await asyncio.sleep(1)
            return _response("late")

    provider = _SlowProvider([])
    service = _service(provider, _policy(max_seconds=0.05))

    result = await service.reflect([], "draft")

    assert result.content == "draft"
    assert result.outcome is ReflectionOutcomeCode.TIME_LIMIT
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_tool_call_in_critique_is_blocked_without_execution_or_revision() -> None:
    content = '{"verdict":"keep","issue_codes":[],"evidence_refs":[],"confidence":1}'
    provider = _QueueProvider(
        [ModelResponse(content, (ToolCall("x", "danger", {}),), TokenUsage(1, 1))]
    )

    result = await _service(provider).reflect([], "draft")

    assert result.outcome is ReflectionOutcomeCode.TOOL_CALL_BLOCKED
    assert result.content == "draft"
    assert result.calls == 1


def test_reflection_durable_events_are_hash_only_and_drop_content() -> None:
    secret = "draft-secret-123"
    redactor = PersistenceRedactor()
    payload = safe_event_payload(
        AgentEventKind.REFLECTION_VERDICT.value,
        {
            "rubric_id": "quality",
            "rubric_version": "1",
            "draft_hash": "a" * 64,
            "critique_hash": "b" * 64,
            "verdict": "revise",
            "issue_codes": ["factual_error"],
            "evidence_refs": ["draft:L1"],
            "confidence": 0.9,
            "draft": secret,
            "critique": f"hidden chain of thought {secret}",
            "revision": secret,
        },
        redactor,
    )

    encoded = str(payload)
    assert secret not in encoded
    assert "chain of thought" not in encoded
    assert set(payload) == {
        "rubric_id",
        "rubric_version",
        "draft_hash",
        "critique_hash",
        "verdict",
        "issue_codes",
        "evidence_refs",
        "confidence",
    }
