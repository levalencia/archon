"""Execution boundary for the isolated evidence-verifier specialist."""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app.delegation.models import (
    ChildVerificationRequest,
    ChildVerificationResult,
    ChildVerificationStatus,
    ClaimVerdict,
    ClaimVerdictStatus,
    VerificationReasonCode,
    validate_verdict_evidence_subset,
)
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


class EvidenceVerifierSpecialist:
    """Run one no-tools verifier child and durably record its safe lifecycle."""

    def __init__(
        self,
        provider: ModelProvider,
        runs: RunRepository,
        redactor: PersistenceRedactor,
    ) -> None:
        self._provider = provider
        self._runs = runs
        self._redactor = redactor

    async def verify(self, request: ChildVerificationRequest) -> ChildVerificationResult:
        # Keep redaction as an explicit dependency of this persistence boundary.
        # RunRepository performs the actual allow-listing and redaction.
        _ = self._redactor
        started = time.monotonic()
        messages = _messages(request)
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
        await self._append(
            request,
            AgentEventKind.DELEGATION_REQUESTED,
            0,
            self._request_payload(request, estimate),
            usage,
        )
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
                if estimate * (attempts + 1) > request.budget.input_tokens:
                    raise _BudgetExhaustedError
                attempts += 1
                try:
                    response = await self._provider.complete(
                        messages, tools=(), max_tokens=request.budget.output_tokens
                    )
                    usage = usage + response.usage
                    return _parse_response(response, request)
                except (TransientVerifierError, ConnectionError, OSError):
                    if attempts > request.budget.retries:
                        raise

        try:
            verdicts = await asyncio.wait_for(execute(), timeout=request.budget.timeout_seconds)
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
        await self._append(request, AgentEventKind.DELEGATION_COMPLETED, attempts, payload, usage)
        await self._append(
            request,
            AgentEventKind.RUN_STOPPED,
            attempts,
            {"reason": status.value, "error": status is not ChildVerificationStatus.COMPLETED},
            usage,
        )
        await self._runs.finalize_metadata(
            request.user_id, request.child_id, answer="", cost_usd=0.0, latency_ms=latency
        )
        return ChildVerificationResult(
            request.child_id, request.parent_run_id, status, usage, latency, verdicts
        )

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
