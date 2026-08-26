"""Executable baseline-versus-verifier benefit benchmark."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.delegation.measurement import (
    ExpectedLabel,
    VerificationObservation,
    load_verifier_benchmark_fixture,
    measure_verifier_benefit,
)
from app.delegation.models import (
    ChildVerificationRequest,
    ClaimInput,
    EvidenceSlice,
    VerificationBudget,
)
from app.delegation.service import EvidenceVerifierSpecialist
from app.research.models import Claim
from app.runtime.models import ModelResponse, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore
from app.services.grounded_rag import DocumentEvidence, _verify_document_claims
from app.services.run_ledger import RunRepository

_FIXTURE = Path("tests/fixtures/evals/verifier-benefit-v1.json")
_HASH = "cddf2eb127330e64f96b3e27d6e7e1dabfb9f35b864799a4dd5cac3365350257"


class FixedVerifierProvider:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    async def complete(self, messages: Any, tools: Any = (), **kwargs: Any) -> ModelResponse:
        del messages, tools, kwargs
        self.calls += 1
        return ModelResponse(self._content, usage=TokenUsage(input_tokens=7, output_tokens=3))


def _document_evidence(case: Any) -> tuple[DocumentEvidence, ...]:
    return tuple(
        DocumentEvidence(
            id=item.evidence_id,
            document_id=item.document_id,
            chunk_id=item.chunk_id,
            content_hash=hashlib.sha256(item.quote.encode()).hexdigest()[:16],
            title="Benchmark fixture",
            score=1.0,
            quote=item.quote,
            verification_text=item.quote,
        )
        for item in case.evidence
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_versioned_fixture_measures_verifier_value_and_lineage(tmp_path: Path) -> None:
    fixture = load_verifier_benchmark_fixture(_FIXTURE)
    assert fixture.content_hash == _HASH

    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'verifier-benefit.db'}")
    await store.initialize()
    try:
        runs = RunRepository(store.session_factory, PersistenceRedactor())
        observations: list[VerificationObservation] = []
        for case in fixture.cases:
            evidence = _document_evidence(case)
            claims = tuple(Claim(item.text, item.evidence_ids) for item in case.claims)
            baseline_claims, _, _ = await _verify_document_claims(claims, evidence)

            if case.expected_outcome is ExpectedLabel.NO_EVIDENCE:
                # No request can be constructed without evidence, so delegation is skipped.
                assert evidence == ()
                assert claims == ()
                observations.append(
                    VerificationObservation(case.key, case.expected_outcome, None, False, None)
                )
                continue

            claim = case.claims[0]
            verdict = {
                "claim_id": claim.claim_id,
                "status": (
                    "supported" if claim.expected_label is ExpectedLabel.SUPPORTED else "rejected"
                ),
                "reason_code": (
                    "evidence_supports"
                    if claim.expected_label is ExpectedLabel.SUPPORTED
                    else "evidence_contradicts"
                ),
                "confidence": 1.0,
                "evidence_ids": list(claim.evidence_ids),
            }
            provider = FixedVerifierProvider(json.dumps({"verdicts": [verdict]}))
            parent_id = f"parent-{case.key}"
            child_id = f"child-{case.key}"
            await runs.ensure_run(
                run_id=parent_id,
                user_id="benchmark-user",
                project_id="benchmark-project",
                conversation_id="verifier-benefit-v1",
                correlation_id=parent_id,
                provider="benchmark-parent",
                model="fixture-parent-v1",
            )
            request = ChildVerificationRequest(
                child_id=child_id,
                parent_run_id=parent_id,
                user_id="benchmark-user",
                project_id="benchmark-project",
                policy_id="grounded-evidence-v1",
                model="fixture-verifier-v1",
                claims=(
                    ClaimInput(
                        claim.claim_id,
                        hashlib.sha256(claim.text.encode()).hexdigest(),
                        claim.text,
                        claim.evidence_ids,
                    ),
                ),
                evidence=tuple(
                    EvidenceSlice(
                        item.id,
                        item.document_id,
                        item.chunk_id,
                        hashlib.sha256(item.verification_text.encode()).hexdigest(),
                        item.quote,
                    )
                    for item in evidence
                ),
                budget=VerificationBudget(4_000, 500, 1.0),
            )
            child_result = await EvidenceVerifierSpecialist(
                provider, runs, PersistenceRedactor()
            ).verify(request)

            assert provider.calls == 1
            assert child_result.parent_run_id == parent_id
            children = await runs.list_children("benchmark-user", parent_id)
            assert tuple(item.run_id for item in children.items) == (child_id,)
            observations.append(
                VerificationObservation(
                    case.key,
                    claim.expected_label,
                    claim.claim_id,
                    any(item.text == claim.text for item in baseline_claims),
                    child_result,
                )
            )

        report = measure_verifier_benefit(tuple(observations))
        assert report.cases == 3
        assert report.evaluated_claims == 2
        assert report.delegations == 2
        assert report.baseline_supported_count == 2
        assert report.child_supported_count == 1
        assert report.baseline_false_support_rate == 1.0
        assert report.child_false_support_rate == 0.0
        assert report.baseline_false_reject_rate == 0.0
        assert report.child_false_reject_rate == 0.0
        assert report.beneficial_rejections == 1
        assert report.failures == 0
        assert report.escalations == 0
        assert report.input_tokens == 14
        assert report.output_tokens == 6
        assert report.child_latency_ms is not None and report.child_latency_ms >= 0.0
        assert report.child_cost_usd is None
        assert report.unnecessary_delegation == 1
        assert report.value_added is True
    finally:
        await store.close()
