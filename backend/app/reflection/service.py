"""One-pass, tool-free reflection at the final-answer boundary."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import time
from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from app.reflection.models import (
    ReflectionDecision,
    ReflectionIssueCode,
    ReflectionOutcomeCode,
    ReflectionPolicy,
    ReflectionResult,
    ReflectionVerdict,
)
from app.runtime.events import AgentEvent, AgentEventKind, EventSink, NullEventSink
from app.runtime.models import Message, ModelResponse, Role, TokenUsage
from app.runtime.ports import ModelProvider
from app.runtime.structured_output import ResponseContract, StructuredOutputError

_CRITIQUE_SYSTEM = """You are a bounded final-answer quality reviewer, not an agent.
Do not call tools, take actions, or reveal chain-of-thought. Assess only the supplied request and
draft against the named rubric. Return only the requested compact JSON verdict. Evidence refs are
short locations such as draft:L1 or request:L2, never quotations or reasoning."""
_REVISION_SYSTEM = """You are a bounded final-answer editor, not an agent.
Do not call tools, take actions, discuss your reasoning, or output metadata. Return only one revised
final answer that fixes the supplied issue codes using the supplied evidence references."""
_VERDICT_KEYS = frozenset({"verdict", "issue_codes", "evidence_refs", "confidence"})


class _ReflectionLimitError(RuntimeError):
    def __init__(self, code: ReflectionOutcomeCode) -> None:
        self.code = code
        super().__init__(code.value)


def estimate_tokens(messages: Sequence[Message]) -> int:
    """Conservative deterministic pre-call estimate used only as a hard guard."""
    return sum(math.ceil(len(message.content.encode("utf-8")) / 4) + 8 for message in messages)


def _verdict_validator(value: Any) -> ReflectionVerdict:
    if not isinstance(value, dict) or set(value) != _VERDICT_KEYS:
        raise ValueError("invalid verdict shape")
    codes = value["issue_codes"]
    refs = value["evidence_refs"]
    if not isinstance(codes, list) or not all(isinstance(item, str) for item in codes):
        raise ValueError("issue_codes must be a string list")
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise ValueError("evidence_refs must be a string list")
    return ReflectionVerdict(
        decision=value["verdict"],
        issue_codes=tuple(codes),
        evidence_refs=tuple(refs),
        confidence=value["confidence"],
    )


REFLECTION_VERDICT_CONTRACT = ResponseContract(
    schema_id="archon.reflection-verdict",
    schema_version="1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "issue_codes", "evidence_refs", "confidence"],
        "properties": {
            "verdict": {"enum": ["keep", "revise"]},
            "issue_codes": {
                "type": "array",
                "maxItems": 16,
                "uniqueItems": True,
                "items": {"enum": [item.value for item in ReflectionIssueCode]},
            },
            "evidence_refs": {
                "type": "array",
                "maxItems": 32,
                "uniqueItems": True,
                "items": {"type": "string", "maxLength": 128},
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
    validator=_verdict_validator,
)


def derive_reflection_hmac_key(application_secret: str) -> bytes:
    if not isinstance(application_secret, str) or not application_secret:
        raise ValueError("reflection fingerprint key is unavailable")
    return hmac.new(
        application_secret.encode("utf-8"),
        b"archon/reflection-fingerprint-key/v1",
        hashlib.sha256,
    ).digest()


def _digest(key: bytes, scope: str, label: str, text: str) -> str:
    return hmac.new(
        key,
        b"archon/reflection/v1\0"
        + scope.encode("utf-8")
        + b"\0"
        + label.encode("ascii")
        + b"\0"
        + text.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class BoundedReflectionService:
    """Perform one critique and, only when requested, one revision with no tools/effects."""

    def __init__(
        self,
        provider: ModelProvider,
        policy: ReflectionPolicy,
        *,
        events: EventSink | None = None,
        clock: Any = time.monotonic,
        hash_key: bytes | None = None,
        hash_scope: str = "",
    ) -> None:
        if policy.enabled and (not isinstance(hash_key, bytes) or len(hash_key) < 32):
            raise ValueError("reflection fingerprint key is unavailable")
        if policy.enabled and (not isinstance(hash_scope, str) or not hash_scope):
            raise ValueError("reflection fingerprint scope is unavailable")
        self._provider = provider
        self._policy = policy
        self._events = events or NullEventSink()
        self._clock = clock
        self._hash_key = hash_key or b""
        self._hash_scope = hash_scope

    async def reflect(
        self,
        request_messages: Sequence[Message],
        draft: str,
        *,
        iteration: int = 0,
        timeout_seconds: float | None = None,
        max_total_tokens: int | None = None,
    ) -> ReflectionResult:
        if not self._policy.enabled:
            return ReflectionResult(draft, None, ReflectionOutcomeCode.KEPT)
        if max_total_tokens is not None and (
            type(max_total_tokens) is not int or max_total_tokens < 0
        ):
            raise ValueError("max_total_tokens must be a non-negative integer")
        started = self._clock()
        time_limit = self._policy.max_seconds
        if timeout_seconds is not None:
            time_limit = min(time_limit, max(0.0, timeout_seconds))
        usage = TokenUsage()
        cost = Decimal("0")
        calls = 0
        draft_hash = _digest(self._hash_key, self._hash_scope, "draft", draft)
        await self._emit(
            AgentEventKind.REFLECTION_STARTED,
            iteration,
            {
                "rubric_id": self._policy.rubric_id,
                "rubric_version": self._policy.rubric_version,
                "draft_hash": draft_hash,
                "max_revisions": self._policy.max_revisions,
            },
        )

        async def complete(
            messages: tuple[Message, ...], cap: int, contract: ResponseContract | None = None
        ) -> ModelResponse:
            nonlocal usage, cost, calls
            remaining_time = time_limit - (self._clock() - started)
            if remaining_time <= 0:
                raise _ReflectionLimitError(ReflectionOutcomeCode.TIME_LIMIT)
            estimated_input = estimate_tokens(messages)
            if usage.input_tokens + estimated_input > self._policy.max_input_tokens:
                raise _ReflectionLimitError(ReflectionOutcomeCode.TOKEN_LIMIT)
            remaining_output = self._policy.max_output_tokens - usage.output_tokens
            max_tokens = min(cap, remaining_output)
            if max_total_tokens is not None:
                remaining_total = max_total_tokens - usage.total_tokens - estimated_input
                max_tokens = min(max_tokens, remaining_total)
            if max_tokens <= 0:
                raise _ReflectionLimitError(ReflectionOutcomeCode.TOKEN_LIMIT)
            input_price = self._policy.input_cost_per_million_usd / Decimal(1_000_000)
            output_price = self._policy.output_cost_per_million_usd / Decimal(1_000_000)
            after_input = self._policy.max_cost_usd - cost - Decimal(estimated_input) * input_price
            if after_input < 0:
                raise _ReflectionLimitError(ReflectionOutcomeCode.COST_LIMIT)
            if output_price > 0:
                affordable = int(
                    (after_input / output_price).to_integral_value(rounding=ROUND_FLOOR)
                )
                max_tokens = min(max_tokens, affordable)
                if max_tokens <= 0:
                    raise _ReflectionLimitError(ReflectionOutcomeCode.COST_LIMIT)
            try:
                response = await asyncio.wait_for(
                    self._provider.complete(
                        messages,
                        tools=(),
                        max_tokens=max_tokens,
                        response_contract=contract,
                    ),
                    timeout=remaining_time,
                )
            except TimeoutError as exc:
                raise _ReflectionLimitError(ReflectionOutcomeCode.TIME_LIMIT) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _ReflectionLimitError(ReflectionOutcomeCode.PROVIDER_ERROR) from exc
            calls += 1
            response_usage = TokenUsage(
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.cache_read_input_tokens,
                response.usage.cache_write_input_tokens,
            )
            usage = usage + response_usage
            cost += (
                Decimal(response_usage.input_tokens) * input_price
                + Decimal(response_usage.output_tokens) * output_price
            )
            if (
                usage.input_tokens > self._policy.max_input_tokens
                or usage.output_tokens > self._policy.max_output_tokens
                or (max_total_tokens is not None and usage.total_tokens > max_total_tokens)
            ):
                raise _ReflectionLimitError(ReflectionOutcomeCode.TOKEN_LIMIT)
            if cost > self._policy.max_cost_usd:
                raise _ReflectionLimitError(ReflectionOutcomeCode.COST_LIMIT)
            if response.tool_calls:
                raise _ReflectionLimitError(ReflectionOutcomeCode.TOOL_CALL_BLOCKED)
            return response

        critique_body = json.dumps(
            {
                "rubric_id": self._policy.rubric_id,
                "rubric_version": self._policy.rubric_version,
                "request": [
                    {"role": item.role.value, "content": item.content}
                    for item in request_messages
                    if item.role in (Role.SYSTEM, Role.USER)
                ],
                "draft": draft,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        critique_messages = (
            Message(Role.SYSTEM, _CRITIQUE_SYSTEM),
            Message(Role.USER, critique_body),
        )
        verdict: ReflectionVerdict | None = None
        try:
            critique = await complete(critique_messages, 512, REFLECTION_VERDICT_CONTRACT)
            try:
                parsed = REFLECTION_VERDICT_CONTRACT.parse_and_validate(critique.content or "")
                if not isinstance(parsed, ReflectionVerdict):
                    raise StructuredOutputError("schema_mismatch", "invalid reflection verdict")
                verdict = parsed
            except StructuredOutputError as exc:
                raise _ReflectionLimitError(ReflectionOutcomeCode.INVALID_VERDICT) from exc
            await self._emit(
                AgentEventKind.REFLECTION_VERDICT,
                iteration,
                {
                    "rubric_id": self._policy.rubric_id,
                    "rubric_version": self._policy.rubric_version,
                    "draft_hash": draft_hash,
                    "critique_hash": _digest(
                        self._hash_key,
                        self._hash_scope,
                        "critique",
                        critique.content or "",
                    ),
                    "verdict": verdict.decision.value,
                    "issue_codes": [item.value for item in verdict.issue_codes],
                    "evidence_refs": list(verdict.evidence_refs),
                    "confidence": verdict.confidence,
                },
                critique.usage,
            )
            if verdict.decision is ReflectionDecision.KEEP or self._policy.max_revisions == 0:
                return await self._finish(
                    draft,
                    draft,
                    verdict,
                    ReflectionOutcomeCode.KEPT,
                    usage,
                    calls,
                    0,
                    cost,
                    iteration,
                )
            revision_body = json.dumps(
                {
                    "draft": draft,
                    "issue_codes": [item.value for item in verdict.issue_codes],
                    "evidence_refs": list(verdict.evidence_refs),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            revision = await complete(
                (Message(Role.SYSTEM, _REVISION_SYSTEM), Message(Role.USER, revision_body)),
                self._policy.max_output_tokens,
            )
            revised = revision.content.strip() if isinstance(revision.content, str) else ""
            if not revised:
                raise _ReflectionLimitError(ReflectionOutcomeCode.EMPTY_REVISION)
            return await self._finish(
                draft,
                revised,
                verdict,
                ReflectionOutcomeCode.REVISED,
                usage,
                calls,
                1,
                cost,
                iteration,
            )
        except asyncio.CancelledError:
            raise
        except _ReflectionLimitError as exc:
            return await self._finish(
                draft, draft, verdict, exc.code, usage, calls, 0, cost, iteration
            )

    async def _finish(
        self,
        draft: str,
        selected: str,
        verdict: ReflectionVerdict | None,
        outcome: ReflectionOutcomeCode,
        usage: TokenUsage,
        calls: int,
        revisions: int,
        cost: Decimal,
        iteration: int,
    ) -> ReflectionResult:
        await self._emit(
            AgentEventKind.REFLECTION_COMPLETED,
            iteration,
            {
                "rubric_id": self._policy.rubric_id,
                "rubric_version": self._policy.rubric_version,
                "draft_hash": _digest(self._hash_key, self._hash_scope, "draft", draft),
                "selected_hash": _digest(
                    self._hash_key, self._hash_scope, "selected", selected
                ),
                "outcome": outcome.value,
                "calls": calls,
                "revisions": revisions,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cost_microusd": int(cost * Decimal(1_000_000)),
            },
            usage,
        )
        return ReflectionResult(selected, verdict, outcome, usage, calls, revisions, cost)

    async def _emit(
        self,
        kind: AgentEventKind,
        iteration: int,
        data: dict[str, Any],
        usage: TokenUsage | None = None,
    ) -> None:
        await self._events.emit(AgentEvent(kind, iteration, data, usage or TokenUsage()))
