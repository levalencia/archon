"""Grounded document workflow acceptance tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.runtime.models import ModelResponse, TokenUsage
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import DocumentChunk
from app.services.db_store import DatabaseStore, RuntimeEventRow
from app.services.grounded_rag import GroundedDocumentWorkflow, GroundedProviderError
from app.services.run_ledger import RunRepository


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
) -> tuple[Any, FakeVectors]:
    vectors = FakeVectors(rows)
    workflow = GroundedDocumentWorkflow(
        vector_store=vectors,  # type: ignore[arg-type]
        embedding_service=FakeEmbeddings(),  # type: ignore[arg-type]
        model_provider=provider,
        runs=harness.runs,
        provider="fake-provider",
        model="fake-model",
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
