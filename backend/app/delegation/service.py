"""Execution boundary for the isolated evidence-verifier specialist."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import structlog

from app.delegation.envelope import (
    DelegationEnvelope,
    DelegationEnvelopeService,
    InvalidDelegationEnvelope,
)
from app.delegation.models import (
    ChildVerificationRequest,
    ChildVerificationResult,
    ChildVerificationStatus,
    ClaimVerdict,
    ClaimVerdictStatus,
    VerificationReasonCode,
    validate_verdict_evidence_subset,
)
from app.runtime.deadline import DeadlineExceededError, await_before_deadline, consume_detached_task
from app.runtime.events import AgentEventKind
from app.runtime.models import Message, ModelResponse, Role, TokenUsage
from app.runtime.ports import ModelProvider
from app.security.persistence_redactor import PersistenceRedactor
from app.services.run_ledger import RunRepository

_SYSTEM_PROMPT = """You are an isolated evidence verifier.
Use only the claims and evidence in the user JSON. Do not use outside knowledge.
Return JSON with exactly one top-level key, "verdicts". Each verdict must contain exactly
claim_id, status, reason_code, confidence, evidence_ids. status is supported, rejected, or
escalate. reason_code is evidence_supports, evidence_contradicts, insufficient_evidence, or
invalid_citation. Include every claim exactly once and cite only supplied evidence IDs."""
_VERDICT_KEYS = frozenset({"claim_id", "status", "reason_code", "confidence", "evidence_ids"})
_TERMINAL_CLEANUP_SECONDS = 0.125
logger = structlog.get_logger()


@dataclass(slots=True)
class _VerifierTerminalState:
    started: bool = False
    persisted: bool = False
    result: ChildVerificationResult | None = None
    task: asyncio.Task[None] | None = None


_VERIFIER_TERMINAL_STATE: ContextVar[_VerifierTerminalState | None] = ContextVar(
    "verifier_terminal_state", default=None
)


class TransientVerifierError(RuntimeError):
    """Provider failure that is explicitly safe to retry once."""


class _MalformedResponseError(ValueError):
    pass


class _BudgetExhaustedError(RuntimeError):
    pass


def estimate_input_tokens(messages: Sequence[Message]) -> int:
    """Return a deterministic conservative estimate independent of configuration."""
    return sum(math.ceil(len(message.content.encode("utf-8")) / 4) + 8 for message in messages)


def _messages(request: ChildVerificationRequest) -> tuple[Message, Message]:
    body = {
        "claims": [
            {
                "claim_id": claim.claim_id,
                "claim_hash": claim.claim_hash,
                "text": claim.text,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in request.claims
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "content_hash": item.content_hash,
                "quote": item.quote,
            }
            for item in request.evidence
        ],
    }
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return Message(Role.SYSTEM, _SYSTEM_PROMPT), Message(Role.USER, encoded)


def _parse_response(
    response: ModelResponse, request: ChildVerificationRequest
) -> tuple[ClaimVerdict, ...]:
    if response.tool_calls or response.content is None:
        raise _MalformedResponseError("tools or empty content are invalid verifier output")
    try:
        value = json.loads(response.content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise _MalformedResponseError("response is not JSON") from exc
    if not isinstance(value, dict) or set(value) != {"verdicts"}:
        raise _MalformedResponseError("response must contain only verdicts")
    raw_verdicts = value["verdicts"]
    if not isinstance(raw_verdicts, list):
        raise _MalformedResponseError("verdicts must be a list")
    verdicts: list[ClaimVerdict] = []
    try:
        for raw in raw_verdicts:
            if not isinstance(raw, dict) or set(raw) != _VERDICT_KEYS:
                raise _MalformedResponseError("verdict has an invalid shape")
            evidence_ids = raw["evidence_ids"]
            if not isinstance(evidence_ids, list) or not all(
                isinstance(item, str) for item in evidence_ids
            ):
                raise _MalformedResponseError("evidence_ids must be a string list")
            verdicts.append(
                ClaimVerdict(
                    claim_id=raw["claim_id"],
                    status=raw["status"],
                    reason_code=raw["reason_code"],
                    confidence=raw["confidence"],
                    evidence_ids=tuple(evidence_ids),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise _MalformedResponseError("invalid verdict") from exc
    expected = {claim.claim_id for claim in request.claims}
    if len(verdicts) != len(expected) or {item.claim_id for item in verdicts} != expected:
        raise _MalformedResponseError("claim IDs must appear exactly once")
    try:
        validate_verdict_evidence_subset(verdicts, (item.evidence_id for item in request.evidence))
    except ValueError as exc:
        raise _MalformedResponseError("verdict cites foreign evidence") from exc
    by_claim = {claim.claim_id: frozenset(claim.evidence_ids) for claim in request.claims}
    if any(not set(item.evidence_ids).issubset(by_claim[item.claim_id]) for item in verdicts):
        raise _MalformedResponseError("verdict cites evidence not delegated to its claim")
    for verdict in verdicts:
        valid_reason = (
            (
                verdict.status is ClaimVerdictStatus.SUPPORTED
                and verdict.reason_code is VerificationReasonCode.EVIDENCE_SUPPORTS
                and bool(verdict.evidence_ids)
            )
            or (
                verdict.status is ClaimVerdictStatus.REJECTED
                and verdict.reason_code is VerificationReasonCode.EVIDENCE_CONTRADICTS
            )
            or (
                verdict.status is ClaimVerdictStatus.ESCALATE
                and verdict.reason_code
                in {
                    VerificationReasonCode.INSUFFICIENT_EVIDENCE,
                    VerificationReasonCode.INVALID_CITATION,
                }
            )
        )
        if not valid_reason:
            raise _MalformedResponseError("status and reason_code are inconsistent")
    return tuple(verdicts)


def _fail_closed(
    request: ChildVerificationRequest, reason: VerificationReasonCode
) -> tuple[ClaimVerdict, ...]:
    return tuple(
        ClaimVerdict(claim.claim_id, ClaimVerdictStatus.ESCALATE, reason, 0.0)
        for claim in request.claims
    )


def verifier_delegation_context(request: ChildVerificationRequest) -> dict[str, Any]:
    """Canonical bounded request content that the parent authorizes for the child."""
    return {
        "policy_id": request.policy_id,
        "model": request.model,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "claim_hash": claim.claim_hash,
                "text": claim.text,
                "evidence_ids": list(claim.evidence_ids),
            }
            for claim in request.claims
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "document_id": item.document_id,
                "chunk_id": item.chunk_id,
                "content_hash": item.content_hash,
                "quote": item.quote,
            }
            for item in request.evidence
        ],
    }


def verifier_delegation_budget(request: ChildVerificationRequest) -> dict[str, int | float]:
    return {
        "input_tokens": request.budget.input_tokens,
        "output_tokens": request.budget.output_tokens,
        "retries": request.budget.retries,
        "timeout_seconds": request.budget.timeout_seconds,
    }


def issue_verifier_delegation(
    envelopes: DelegationEnvelopeService, request: ChildVerificationRequest
) -> DelegationEnvelope:
    """Parent/orchestrator boundary: issue authorization before entering the child."""
    return envelopes.issue(
        parent_run_id=request.parent_run_id,
        child_run_id=request.child_id,
        owner_id=request.user_id,
        project_id=request.project_id,
        context_hash=envelopes.context_digest(verifier_delegation_context(request)),
        budget=verifier_delegation_budget(request),
    )


class EvidenceVerifierSpecialist:
    """Run one no-tools verifier child and durably record its safe lifecycle."""

    def __init__(
        self,
        provider: ModelProvider,
        runs: RunRepository,
        redactor: PersistenceRedactor,
        envelopes: DelegationEnvelopeService | None = None,
        provider_factory: Callable[[ChildVerificationRequest], ModelProvider] | None = None,
    ) -> None:
        self._provider = provider
        self._provider_factory = provider_factory
        self._runs = runs
        self._redactor = redactor
        self._envelopes = envelopes

    async def verify(
        self,
        request: ChildVerificationRequest,
        envelope: DelegationEnvelope | None = None,
    ) -> ChildVerificationResult:
        started = time.monotonic()
        deadline = started + request.budget.timeout_seconds
        terminal = _VerifierTerminalState()
        token = _VERIFIER_TERMINAL_STATE.set(terminal)
        try:
            return await await_before_deadline(
                self._verify(request, envelope, started=started),
                deadline=deadline,
            )
        except DeadlineExceededError:
            if terminal.started:
                await self._bounded_finish(
                    request,
                    ChildVerificationStatus.TIMEOUT,
                    _fail_closed(request, VerificationReasonCode.TIMEOUT),
                    TokenUsage(),
                    started,
                    VerificationReasonCode.TIMEOUT,
                    0,
                )
                if terminal.result is not None:
                    return terminal.result
            verdicts = _fail_closed(request, VerificationReasonCode.TIMEOUT)
            await self._bounded_finish(
                request,
                ChildVerificationStatus.TIMEOUT,
                verdicts,
                TokenUsage(),
                started,
                VerificationReasonCode.TIMEOUT,
                0,
            )
            return terminal.result or ChildVerificationResult(
                request.child_id,
                request.parent_run_id,
                ChildVerificationStatus.TIMEOUT,
                TokenUsage(),
                (time.monotonic() - started) * 1000,
                verdicts,
            )
        except asyncio.CancelledError:
            if not terminal.started:
                await self._bounded_finish(
                    request,
                    ChildVerificationStatus.CANCELLED,
                    _fail_closed(request, VerificationReasonCode.PROVIDER_ERROR),
                    TokenUsage(),
                    started,
                    VerificationReasonCode.PROVIDER_ERROR,
                    0,
                )
            elif not terminal.persisted:
                logger.warning(
                    "verifier_terminal_persistence_indeterminate",
                    child_run_id=request.child_id,
                    status=(terminal.result.status.value if terminal.result else "unknown"),
                    error_type="cancelled",
                )
            raise
        finally:
            _VERIFIER_TERMINAL_STATE.reset(token)

    async def _verify(
        self,
        request: ChildVerificationRequest,
        envelope: DelegationEnvelope | None,
        *,
        started: float,
    ) -> ChildVerificationResult:
        # Keep redaction as an explicit dependency of this persistence boundary.
        # RunRepository performs the actual allow-listing and redaction.
        _ = self._redactor
        if self._envelopes is not None:
            if envelope is None:
                raise InvalidDelegationEnvelope("delegation envelope is required")
            context_hash = self._envelopes.context_digest(verifier_delegation_context(request))
            budget = verifier_delegation_budget(request)
            if dict(envelope.budget) != budget:
                raise InvalidDelegationEnvelope("delegation envelope rejected")
            await self._envelopes.verify_and_consume(
                envelope,
                owner_id=request.user_id,
                project_id=request.project_id,
                parent_run_id=request.parent_run_id,
                child_run_id=request.child_id,
                context_hash=context_hash,
            )
            if time.monotonic() >= started + request.budget.timeout_seconds:
                raise DeadlineExceededError
        messages = list(_messages(request))
        estimate = estimate_input_tokens(messages)
        usage = TokenUsage()
        attempts = 0
        await self._runs.ensure_child_run(
            run_id=request.child_id,
            parent_run_id=request.parent_run_id,
            user_id=request.user_id,
            project_id=request.project_id,
            provider="verifier",
            model=request.model,
        )
        if time.monotonic() >= started + request.budget.timeout_seconds:
            raise DeadlineExceededError
        provider = (
            self._provider_factory(request)
            if self._provider_factory is not None
            else self._provider
        )
        await self._append(
            request,
            AgentEventKind.DELEGATION_REQUESTED,
            0,
            self._request_payload(request, estimate),
            usage,
        )
        if time.monotonic() >= started + request.budget.timeout_seconds:
            raise DeadlineExceededError
        if estimate > request.budget.input_tokens:
            return await self._finish(
                request,
                ChildVerificationStatus.FAILED,
                _fail_closed(request, VerificationReasonCode.BUDGET_EXCEEDED),
                usage,
                started,
                VerificationReasonCode.BUDGET_EXCEEDED,
                attempts,
            )

        async def execute() -> tuple[ClaimVerdict, ...]:
            nonlocal usage, attempts
            while True:
                current_estimate = estimate_input_tokens(messages)
                remaining_input = request.budget.input_tokens - usage.input_tokens
                remaining_output = request.budget.output_tokens - usage.output_tokens
                # The estimate is only a pre-call guard. Provider-reported usage is the
                # authority after a call and is accumulated across every response.
                if (
                    remaining_input < current_estimate
                    or remaining_output <= 0
                    or usage.total_tokens + current_estimate
                    > request.budget.input_tokens + request.budget.output_tokens
                ):
                    raise _BudgetExhaustedError
                attempts += 1
                try:
                    response = await provider.complete(
                        messages,
                        tools=(),
                        max_tokens=remaining_output,
                        response_format="json",
                    )
                    usage = usage + response.usage
                    if (
                        usage.input_tokens > request.budget.input_tokens
                        or usage.output_tokens > request.budget.output_tokens
                        or usage.total_tokens
                        > request.budget.input_tokens + request.budget.output_tokens
                    ):
                        raise _BudgetExhaustedError
                    try:
                        return _parse_response(response, request)
                    except _MalformedResponseError:
                        if attempts > request.budget.retries:
                            raise
                        messages.append(
                            Message(
                                Role.USER,
                                "The prior verifier response was invalid. Return one JSON object "
                                "with only the verdicts array and the exact required fields; "
                                "include no prose or markdown.",
                            )
                        )
                except (TransientVerifierError, ConnectionError, OSError):
                    if attempts > request.budget.retries:
                        raise

        try:
            verdicts = await await_before_deadline(
                execute(), deadline=started + request.budget.timeout_seconds
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel(request, usage, started, attempts))
            raise
        except TimeoutError:
            return await self._finish(
                request,
                ChildVerificationStatus.TIMEOUT,
                _fail_closed(request, VerificationReasonCode.TIMEOUT),
                usage,
                started,
                VerificationReasonCode.TIMEOUT,
                attempts,
            )
        except _MalformedResponseError:
            return await self._finish(
                request,
                ChildVerificationStatus.FAILED,
                _fail_closed(request, VerificationReasonCode.MALFORMED_RESPONSE),
                usage,
                started,
                VerificationReasonCode.MALFORMED_RESPONSE,
                attempts,
            )
        except _BudgetExhaustedError:
            return await self._finish(
                request,
                ChildVerificationStatus.FAILED,
                _fail_closed(request, VerificationReasonCode.BUDGET_EXCEEDED),
                usage,
                started,
                VerificationReasonCode.BUDGET_EXCEEDED,
                attempts,
            )
        except (TransientVerifierError, ConnectionError, OSError):
            return await self._finish(
                request,
                ChildVerificationStatus.FAILED,
                _fail_closed(request, VerificationReasonCode.PROVIDER_ERROR),
                usage,
                started,
                VerificationReasonCode.PROVIDER_ERROR,
                attempts,
            )
        except Exception:
            return await self._finish(
                request,
                ChildVerificationStatus.FAILED,
                _fail_closed(request, VerificationReasonCode.PROVIDER_ERROR),
                usage,
                started,
                VerificationReasonCode.PROVIDER_ERROR,
                attempts,
            )
        return await self._finish(
            request,
            ChildVerificationStatus.COMPLETED,
            verdicts,
            usage,
            started,
            None,
            attempts,
        )

    async def _bounded_finish(
        self,
        request: ChildVerificationRequest,
        status: ChildVerificationStatus,
        verdicts: tuple[ClaimVerdict, ...],
        usage: TokenUsage,
        started: float,
        reason: VerificationReasonCode | None,
        attempts: int,
    ) -> None:
        terminal = _VERIFIER_TERMINAL_STATE.get()
        if terminal is not None and terminal.started:
            if terminal.task is not None and not terminal.task.done():

                async def wait_for_existing_terminal() -> None:
                    await asyncio.shield(terminal.task)

                with suppress(BaseException):
                    await await_before_deadline(
                        wait_for_existing_terminal(),
                        deadline=time.monotonic() + _TERMINAL_CLEANUP_SECONDS,
                    )
                if not terminal.task.done():
                    terminal.task.cancel()
                    with suppress(BaseException):
                        await await_before_deadline(
                            wait_for_existing_terminal(),
                            deadline=time.monotonic() + _TERMINAL_CLEANUP_SECONDS,
                        )
            if not terminal.persisted:
                logger.warning(
                    "verifier_terminal_persistence_indeterminate",
                    child_run_id=request.child_id,
                    status=(terminal.result.status.value if terminal.result else status.value),
                    error_type="terminal_already_started",
                )
            return
        try:
            await await_before_deadline(
                self._finish(request, status, verdicts, usage, started, reason, attempts),
                deadline=time.monotonic() + _TERMINAL_CLEANUP_SECONDS,
            )
        except BaseException as cleanup_error:
            logger.warning(
                "verifier_terminal_persistence_indeterminate",
                child_run_id=request.child_id,
                status=status.value,
                error_type=type(cleanup_error).__name__,
            )

    async def _finish(
        self,
        request: ChildVerificationRequest,
        status: ChildVerificationStatus,
        verdicts: tuple[ClaimVerdict, ...],
        usage: TokenUsage,
        started: float,
        reason: VerificationReasonCode | None,
        attempts: int,
    ) -> ChildVerificationResult:
        latency = (time.monotonic() - started) * 1000
        result = ChildVerificationResult(
            request.child_id,
            request.parent_run_id,
            status,
            usage,
            latency,
            verdicts,
        )
        terminal = _VERIFIER_TERMINAL_STATE.get()
        if terminal is not None:
            if terminal.started:
                if terminal.result is None:
                    raise RuntimeError("verifier terminal state is incomplete")
                if terminal.task is not None:
                    await asyncio.shield(terminal.task)
                return terminal.result
            terminal.started = True
            terminal.result = result
        counts = {item.value: 0 for item in ClaimVerdictStatus}
        for verdict in verdicts:
            counts[verdict.status.value] += 1
        payload: dict[str, Any] = {
            **self._request_payload(request, estimate_input_tokens(_messages(request))),
            "status": status.value,
            "reason_code": reason.value if reason else None,
            "reason_codes": sorted({item.reason_code.value for item in verdicts}),
            "supported_count": counts[ClaimVerdictStatus.SUPPORTED.value],
            "rejected_count": counts[ClaimVerdictStatus.REJECTED.value],
            "escalated_count": counts[ClaimVerdictStatus.ESCALATE.value],
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }

        async def persist_terminal() -> None:
            await self._append(
                request,
                AgentEventKind.DELEGATION_COMPLETED,
                attempts,
                payload,
                usage,
            )
            await self._append(
                request,
                AgentEventKind.RUN_STOPPED,
                attempts,
                {"reason": status.value, "error": status is not ChildVerificationStatus.COMPLETED},
                usage,
            )
            await self._runs.finalize_metadata(
                request.user_id,
                request.child_id,
                answer="",
                cost_usd=0.0,
                latency_ms=latency,
            )
            if terminal is not None:
                terminal.persisted = True

        task = asyncio.create_task(persist_terminal())
        task.add_done_callback(consume_detached_task)
        if terminal is not None:
            terminal.task = task
        await asyncio.shield(task)
        return result

    async def _cancel(
        self,
        request: ChildVerificationRequest,
        usage: TokenUsage,
        started: float,
        attempts: int,
    ) -> None:
        await self._finish(
            request,
            ChildVerificationStatus.CANCELLED,
            _fail_closed(request, VerificationReasonCode.PROVIDER_ERROR),
            usage,
            started,
            VerificationReasonCode.PROVIDER_ERROR,
            attempts,
        )

    async def _append(
        self,
        request: ChildVerificationRequest,
        kind: AgentEventKind,
        iteration: int,
        payload: Mapping[str, Any],
        usage: TokenUsage,
    ) -> None:
        await self._runs.append(
            run_id=request.child_id,
            user_id=request.user_id,
            project_id=request.project_id,
            conversation_id=request.parent_run_id,
            correlation_id=request.child_id,
            provider="verifier",
            model=request.model,
            kind=kind.value,
            iteration=iteration,
            payload=payload,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )

    @staticmethod
    def _request_payload(request: ChildVerificationRequest, estimate: int) -> dict[str, Any]:
        return {
            "child_id": request.child_id,
            "parent_run_id": request.parent_run_id,
            "user_id": request.user_id,
            "project_id": request.project_id,
            "policy_id": request.policy_id,
            "claim_ids": [item.claim_id for item in request.claims],
            "claim_hashes": [item.claim_hash for item in request.claims],
            "evidence_ids": [item.evidence_id for item in request.evidence],
            "content_hashes": [item.content_hash for item in request.evidence],
            "claim_count": len(request.claims),
            "evidence_count": len(request.evidence),
            "status": "requested",
            "input_tokens": estimate,
            "output_tokens": request.budget.output_tokens,
        }
