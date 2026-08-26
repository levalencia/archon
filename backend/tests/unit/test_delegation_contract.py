"""Tests for bounded verifier-child contracts and ledger-safe event schemas."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from typing import Any, cast

import pytest

from app.delegation import (
    MAX_CLAIMS,
    MAX_INPUT_TOKENS,
    ChildVerificationRequest,
    ChildVerificationResult,
    ChildVerificationStatus,
    ClaimInput,
    ClaimVerdict,
    ClaimVerdictStatus,
    EvidenceSlice,
    VerificationBudget,
    VerificationReasonCode,
    validate_verdict_evidence_subset,
)
from app.runtime.events import AgentEventKind
from app.runtime.models import TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.run_ledger import safe_event_payload

HASH = "a" * 64


def evidence(number: int = 1, *, quote: str = "source") -> EvidenceSlice:
    return EvidenceSlice(f"ev-{number}", "doc-1", f"chunk-{number}", HASH, quote)


def claim(number: int = 1, *, text: str = "claim") -> ClaimInput:
    return ClaimInput(f"claim-{number}", HASH, text, ("ev-1",))


def request(**changes: Any) -> ChildVerificationRequest:
    values: dict[str, Any] = {
        "child_id": "child-1",
        "parent_run_id": "parent-1",
        "user_id": "user-1",
        "project_id": "project-1",
        "policy_id": "policy-1",
        "model": "model-1",
        "claims": (claim(),),
        "evidence": (evidence(),),
        "budget": VerificationBudget(100, 20, 1.0),
    }
    values.update(changes)
    return ChildVerificationRequest(**values)


def test_models_are_frozen_slotted_and_exclude_context_and_secrets() -> None:
    item = evidence()
    with pytest.raises(FrozenInstanceError):
        item.quote = "changed"
    assert not hasattr(item, "__dict__")
    request_fields = {item.name for item in fields(ChildVerificationRequest)}
    assert request_fields.isdisjoint({"context", "general_context", "secret", "api_key"})
    assert request().tools == ()
    with pytest.raises(ValueError, match="cannot receive tools"):
        request(tools=("web_search",))


def test_exact_identifier_hash_and_text_bounds() -> None:
    EvidenceSlice("ev-1", "doc-1", "chunk-1", HASH, "q" * 1_000)
    ClaimInput("claim-1", HASH, "c" * 1_000, ("ev-1",))
    with pytest.raises(ValueError):
        EvidenceSlice("unsafe/id", "doc-1", "chunk-1", HASH, "quote")
    with pytest.raises(ValueError):
        EvidenceSlice("ev-1", "doc-1", "chunk-1", "A" * 64, "quote")
    with pytest.raises(ValueError):
        evidence(quote="q" * 1_001)
    with pytest.raises(ValueError):
        claim(text="c" * 1_001)


def test_budget_and_request_bounds() -> None:
    VerificationBudget(MAX_INPUT_TOKENS, 1, 0.1, retries=1)
    for budget in (
        (0, 1, 1.0, 0),
        (1, 0, 1.0, 0),
        (1, 1, 0.09, 0),
        (1, 1, 60.01, 0),
        (1, 1, 1.0, 2),
    ):
        with pytest.raises(ValueError):
            VerificationBudget(*budget)
    with pytest.raises(ValueError):
        request(claims=tuple(claim(i) for i in range(1, MAX_CLAIMS + 2)))
    with pytest.raises(ValueError, match="delegated evidence"):
        request(claims=(ClaimInput("claim-1", HASH, "claim", ("foreign",)),))


def test_verdict_confidence_enum_and_separate_evidence_subset_validation() -> None:
    verdict = ClaimVerdict(
        "claim-1",
        ClaimVerdictStatus.SUPPORTED,
        VerificationReasonCode.EVIDENCE_SUPPORTS,
        1.0,
        ("ev-1",),
    )
    validate_verdict_evidence_subset((verdict,), ("ev-1",))
    with pytest.raises(ValueError, match="delegated evidence"):
        validate_verdict_evidence_subset((verdict,), ("ev-2",))
    for confidence in (float("nan"), float("inf"), -0.01, 1.01):
        with pytest.raises(ValueError):
            ClaimVerdict(
                "claim-1",
                ClaimVerdictStatus.SUPPORTED,
                VerificationReasonCode.EVIDENCE_SUPPORTS,
                confidence,
            )
    with pytest.raises(ValueError):
        ClaimVerdict(
            "claim-1",
            cast(ClaimVerdictStatus, "unknown"),
            VerificationReasonCode.EVIDENCE_SUPPORTS,
            0.5,
        )


def test_result_is_bounded_and_typed() -> None:
    verdict = ClaimVerdict(
        "claim-1",
        ClaimVerdictStatus.REJECTED,
        VerificationReasonCode.EVIDENCE_CONTRADICTS,
        0.8,
    )
    result = ChildVerificationResult(
        "child-1",
        "parent-1",
        ChildVerificationStatus.COMPLETED,
        TokenUsage(10, 2),
        3.5,
        (verdict,),
    )
    assert result.latency_ms == 3.5
    with pytest.raises(ValueError):
        ChildVerificationResult(
            "child-1",
            "parent-1",
            ChildVerificationStatus.COMPLETED,
            TokenUsage(),
            float("nan"),
            (),
        )


def test_delegation_event_payload_drops_text_quotes_context_and_secrets() -> None:
    for kind in (AgentEventKind.DELEGATION_REQUESTED, AgentEventKind.DELEGATION_COMPLETED):
        payload = safe_event_payload(
            kind.value,
            {
                "child_id": "child-1",
                "parent_run_id": "parent-1",
                "claim_hashes": [HASH],
                "evidence_ids": ["ev-1"],
                "claim_count": 1,
                "status": "completed",
                "reason_code": "evidence_supports",
                "input_tokens": 10,
                "output_tokens": 2,
                "text": "sensitive claim",
                "quote": "sensitive quote",
                "context": "general context",
                "secret": "top-secret",
                "api_key": "sk-secret",
            },
            PersistenceRedactor(),
        )
        assert payload["child_id"] == "child-1"
        assert payload["input_tokens"] == 10
        assert set(payload).isdisjoint({"text", "quote", "context", "secret", "api_key"})
