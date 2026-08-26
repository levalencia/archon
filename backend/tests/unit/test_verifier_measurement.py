"""Unit tests for verifier benchmark fixture integrity and value semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.delegation.measurement import (
    ExpectedLabel,
    VerificationObservation,
    VerifierFixtureError,
    load_verifier_benchmark_fixture,
    measure_verifier_benefit,
    verifier_fixture_content_hash,
)
from app.delegation.models import (
    ChildVerificationResult,
    ChildVerificationStatus,
    ClaimVerdict,
    ClaimVerdictStatus,
    VerificationReasonCode,
)
from app.runtime.models import TokenUsage

_FIXTURE = Path("tests/fixtures/evals/verifier-benefit-v1.json")
_HASH = "cddf2eb127330e64f96b3e27d6e7e1dabfb9f35b864799a4dd5cac3365350257"


def _result(claim_id: str, status: ClaimVerdictStatus) -> ChildVerificationResult:
    reason = (
        VerificationReasonCode.EVIDENCE_SUPPORTS
        if status is ClaimVerdictStatus.SUPPORTED
        else VerificationReasonCode.EVIDENCE_CONTRADICTS
    )
    return ChildVerificationResult(
        "child-1",
        "parent-1",
        ChildVerificationStatus.COMPLETED,
        TokenUsage(2, 1),
        1.5,
        (ClaimVerdict(claim_id, status, reason, 1.0, ("E1",)),),
    )


def test_verifier_benefit_fixture_has_stable_verified_hash_and_required_cases() -> None:
    fixture = load_verifier_benchmark_fixture(_FIXTURE)
    assert fixture.schema_version == 1
    assert fixture.version == "1.0.0"
    assert fixture.content_hash == _HASH
    assert verifier_fixture_content_hash(fixture) == _HASH
    assert {case.expected_outcome for case in fixture.cases} == set(ExpectedLabel)


def test_verifier_fixture_rejects_schema_hash_and_bounds(tmp_path: Path) -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    mutations = (
        ("schema", lambda item: item.update({"extra": True}), "top-level schema"),
        ("hash", lambda item: item["cases"][0].update({"question": "changed"}), "content hash"),
        (
            "bound",
            lambda item: item["cases"][0]["claims"][0].update({"text": "x" * 1_001}),
            "claim text",
        ),
    )
    for name, mutate, message in mutations:
        changed = json.loads(json.dumps(raw))
        mutate(changed)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(VerifierFixtureError, match=message):
            load_verifier_benchmark_fixture(path)


def test_value_added_requires_improvement_without_false_rejects() -> None:
    observations = (
        VerificationObservation(
            "unsupported",
            ExpectedLabel.UNSUPPORTED,
            "C1",
            True,
            _result("C1", ClaimVerdictStatus.REJECTED),
        ),
        VerificationObservation(
            "supported",
            ExpectedLabel.SUPPORTED,
            "C2",
            True,
            _result("C2", ClaimVerdictStatus.REJECTED),
        ),
    )
    report = measure_verifier_benefit(observations)
    assert report.baseline_false_support_rate == 1.0
    assert report.child_false_support_rate == 0.0
    assert report.child_false_reject_rate == 1.0
    assert report.value_added is False
    assert (
        measure_verifier_benefit(observations, max_acceptable_false_reject_rate=1.0).value_added
        is True
    )
