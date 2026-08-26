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
from app.runtime.models import Message, ModelResponse, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore
from app.services.grounded_rag import DocumentEvidence, _verify_document_claims
from app.services.run_ledger import RunRepository

_FIXTURE = Path("tests/fixtures/evals/verifier-benefit-v1.json")
_FIXTURE_HASH = "8b1c7e420932d4640c275d0a1bab5c680f5b4ee9d320d15274a5346e72d169ea"
_OUTPUTS = Path("tests/fixtures/evals/verifier-provider-outputs-v1.json")
_OUTPUTS_HASH = "574828fe8ef6a9db4b1b8d476684567a272972375b507e72a180fae6b6e8acb0"


class FixedVerifierProvider:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[tuple[Message, ...]] = []

    async def complete(self, messages: Any, tools: Any = (), **kwargs: Any) -> ModelResponse:
        del tools, kwargs
        self.calls.append(tuple(messages))
        return ModelResponse(self._content, usage=TokenUsage(input_tokens=7, output_tokens=3))


def _load_independent_outputs(path: Path) -> dict[str, str]:
    """Load immutable raw model outputs without accepting benchmark labels as input."""
    raw_bytes = path.read_bytes()
    assert b"expected_label" not in raw_bytes
    raw = json.loads(raw_bytes)
    assert set(raw) == {"schema_version", "dataset_id", "content_hash", "outputs"}
    declared_hash = raw.pop("content_hash")
    actual_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert declared_hash == actual_hash == _OUTPUTS_HASH
    assert raw["schema_version"] == 1
    return {
        case_key: json.dumps(output, sort_keys=True, separators=(",", ":"))
        for case_key, output in raw["outputs"].items()
    }


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
    outputs = _load_independent_outputs(_OUTPUTS)
    assert fixture.content_hash == _FIXTURE_HASH
    assert set(outputs) == {case.key for case in fixture.cases if case.claims}

    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'verifier-benefit.db'}")
    await store.initialize()
    try:
        runs = RunRepository(store.session_factory, PersistenceRedactor())
        observations: list[VerificationObservation] = []
        for case in fixture.cases:
            evidence = _document_evidence(case)
            claims = tuple(Claim(item.text, item.evidence_ids) for item in case.claims)
            baseline_claims, _, _ = await _verify_document_claims(claims, evidence)

            if not case.claims:
                assert case.expected_outcome is ExpectedLabel.NO_EVIDENCE
                observations.append(
                    VerificationObservation(case.key, case.expected_outcome, None, False, None)
                )
                continue

            provider = FixedVerifierProvider(outputs[case.key])
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
                claims=tuple(
                    ClaimInput(
                        claim.claim_id,
                        hashlib.sha256(claim.text.encode()).hexdigest(),
                        claim.text,
                        claim.evidence_ids,
                    )
                    for claim in case.claims
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

            assert len(provider.calls) == 1
            prompt = "\n".join(message.content for message in provider.calls[0])
            assert "expected_label" not in prompt
            assert child_result.parent_run_id == parent_id
            persisted_child = await runs.get("benchmark-user", child_id)
            assert persisted_child is not None and persisted_child.parent_run_id == parent_id

            # Ground truth is consulted only after the independent provider result exists.
            for claim in case.claims:
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
        assert report.evaluated_claims == 4
        assert report.delegations == 2
        assert report.baseline_supported_count == 3
        assert report.child_supported_count == 2
        assert report.baseline_false_support_rate == 0.5
        assert report.child_false_support_rate == 0.0
        assert report.baseline_false_reject_rate == 0.0
        assert report.child_false_reject_rate == 0.0
        assert report.beneficial_rejections == 1
        assert report.failures == 0
        assert report.escalations == 1
        assert report.input_tokens == 14
        assert report.output_tokens == 6
        assert report.child_latency_ms is not None and report.child_latency_ms >= 0.0
        assert report.child_cost_usd is None
        assert report.unnecessary_delegation == 3
        assert report.value_added is True
    finally:
        await store.close()
