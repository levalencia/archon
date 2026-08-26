"""Strict, bounded data contracts for isolated verifier children."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.runtime.models import TokenUsage

MAX_CLAIMS = 32
MAX_EVIDENCE_SLICES = 32
MAX_TEXT_CHARS = 1_000
MAX_QUOTE_CHARS = 1_000
MAX_INPUT_TOKENS = 32_768
MAX_OUTPUT_TOKENS = 8_192
MIN_TIMEOUT_SECONDS = 0.1
MAX_TIMEOUT_SECONDS = 60.0

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _validate_id(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe identifier")


def _validate_hash(value: object, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _bounded_text(value: object, field_name: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{field_name} must be non-empty and at most {maximum} characters")


def _ids(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{field_name} must be an immutable tuple")
    for item in value:
        _validate_id(item, field_name)
    if len(value) > MAX_EVIDENCE_SLICES or len(value) != len(set(value)):
        raise ValueError(f"{field_name} must be unique and bounded")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceSlice:
    """A single provenance-bearing quotation and no arbitrary metadata."""

    evidence_id: str
    document_id: str
    chunk_id: str
    content_hash: str
    quote: str

    def __post_init__(self) -> None:
        _validate_id(self.evidence_id, "evidence_id")
        _validate_id(self.document_id, "document_id")
        _validate_id(self.chunk_id, "chunk_id")
        _validate_hash(self.content_hash, "content_hash")
        _bounded_text(self.quote, "quote", MAX_QUOTE_CHARS)


@dataclass(frozen=True, slots=True)
class ClaimInput:
    claim_id: str
    claim_hash: str
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_id(self.claim_id, "claim_id")
        _validate_hash(self.claim_hash, "claim_hash")
        _bounded_text(self.text, "text", MAX_TEXT_CHARS)
        _ids(self.evidence_ids, "evidence_ids")


@dataclass(frozen=True, slots=True)
class VerificationBudget:
    input_tokens: int
    output_tokens: int
    timeout_seconds: float
    retries: int = 0

    def __post_init__(self) -> None:
        if type(self.input_tokens) is not int or not 1 <= self.input_tokens <= MAX_INPUT_TOKENS:
            raise ValueError("input_tokens is outside the supported bounds")
        if type(self.output_tokens) is not int or not 1 <= self.output_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("output_tokens is outside the supported bounds")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not MIN_TIMEOUT_SECONDS <= float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_seconds is outside the supported bounds")
        if type(self.retries) is not int or self.retries not in (0, 1):
            raise ValueError("retries must be zero or one")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))


@dataclass(frozen=True, slots=True)
class ChildVerificationRequest:
    child_id: str
    parent_run_id: str
    user_id: str
    project_id: str
    policy_id: str
    model: str
    claims: tuple[ClaimInput, ...]
    evidence: tuple[EvidenceSlice, ...]
    budget: VerificationBudget
    tools: tuple[()] = ()

    def __post_init__(self) -> None:
        for value, name in (
            (self.child_id, "child_id"),
            (self.parent_run_id, "parent_run_id"),
            (self.user_id, "user_id"),
            (self.project_id, "project_id"),
            (self.policy_id, "policy_id"),
            (self.model, "model"),
        ):
            _validate_id(value, name)
        if not isinstance(self.claims, tuple) or not 1 <= len(self.claims) <= MAX_CLAIMS:
            raise ValueError("claims must be an immutable, non-empty, bounded tuple")
        if (
            not isinstance(self.evidence, tuple)
            or not 1 <= len(self.evidence) <= MAX_EVIDENCE_SLICES
        ):
            raise ValueError("evidence must be an immutable, non-empty, bounded tuple")
        if not all(isinstance(claim, ClaimInput) for claim in self.claims):
            raise ValueError("claims contains an invalid value")
        if not all(isinstance(item, EvidenceSlice) for item in self.evidence):
            raise ValueError("evidence contains an invalid value")
        if not isinstance(self.budget, VerificationBudget):
            raise ValueError("budget must be a VerificationBudget")
        if not isinstance(self.tools, tuple) or self.tools:
            raise ValueError("verifier children cannot receive tools")

        claim_ids = tuple(claim.claim_id for claim in self.claims)
        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim IDs must be unique")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        delegated = set(evidence_ids)
        if any(not set(claim.evidence_ids).issubset(delegated) for claim in self.claims):
            raise ValueError("claims may reference only delegated evidence")


class ClaimVerdictStatus(StrEnum):
    SUPPORTED = "supported"
    REJECTED = "rejected"
    ESCALATE = "escalate"


class VerificationReasonCode(StrEnum):
    EVIDENCE_SUPPORTS = "evidence_supports"
    EVIDENCE_CONTRADICTS = "evidence_contradicts"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INVALID_CITATION = "invalid_citation"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    MALFORMED_RESPONSE = "malformed_response"


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    claim_id: str
    status: ClaimVerdictStatus
    reason_code: VerificationReasonCode
    confidence: float
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.claim_id, "claim_id")
        if not isinstance(self.status, ClaimVerdictStatus):
            object.__setattr__(self, "status", ClaimVerdictStatus(self.status))
        if not isinstance(self.reason_code, VerificationReasonCode):
            object.__setattr__(self, "reason_code", VerificationReasonCode(self.reason_code))
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not math.isfinite(float(self.confidence))
            or not 0.0 <= float(self.confidence) <= 1.0
        ):
            raise ValueError("confidence must be finite and between zero and one")
        _ids(self.evidence_ids, "evidence_ids")
        object.__setattr__(self, "confidence", float(self.confidence))


class ChildVerificationStatus(StrEnum):
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChildVerificationResult:
    child_id: str
    parent_run_id: str
    status: ChildVerificationStatus
    usage: TokenUsage
    latency_ms: float
    verdicts: tuple[ClaimVerdict, ...]

    def __post_init__(self) -> None:
        _validate_id(self.child_id, "child_id")
        _validate_id(self.parent_run_id, "parent_run_id")
        if not isinstance(self.status, ChildVerificationStatus):
            object.__setattr__(self, "status", ChildVerificationStatus(self.status))
        if not isinstance(self.usage, TokenUsage):
            raise ValueError("usage must be TokenUsage")
        if (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or not math.isfinite(float(self.latency_ms))
            or float(self.latency_ms) < 0.0
        ):
            raise ValueError("latency_ms must be finite and non-negative")
        if not isinstance(self.verdicts, tuple) or len(self.verdicts) > MAX_CLAIMS:
            raise ValueError("verdicts must be an immutable bounded tuple")
        if not all(isinstance(verdict, ClaimVerdict) for verdict in self.verdicts):
            raise ValueError("verdicts contains an invalid value")
        claim_ids = tuple(verdict.claim_id for verdict in self.verdicts)
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("verdict claim IDs must be unique")
        object.__setattr__(self, "latency_ms", float(self.latency_ms))


def validate_verdict_evidence_subset(
    verdicts: Iterable[ClaimVerdict], allowed_evidence_ids: Iterable[str]
) -> None:
    """Reject verdict citations that were not present in the delegated request."""

    allowed = frozenset(allowed_evidence_ids)
    if any(not set(verdict.evidence_ids).issubset(allowed) for verdict in verdicts):
        raise ValueError("verdicts may reference only delegated evidence")
