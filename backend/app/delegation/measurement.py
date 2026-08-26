"""Pure, deterministic measurement for baseline-versus-verifier evaluations."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.delegation.models import (
    MAX_CLAIMS,
    MAX_EVIDENCE_SLICES,
    MAX_QUOTE_CHARS,
    MAX_TEXT_CHARS,
    ChildVerificationResult,
    ChildVerificationStatus,
    ClaimVerdictStatus,
)

_SCHEMA_VERSION = 1
_TOP_LEVEL_KEYS = frozenset({"schema_version", "dataset_id", "version", "content_hash", "cases"})
_CASE_KEYS = frozenset({"key", "question", "expected_outcome", "evidence", "claims"})
_EVIDENCE_KEYS = frozenset({"evidence_id", "document_id", "chunk_id", "quote"})
_CLAIM_KEYS = frozenset({"claim_id", "text", "evidence_ids", "expected_label"})
_MAX_CASES = 100
_MAX_ID_CHARS = 128
_MAX_QUESTION_CHARS = 1_000


class VerifierFixtureError(ValueError):
    """The benchmark fixture is malformed, unsupported, or has drifted."""


class ExpectedLabel(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True, slots=True)
class VerifierEvidence:
    evidence_id: str
    document_id: str
    chunk_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class VerifierClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    expected_label: ExpectedLabel


@dataclass(frozen=True, slots=True)
class VerifierBenchmarkCase:
    key: str
    question: str
    expected_outcome: ExpectedLabel
    evidence: tuple[VerifierEvidence, ...]
    claims: tuple[VerifierClaim, ...]


@dataclass(frozen=True, slots=True)
class VerifierBenchmarkFixture:
    schema_version: int
    dataset_id: str
    version: str
    content_hash: str
    cases: tuple[VerifierBenchmarkCase, ...]


@dataclass(frozen=True, slots=True)
class VerificationObservation:
    """One fixture claim and its observed baseline/child decisions."""

    case_key: str
    expected_label: ExpectedLabel
    claim_id: str | None
    baseline_supported: bool
    child_result: ChildVerificationResult | None
    child_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.case_key:
            raise ValueError("case_key must be non-empty")
        if self.expected_label is ExpectedLabel.NO_EVIDENCE:
            if (
                self.claim_id is not None
                or self.baseline_supported
                or self.child_result is not None
            ):
                raise ValueError("no-evidence observations cannot contain a claim or delegation")
        elif self.claim_id is None:
            raise ValueError("claim observations require claim_id")
        if self.child_cost_usd is not None and (
            not math.isfinite(self.child_cost_usd) or self.child_cost_usd < 0.0
        ):
            raise ValueError("child_cost_usd must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class VerifierBenefitReport:
    cases: int
    evaluated_claims: int
    delegations: int
    baseline_supported_count: int
    child_supported_count: int
    baseline_false_support_rate: float
    child_false_support_rate: float
    baseline_false_reject_rate: float
    child_false_reject_rate: float
    beneficial_rejections: int
    failures: int
    escalations: int
    input_tokens: int
    output_tokens: int
    child_latency_ms: float | None
    child_cost_usd: float | None
    unnecessary_delegation: int
    value_added: bool


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerifierFixtureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _bounded_string(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise VerifierFixtureError(f"{field} must be a non-empty bounded string")
    return value


def _label(value: object, field: str) -> ExpectedLabel:
    if not isinstance(value, str):
        raise VerifierFixtureError(f"{field} is invalid")
    try:
        return ExpectedLabel(value)
    except ValueError as exc:
        raise VerifierFixtureError(f"{field} is invalid") from exc


def _canonical(fixture: VerifierBenchmarkFixture) -> bytes:
    body = {
        "cases": [
            {
                "claims": [
                    {
                        "claim_id": claim.claim_id,
                        "evidence_ids": list(claim.evidence_ids),
                        "expected_label": claim.expected_label.value,
                        "text": claim.text,
                    }
                    for claim in case.claims
                ],
                "evidence": [
                    {
                        "chunk_id": item.chunk_id,
                        "document_id": item.document_id,
                        "evidence_id": item.evidence_id,
                        "quote": item.quote,
                    }
                    for item in case.evidence
                ],
                "expected_outcome": case.expected_outcome.value,
                "key": case.key,
                "question": case.question,
            }
            for case in fixture.cases
        ],
        "dataset_id": fixture.dataset_id,
        "schema_version": fixture.schema_version,
        "version": fixture.version,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def verifier_fixture_content_hash(fixture: VerifierBenchmarkFixture) -> str:
    """Return the canonical SHA-256 identity, excluding the declared hash."""

    return hashlib.sha256(_canonical(fixture)).hexdigest()


def load_verifier_benchmark_fixture(path: Path) -> VerifierBenchmarkFixture:
    """Load an exact-schema, bounded fixture and reject hash or version drift."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except VerifierFixtureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerifierFixtureError("fixture is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise VerifierFixtureError("fixture has an invalid top-level schema")
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise VerifierFixtureError("unsupported fixture schema version")
    dataset_id = _bounded_string(raw["dataset_id"], "dataset_id", 255)
    version = _bounded_string(raw["version"], "version", 100)
    content_hash = raw["content_hash"]
    if (
        not isinstance(content_hash, str)
        or len(content_hash) != 64
        or any(char not in "0123456789abcdef" for char in content_hash)
    ):
        raise VerifierFixtureError("content_hash must be a lowercase SHA-256 digest")
    raw_cases = raw["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= _MAX_CASES:
        raise VerifierFixtureError("cases must be a non-empty bounded list")

    cases: list[VerifierBenchmarkCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or set(raw_case) != _CASE_KEYS:
            raise VerifierFixtureError("case has an invalid schema")
        key = _bounded_string(raw_case["key"], "case key", _MAX_ID_CHARS)
        question = _bounded_string(raw_case["question"], "question", _MAX_QUESTION_CHARS)
        outcome = _label(raw_case["expected_outcome"], "expected_outcome")
        raw_evidence = raw_case["evidence"]
        raw_claims = raw_case["claims"]
        if not isinstance(raw_evidence, list) or len(raw_evidence) > MAX_EVIDENCE_SLICES:
            raise VerifierFixtureError("evidence must be a bounded list")
        if not isinstance(raw_claims, list) or len(raw_claims) > MAX_CLAIMS:
            raise VerifierFixtureError("claims must be a bounded list")

        evidence: list[VerifierEvidence] = []
        for raw_item in raw_evidence:
            if not isinstance(raw_item, dict) or set(raw_item) != _EVIDENCE_KEYS:
                raise VerifierFixtureError("evidence has an invalid schema")
            evidence.append(
                VerifierEvidence(
                    _bounded_string(raw_item["evidence_id"], "evidence_id", _MAX_ID_CHARS),
                    _bounded_string(raw_item["document_id"], "document_id", _MAX_ID_CHARS),
                    _bounded_string(raw_item["chunk_id"], "chunk_id", _MAX_ID_CHARS),
                    _bounded_string(raw_item["quote"], "quote", MAX_QUOTE_CHARS),
                )
            )
        evidence_ids = {item.evidence_id for item in evidence}
        if len(evidence_ids) != len(evidence):
            raise VerifierFixtureError("evidence IDs must be unique")

        claims: list[VerifierClaim] = []
        for raw_claim in raw_claims:
            if not isinstance(raw_claim, dict) or set(raw_claim) != _CLAIM_KEYS:
                raise VerifierFixtureError("claim has an invalid schema")
            raw_ids = raw_claim["evidence_ids"]
            if (
                not isinstance(raw_ids, list)
                or len(raw_ids) > MAX_EVIDENCE_SLICES
                or any(not isinstance(item, str) for item in raw_ids)
            ):
                raise VerifierFixtureError("claim evidence_ids must be a bounded string list")
            ids = tuple(raw_ids)
            if len(ids) != len(set(ids)) or not set(ids).issubset(evidence_ids):
                raise VerifierFixtureError("claim evidence_ids must be unique delegated IDs")
            expected = _label(raw_claim["expected_label"], "expected_label")
            if expected is ExpectedLabel.NO_EVIDENCE:
                raise VerifierFixtureError("claim labels cannot be no_evidence")
            claims.append(
                VerifierClaim(
                    _bounded_string(raw_claim["claim_id"], "claim_id", _MAX_ID_CHARS),
                    _bounded_string(raw_claim["text"], "claim text", MAX_TEXT_CHARS),
                    ids,
                    expected,
                )
            )
        if len({claim.claim_id for claim in claims}) != len(claims):
            raise VerifierFixtureError("claim IDs must be unique")
        if outcome is ExpectedLabel.NO_EVIDENCE:
            if evidence or claims:
                raise VerifierFixtureError("no_evidence cases must contain no evidence or claims")
        elif (
            not evidence
            or not claims
            or any(claim.expected_label is not outcome for claim in claims)
        ):
            raise VerifierFixtureError("evidence cases must contain consistently labelled claims")
        cases.append(VerifierBenchmarkCase(key, question, outcome, tuple(evidence), tuple(claims)))

    if len({case.key for case in cases}) != len(cases):
        raise VerifierFixtureError("case keys must be unique")
    fixture = VerifierBenchmarkFixture(
        _SCHEMA_VERSION, dataset_id, version, content_hash, tuple(cases)
    )
    if verifier_fixture_content_hash(fixture) != content_hash:
        raise VerifierFixtureError("fixture content hash does not match")
    return fixture


def measure_verifier_benefit(
    observations: tuple[VerificationObservation, ...],
    *,
    max_acceptable_false_reject_rate: float = 0.0,
) -> VerifierBenefitReport:
    """Compare observed deterministic baseline decisions with actual child verdicts.

    ``value_added`` is deliberately narrow: false support must strictly improve and
    the resulting false-reject rate must not exceed the caller's declared threshold.
    """

    if not 0.0 <= max_acceptable_false_reject_rate <= 1.0:
        raise ValueError("max_acceptable_false_reject_rate must be between zero and one")
    if not observations or len({(item.case_key, item.claim_id) for item in observations}) != len(
        observations
    ):
        raise ValueError("observations must have unique case and claim identities")

    claims = tuple(
        item for item in observations if item.expected_label is not ExpectedLabel.NO_EVIDENCE
    )
    supported_truth = tuple(
        item for item in claims if item.expected_label is ExpectedLabel.SUPPORTED
    )
    unsupported_truth = tuple(
        item for item in claims if item.expected_label is ExpectedLabel.UNSUPPORTED
    )
    delegated = tuple(item for item in claims if item.child_result is not None)
    delegated_results = {
        item.child_result.child_id: item.child_result
        for item in delegated
        if item.child_result is not None
    }

    def child_supported(item: VerificationObservation) -> bool:
        result = item.child_result
        if result is None:
            return item.baseline_supported
        return any(
            verdict.claim_id == item.claim_id and verdict.status is ClaimVerdictStatus.SUPPORTED
            for verdict in result.verdicts
        )

    baseline_false_supports = sum(item.baseline_supported for item in unsupported_truth)
    child_false_supports = sum(child_supported(item) for item in unsupported_truth)
    baseline_false_rejects = sum(not item.baseline_supported for item in supported_truth)
    child_false_rejects = sum(not child_supported(item) for item in supported_truth)
    baseline_false_support_rate = (
        baseline_false_supports / len(unsupported_truth) if unsupported_truth else 0.0
    )
    child_false_support_rate = (
        child_false_supports / len(unsupported_truth) if unsupported_truth else 0.0
    )
    baseline_false_reject_rate = (
        baseline_false_rejects / len(supported_truth) if supported_truth else 0.0
    )
    child_false_reject_rate = child_false_rejects / len(supported_truth) if supported_truth else 0.0
    costs = tuple(item.child_cost_usd for item in delegated)

    return VerifierBenefitReport(
        cases=len({item.case_key for item in observations}),
        evaluated_claims=len(claims),
        delegations=len(delegated_results),
        baseline_supported_count=sum(item.baseline_supported for item in claims),
        child_supported_count=sum(child_supported(item) for item in claims),
        baseline_false_support_rate=baseline_false_support_rate,
        child_false_support_rate=child_false_support_rate,
        baseline_false_reject_rate=baseline_false_reject_rate,
        child_false_reject_rate=child_false_reject_rate,
        beneficial_rejections=sum(
            item.baseline_supported and not child_supported(item) for item in unsupported_truth
        ),
        failures=sum(
            result.status is not ChildVerificationStatus.COMPLETED
            for result in delegated_results.values()
        ),
        escalations=sum(
            verdict.status is ClaimVerdictStatus.ESCALATE
            for result in delegated_results.values()
            for verdict in result.verdicts
        ),
        input_tokens=sum(result.usage.input_tokens for result in delegated_results.values()),
        output_tokens=sum(result.usage.output_tokens for result in delegated_results.values()),
        child_latency_ms=(
            sum(result.latency_ms for result in delegated_results.values())
            if delegated_results
            else None
        ),
        child_cost_usd=(
            sum(cost for cost in costs if cost is not None)
            if costs and all(cost is not None for cost in costs)
            else None
        ),
        unnecessary_delegation=sum(
            item.baseline_supported == child_supported(item)
            and (
                (item.expected_label is ExpectedLabel.SUPPORTED and item.baseline_supported)
                or (
                    item.expected_label is ExpectedLabel.UNSUPPORTED and not item.baseline_supported
                )
            )
            for item in delegated
        ),
        value_added=(
            child_false_support_rate < baseline_false_support_rate
            and child_false_reject_rate <= max_acceptable_false_reject_rate
        ),
    )
