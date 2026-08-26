"""Grounded document workflow acceptance tests."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select, update

from app.delegation import EvidenceVerifierSpecialist, VerificationBudget
from app.research.models import Claim
from app.runtime.models import ModelResponse, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import DocumentChunk
from app.services.db_store import DatabaseStore, RuntimeEventRow, VectorChunkRow
from app.services.grounded_rag import (
    DocumentEvidence,
    GroundedDocumentWorkflow,
    GroundedProviderError,
    _verify_document_claims,
)
from app.services.run_ledger import RunRepository
from app.services.sql_json_vector_store import SqlJsonVectorStore


class FakeEmbeddings:
    async def embed(self, text: str) -> list[float]:
        del text
        return [1.0, 0.0]


class FakeVectors:
    backend = "fake"

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.searches: list[dict[str, Any]] = []

    async def search(self, query_embedding: list[float], **kwargs: Any) -> list[dict[str, Any]]:
        self.searches.append({"query_embedding": query_embedding, **kwargs})
        return self.rows


class FakeProvider:
    def __init__(self, content: str, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail
        self.calls = 0
        self.messages: Any = None

    async def complete(self, messages: Any, tools: Any = (), **kwargs: Any) -> Any:
        del tools, kwargs
        self.calls += 1
        self.messages = messages
        if self.fail:
            raise RuntimeError("provider leaked response")
        if not self.content:
            return SimpleNamespace(content="", usage=TokenUsage())
        return ModelResponse(
            self.content,
            usage=TokenUsage(input_tokens=11, output_tokens=7),
        )


@dataclass
class Harness:
    store: DatabaseStore
    runs: RunRepository


@pytest.fixture
async def harness(tmp_path: Any) -> Any:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'grounded.db'}")
    await store.initialize()
    yield Harness(store, RunRepository(store.session_factory, PersistenceRedactor()))
    await store.close()


def _row(
    *,
    content: str = "Alpha project uses Python for data analysis.",
    chunk_id: str = "chunk-1",
    document_id: str = "doc-1",
    score: float = 0.9,
) -> dict[str, Any]:
    return {
        "chunk": DocumentChunk(
            id=chunk_id,
            document_id=document_id,
            content=content,
            chunk_index=0,
            metadata={"title": "Project notes"},
            embedding=[1.0, 0.0],
        ),
        "score": score,
    }


async def _run(
    harness: Harness,
    provider: FakeProvider,
    rows: list[dict[str, Any]],
    *,
    owner: str = "alice",
    project: str = "project-a",
    verifier_provider: FakeProvider | None = None,
) -> tuple[Any, FakeVectors]:
    vectors = FakeVectors(rows)
    verifier = (
        EvidenceVerifierSpecialist(verifier_provider, harness.runs, PersistenceRedactor())
        if verifier_provider is not None
        else None
    )
    workflow = GroundedDocumentWorkflow(
        vector_store=vectors,  # type: ignore[arg-type]
        embedding_service=FakeEmbeddings(),  # type: ignore[arg-type]
        model_provider=provider,
        runs=harness.runs,
        provider="fake-provider",
        model="fake-model",
        verifier=verifier,
        verifier_budget=VerificationBudget(4_000, 500, 1.0) if verifier is not None else None,
    )
    result = await workflow.run(
        "What does Alpha use?",
        owner_id=owner,
        project_id=project,
        correlation_id="correlation",
        document_id=None,
        document_ids={"doc-1"},
    )
    return result, vectors


@pytest.mark.asyncio
async def test_supported_claim_is_answered_with_verified_citation(harness: Harness) -> None:
    provider = FakeProvider(
        json.dumps({"claims": [{"text": "Alpha project uses Python", "evidence_ids": ["E1"]}]})
    )
    result, _ = await _run(harness, provider, [_row()])
    assert result.grounded is True
    assert result.answer == "Alpha project uses Python [E1]"
    assert result.claims == ({"text": "Alpha project uses Python", "evidence_ids": ["E1"]},)
    assert result.citations[0]["content_hash"]
    assert provider.calls == 1
    assert "Return JSON only" in provider.messages[0].content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "grounded", "rejected"),
    [
        (
            {
                "claim_id": "C1",
                "status": "supported",
                "reason_code": "evidence_supports",
                "confidence": 0.95,
                "evidence_ids": ["E1"],
            },
            True,
            0,
        ),
        (
            {
                "claim_id": "C1",
                "status": "rejected",
                "reason_code": "evidence_contradicts",
                "confidence": 0.8,
                "evidence_ids": ["E1"],
            },
            False,
            1,
        ),
    ],
)
async def test_enabled_verifier_filters_and_records_child_lineage(
    harness: Harness, verdict: dict[str, Any], grounded: bool, rejected: int
) -> None:
    parent = FakeProvider(
        json.dumps({"claims": [{"text": "Alpha project uses Python", "evidence_ids": ["E1"]}]})
    )
    child = FakeProvider(json.dumps({"verdicts": [verdict]}))
    result, _ = await _run(harness, parent, [_row()], verifier_provider=child)

    assert result.grounded is grounded
    assert result.verification_status == "completed"
    assert result.verification_tokens == 18
    assert result.verification_rejected_count == rejected
    assert result.child_run_id is not None
    assert child.calls == 1
    child_input = child.messages[1].content
    assert "Alpha project uses Python" in child_input
    assert "Alpha project uses Python for data analysis" in child_input
    assert "What does Alpha use?" not in child_input

    restarted = RunRepository(harness.store.session_factory, PersistenceRedactor())
    child_run = await restarted.get("alice", result.child_run_id)
    children = await restarted.list_children("alice", result.run_id)
    parent_events = await restarted.events("alice", result.run_id)
    assert child_run is not None and child_run.parent_run_id == result.run_id
    assert [item.run_id for item in children.items] == [result.child_run_id]
    assert (await restarted.list_children("mallory", result.run_id)).items == ()
    assert parent_events is not None
    delegation = next(item for item in parent_events.items if item.kind == "delegation_completed")
    assert set(delegation.payload) == {"child_id", "status", "supported_count", "rejected_count"}


@pytest.mark.asyncio
async def test_verifier_failure_fails_closed_and_no_evidence_never_delegates(
    harness: Harness,
) -> None:
    parent = FakeProvider(
        json.dumps({"claims": [{"text": "Alpha project uses Python", "evidence_ids": ["E1"]}]})
    )
    malformed = FakeProvider("not-json")
    result, _ = await _run(harness, parent, [_row()], verifier_provider=malformed)
    assert result.claims == ()
    assert result.unsupported == ("Alpha project uses Python",)
    assert result.verification_status == "failed"
    assert result.verification_rejected_count == 1

    unused = FakeProvider("must not be called")
    empty, _ = await _run(harness, FakeProvider("must not be called"), [], verifier_provider=unused)
    assert empty.child_run_id is None
    assert empty.verification_status is None
    assert unused.calls == 0


@pytest.mark.asyncio
async def test_disabled_verifier_preserves_prior_result_shape_defaults(harness: Harness) -> None:
    parent = FakeProvider(
        json.dumps({"claims": [{"text": "Alpha project uses Python", "evidence_ids": ["E1"]}]})
    )
    result, _ = await _run(harness, parent, [_row()])
    assert result.grounded is True
    assert result.child_run_id is None
    assert result.verification_status is None
    assert result.verification_tokens == 0
    assert result.verification_rejected_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claims", "supported", "unsupported"),
    [
        (
            [
                {"text": "Alpha project uses Python", "evidence_ids": ["E1"]},
                {"text": "The moon is green", "evidence_ids": ["E1"]},
            ],
            1,
            ("The moon is green",),
        ),
        (
            [{"text": "Alpha project uses Python", "evidence_ids": ["E99"]}],
            0,
            ("Alpha project uses Python",),
        ),
        (
            [{"text": "Alpha project uses Python", "evidence_ids": []}],
            0,
            ("Alpha project uses Python",),
        ),
    ],
)
async def test_partial_unknown_and_missing_citations_are_unsupported(
    harness: Harness, claims: list[dict[str, Any]], supported: int, unsupported: tuple[str, ...]
) -> None:
    result, _ = await _run(harness, FakeProvider(json.dumps({"claims": claims})), [_row()])
    assert len(result.claims) == supported
    assert result.unsupported == unsupported
    assert "moon" not in result.answer.lower()


@pytest.mark.asyncio
async def test_duplicate_results_are_deduplicated(harness: Harness) -> None:
    provider = FakeProvider(
        '{"claims":[{"text":"Alpha project uses Python","evidence_ids":["E1"]}]}'
    )
    row = _row()
    result, _ = await _run(
        harness, provider, [row, row, _row(chunk_id="chunk-duplicate", score=0.8)]
    )
    assert result.chunks_retrieved == 1
    assert [item["id"] for item in result.citations] == ["E1"]


@pytest.mark.asyncio
async def test_no_evidence_has_standard_response_and_no_provider_call(harness: Harness) -> None:
    provider = FakeProvider("must not be used")
    result, vectors = await _run(harness, provider, [])
    assert result.answer == "I could not find relevant information to answer your question."
    assert result.metrics["provider_calls"] == 0
    assert result.grounded is False
    assert provider.calls == 0
    assert vectors.searches[0]["owner_id"] == "alice"
    assert vectors.searches[0]["project_id"] == "project-a"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("column", "raw_value"),
    [
        ("content", "RAW_STALE_EVIDENCE_SECRET"),
        ("content_hash", "RAW_INVALID_HASH_SECRET"),
    ],
)
async def test_tampered_persisted_evidence_is_skipped_before_provider_call(
    harness: Harness, column: str, raw_value: str
) -> None:
    vectors = SqlJsonVectorStore(harness.store.session_factory, dimensions=2)
    await vectors.add_chunks(
        [DocumentChunk("chunk-1", "doc-1", "trusted content", 0, embedding=[1.0, 0.0])],
        owner_id="alice",
        project_id="project-a",
    )
    async with harness.store.session_factory.begin() as session:
        await session.execute(
            update(VectorChunkRow)
            .where(VectorChunkRow.id == "chunk-1")
            .values(**{column: raw_value})
        )
    provider = FakeProvider("must not be used")
    workflow = GroundedDocumentWorkflow(
        vector_store=vectors,
        embedding_service=FakeEmbeddings(),  # type: ignore[arg-type]
        model_provider=provider,
        runs=harness.runs,
        provider="fake-provider",
        model="fake-model",
    )

    with patch("app.services.sql_json_vector_store.logger.warning") as warning:
        result = await workflow.run(
            "What does Alpha use?",
            owner_id="alice",
            project_id="project-a",
            correlation_id="correlation",
            document_id=None,
            document_ids={"doc-1"},
        )

    assert result.chunks_retrieved == 0
    assert result.metrics["provider_calls"] == 0
    assert provider.calls == 0
    warning.assert_called_once_with("corrupt_vector_row_skipped")
    assert raw_value not in repr(warning.call_args_list)


@pytest.mark.asyncio
async def test_empty_model_output_is_safe_and_bounded(harness: Harness) -> None:
    provider = FakeProvider("")
    result, _ = await _run(harness, provider, [_row()])
    assert provider.calls == 1
    assert result.claims == ()
    assert result.grounded is False
    assert result.answer == "I could not find relevant information to answer your question."


@pytest.mark.asyncio
async def test_provider_failure_finalizes_failed_run(harness: Harness) -> None:
    provider = FakeProvider("unused", fail=True)
    with pytest.raises(GroundedProviderError):
        await _run(harness, provider, [_row()])
    page = await harness.runs.list("alice")
    run = page.items[0]
    assert run.status == "failed"
    assert run.provider == "fake-provider"
    assert run.model == "fake-model"
    assert run.stop_reason == "provider_error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("claim_text", "evidence_text", "supported"),
    [
        ("Alpha uses Python", "Alpha does not use Python", False),
        ("Alpha does not use Python", "Alpha uses Python", False),
        ("Alpha doesn't use Python", "Alpha does not use Python", True),
        ("Alpha uses Python 3", "Alpha uses Python 2", False),
        ("Alpha uses Python 3", "Alpha uses Python 3 for data analysis", True),
        ("Alpha uses Python and Rust", "Alpha uses Python", False),
    ],
)
async def test_claim_support_is_conservative_about_negation_numbers_and_partial_claims(
    claim_text: str, evidence_text: str, supported: bool
) -> None:
    chunk = DocumentChunk("chunk", "doc", evidence_text, 0)
    evidence = (
        DocumentEvidence(
            "E1",
            "doc",
            "chunk",
            chunk.content_hash,
            "title",
            1.0,
            evidence_text,
            evidence_text,
        ),
    )
    accepted, _, unsupported = await _verify_document_claims(
        (Claim(claim_text, ("E1",)),), evidence
    )
    assert bool(accepted) is supported
    assert bool(unsupported) is not supported


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["embedding", "vector"])
async def test_retrieval_failure_finalizes_failed_run_after_restart(
    harness: Harness, failure_stage: str
) -> None:
    class FailingEmbeddings:
        async def embed(self, text: str) -> list[float]:
            del text
            if failure_stage == "embedding":
                raise RuntimeError("secret embedding failure")
            return [1.0, 0.0]

    class FailingVectors(FakeVectors):
        async def search(self, query_embedding: list[float], **kwargs: Any) -> list[dict[str, Any]]:
            del query_embedding, kwargs
            raise RuntimeError("secret vector failure")

    workflow = GroundedDocumentWorkflow(
        vector_store=FailingVectors([]),  # type: ignore[arg-type]
        embedding_service=FailingEmbeddings(),  # type: ignore[arg-type]
        model_provider=FakeProvider("unused"),
        runs=harness.runs,
        provider="fake-provider",
        model="fake-model",
    )
    with pytest.raises(GroundedProviderError, match="Grounded answer unavailable"):
        await workflow.run(
            "private question",
            owner_id="alice",
            project_id="project-a",
            correlation_id="correlation",
            document_id=None,
            document_ids={"doc-1"},
        )
    restarted = RunRepository(harness.store.session_factory, PersistenceRedactor())
    run = (await restarted.list("alice")).items[0]
    events = await restarted.events("alice", run.run_id)
    assert run.status == "failed"
    assert run.stop_reason == "provider_error"
    assert events is not None and events.items[-1].kind == "run_stopped"
    assert "secret" not in json.dumps(events.items[-1].payload)


@pytest.mark.asyncio
async def test_cancellation_finalizes_cancelled_run_and_reraises(harness: Harness) -> None:
    started = asyncio.Event()

    class BlockingEmbeddings:
        async def embed(self, text: str) -> list[float]:
            del text
            started.set()
            await asyncio.Event().wait()
            return [1.0, 0.0]

    workflow = GroundedDocumentWorkflow(
        vector_store=FakeVectors([]),  # type: ignore[arg-type]
        embedding_service=BlockingEmbeddings(),  # type: ignore[arg-type]
        model_provider=FakeProvider("unused"),
        runs=harness.runs,
        provider="fake-provider",
        model="fake-model",
    )
    task = asyncio.create_task(
        workflow.run(
            "question",
            owner_id="alice",
            project_id="project-a",
            correlation_id="correlation",
            document_id=None,
            document_ids=set(),
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    run = (await harness.runs.list("alice")).items[0]
    assert run.status == "cancelled"
    assert run.stop_reason == "cancelled"


@pytest.mark.asyncio
async def test_owner_scope_restart_ledger_and_no_raw_database_content(harness: Harness) -> None:
    quote = "Alpha project uses Python for private-roadmap analysis."
    answer = "Alpha project uses Python"
    provider = FakeProvider(json.dumps({"claims": [{"text": answer, "evidence_ids": ["E1"]}]}))
    result, vectors = await _run(harness, provider, [_row(content=quote)])
    assert vectors.searches[0]["document_ids"] == {"doc-1"}
    assert await harness.runs.get("mallory", result.run_id) is None

    restarted = RunRepository(harness.store.session_factory, PersistenceRedactor())
    events = await restarted.events("alice", result.run_id)
    run = await restarted.get("alice", result.run_id)
    assert events is not None and run is not None
    assert run.status == "completed"
    assert (run.input_tokens, run.output_tokens, run.total_tokens) == (11, 7, 18)
    assert [item.kind for item in events.items] == [
        "evidence_retrieved",
        "claim_verified",
        "grounded_answer",
        "run_stopped",
    ]
    assert all(
        "quote" not in item.payload and "answer" not in item.payload for item in events.items
    )

    async with harness.store.session_factory() as session:
        payloads = list((await session.scalars(select(RuntimeEventRow.payload))).all())
    raw = "\n".join(payloads)
    assert quote not in raw
    assert answer not in raw
    assert "private-roadmap" not in raw
