"""Tests for concept-aware retrieval reranking and score diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.learning_tutor.repository import (
    LearningEvidence,
    LearningKnowledgeRepository,
    _expand_query,
)
from app.learning_tutor.sources import LearningSourceInput
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import EmbeddingService
from app.services.db_store import DatabaseStore


@pytest.fixture
async def knowledge(tmp_path: Path):
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'diag.db'}")
    await store.initialize()
    repo = LearningKnowledgeRepository(
        store.session_factory,
        EmbeddingService(provider="mock", dimensions=32),
        PersistenceRedactor(),
    )
    try:
        yield repo
    finally:
        await store.close()


_REV = "a" * 40


def _concept_sources() -> list[LearningSourceInput]:
    """Sources covering OOP, DI, factory, preflight, observability, policy, RAG, SSE, chunking."""
    return [
        LearningSourceInput(
            kind="documentation",
            key="docs/oop.md#oop",
            title="Object-Oriented Programming",
            text=(
                "Object-oriented programming (OOP) organises code into classes and objects. "
                "Each class encapsulates data and behaviour."
            ),
            revision=_REV,
            locator={"path": "docs/oop.md", "line_start": 1, "line_end": 5},
            context_keys=("concept:oop",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/di.md#dependency-injection",
            title="Dependency Injection",
            text=(
                "Dependency injection (DI) is a design pattern where objects receive their "
                "dependencies from the outside rather than creating them internally."
            ),
            revision=_REV,
            locator={"path": "docs/di.md", "line_start": 1, "line_end": 5},
            context_keys=("concept:di",),
        ),
        LearningSourceInput(
            kind="code",
            key="backend/app/factory.py#create_app",
            title="factory.py — create_app",
            text="def create_app():\n    app = FastAPI()\n    return app",
            revision=_REV,
            locator={
                "path": "backend/app/factory.py",
                "symbol": "create_app",
                "line_start": 1,
                "line_end": 3,
            },
            context_keys=("concept:factory",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/preflight.md#preflight-checks",
            title="Preflight Checks",
            text=(
                "A preflight check validates configuration and external service connectivity "
                "before startup."
            ),
            revision=_REV,
            locator={"path": "docs/preflight.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:preflight",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/observability.md#observability",
            title="Observability",
            text=(
                "Observability exposes metrics, tracing, and structured logging for production "
                "insight."
            ),
            revision=_REV,
            locator={"path": "docs/observability.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:observability",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/policy.md#security-policy",
            title="Security Policy",
            text=(
                "A policy in Cogentrex defines permission rules that restrict agent tool execution."
            ),
            revision=_REV,
            locator={"path": "docs/policy.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:policy",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/rag.md#retrieval-augmented-generation",
            title="Retrieval-Augmented Generation",
            text=(
                "RAG (Retrieval-Augmented Generation) fetches relevant chunks before calling "
                "the LLM."
            ),
            revision=_REV,
            locator={"path": "docs/rag.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:rag",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/sse.md#server-sent-events",
            title="Server-Sent Events",
            text="SSE (Server-Sent Events) enables real-time one-way server-to-client streaming.",
            revision=_REV,
            locator={"path": "docs/sse.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:sse",),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/chunking.md#chunking-strategy",
            title="Chunking Strategy",
            text=(
                "Chunking splits large documents into overlapping windows for embedding and "
                "retrieval."
            ),
            revision=_REV,
            locator={"path": "docs/chunking.md", "line_start": 1, "line_end": 3},
            context_keys=("concept:chunking",),
        ),
    ]


# ── Concept alias tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_oop_alias_boosts_oop_source(knowledge) -> None:
    """Query 'what is OOP?' should rank the OOP source first via alias expansion."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is OOP?", top_k=3)
    assert evidence[0].title == "Object-Oriented Programming"


@pytest.mark.asyncio
async def test_di_alias_boosts_di_source(knowledge) -> None:
    """Query 'what's DI?' should rank the DI source first."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what's DI?", top_k=3)
    assert evidence[0].title == "Dependency Injection"


def test_short_alias_does_not_match_inside_an_unrelated_word() -> None:
    assert _expand_query("What is the difference between two scores?") == set()


@pytest.mark.asyncio
async def test_rag_alias_boosts_rag_source(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is RAG?", top_k=3)
    assert evidence[0].title == "Retrieval-Augmented Generation"


@pytest.mark.asyncio
async def test_sse_alias_boosts_sse_source(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is SSE?", top_k=3)
    assert evidence[0].title == "Server-Sent Events"


@pytest.mark.asyncio
async def test_factory_query_finds_factory_source(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what's factory?", top_k=3)
    assert any(e.title == "factory.py — create_app" for e in evidence)


@pytest.mark.asyncio
async def test_preflight_alias_resolves(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is preflight?", top_k=3)
    assert evidence[0].title == "Preflight Checks"


@pytest.mark.asyncio
async def test_observability_alias_resolves(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what's observability?", top_k=3)
    assert evidence[0].title == "Observability"


@pytest.mark.asyncio
async def test_policy_query_resolves(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what's a policy in cogentrex?", top_k=3)
    assert evidence[0].title == "Security Policy"


@pytest.mark.asyncio
async def test_chunking_query_resolves(knowledge) -> None:
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is chunking?", top_k=3)
    assert evidence[0].title == "Chunking Strategy"


# ── Score diagnostic fields ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_carries_score_components(knowledge) -> None:
    """Each LearningEvidence should expose dense/lexical/context/symbol score components."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is OOP?", top_k=3)
    first = evidence[0]
    # score_components must exist and contain the expected keys
    assert hasattr(first, "score_components")
    components = first.score_components
    for key in ("dense", "lexical", "context", "exact_symbol", "final"):
        assert key in components, f"Missing score component: {key}"
        assert isinstance(components[key], float)
    # final should match score
    assert abs(components["final"] - first.score) < 1e-6


@pytest.mark.asyncio
async def test_public_dict_includes_score_components(knowledge) -> None:
    """public() should include score_components for safe diagnostics."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("what is OOP?", top_k=1)
    pub = evidence[0].public()
    assert "score_components" in pub
    assert pub["score_components"]["final"] == pub["score"]


# ── Exact symbol/file matching ───────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_symbol_match_boosts_factory(knowledge) -> None:
    """Querying 'create_app' should boost the source containing that symbol."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("create_app", top_k=3)
    assert evidence[0].title == "factory.py — create_app"


@pytest.mark.asyncio
async def test_exact_path_match_boosts_file(knowledge) -> None:
    """Querying 'factory.py' should boost sources with that file path."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("factory.py", top_k=3)
    assert evidence[0].title == "factory.py — create_app"


# ── Unrelated queries remain stable ──────────────────────────────────


@pytest.mark.asyncio
async def test_unrelated_query_still_returns_results(knowledge) -> None:
    """Queries without alias/symbol matches should still work via dense+lexical."""
    await knowledge.sync(_concept_sources())
    evidence = await knowledge.search("how do I handle errors in production?", top_k=3)
    assert len(evidence) >= 1
    assert all(isinstance(e, LearningEvidence) for e in evidence)
