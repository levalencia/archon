"""Persistence and retrieval contracts for curated learning knowledge."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.learning_tutor.repository import LearningKnowledgeRepository, LearningTutorRepository
from app.learning_tutor.sources import LearningSourceInput
from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import EmbeddingService
from app.services.db_store import DatabaseStore


@pytest.fixture
async def repositories(tmp_path: Path):
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'learning.db'}")
    await store.initialize()
    knowledge = LearningKnowledgeRepository(
        store.session_factory,
        EmbeddingService(provider="mock", dimensions=32),
        PersistenceRedactor(),
    )
    tutor = LearningTutorRepository(store.session_factory, PersistenceRedactor())
    try:
        yield knowledge, tutor
    finally:
        await store.close()


def _sources(revision: str = "a" * 40) -> list[LearningSourceInput]:
    return [
        LearningSourceInput(
            kind="code",
            key="backend/app/main.py#create_app",
            title="main.py — create_app",
            text="app.state.sandbox_executor = None\napp.state.evidence_verifier = None",
            revision=revision,
            locator={"path": "backend/app/main.py", "line_start": 418, "line_end": 419},
            context_keys=("artifact:code-first-video-02", "concept:application-composition"),
        ),
        LearningSourceInput(
            kind="documentation",
            key="docs/course/concepts/application-composition.md#service-slots",
            title="Application composition — Service slots",
            text="A service slot is initialized to None and populated during application lifespan.",
            revision=revision,
            locator={
                "path": "docs/course/concepts/application-composition.md",
                "line_start": 40,
                "line_end": 46,
            },
            context_keys=("concept:application-composition",),
        ),
        LearningSourceInput(
            kind="video",
            key="video:code-first-video-02:7",
            title="Video 2 — Application state",
            text="Service slots start empty and lifespan later installs the runtime service.",
            revision=revision,
            locator={
                "artifact_id": "code-first-video-02",
                "start_seconds": 286.94,
                "end_seconds": 347.156,
                "chapter": "Application state",
            },
            context_keys=("artifact:code-first-video-02",),
        ),
    ]


def test_vocabulary_discovery_rollout_is_default_off_and_mapped_by_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COGENTREX_LEARNING_TUTOR_VOCABULARY_DISCOVERY_ENABLED", raising=False)
    assert Settings().learning_tutor_vocabulary_discovery_enabled is False

    monkeypatch.setenv("COGENTREX_LEARNING_TUTOR_VOCABULARY_DISCOVERY_ENABLED", "true")
    assert Settings().learning_tutor_vocabulary_discovery_enabled is True
    compose = (Path(__file__).parents[3] / "docker-compose.local.yml").read_text()
    assert "COGENTREX_LEARNING_TUTOR_VOCABULARY_DISCOVERY_ENABLED" in compose


@pytest.mark.asyncio
async def test_sync_is_idempotent_and_prunes_stale_sources(repositories) -> None:
    knowledge, _ = repositories

    first = await knowledge.sync(_sources())
    second = await knowledge.sync(_sources())
    third = await knowledge.sync(_sources()[:2])

    assert first == {"added": 3, "updated": 0, "unchanged": 0, "removed": 0}
    assert second == {"added": 0, "updated": 0, "unchanged": 3, "removed": 0}
    assert third == {"added": 0, "updated": 0, "unchanged": 2, "removed": 1}
    assert await knowledge.count_sources() == 2


@pytest.mark.asyncio
async def test_sync_reembeds_unchanged_sources_when_embedding_space_changes(repositories) -> None:
    knowledge, _ = repositories
    await knowledge.sync(_sources())
    knowledge._embeddings = EmbeddingService(  # noqa: SLF001 - test changes the provider boundary
        provider="mock", model="mock-v2", dimensions=32
    )

    assert await knowledge.search("service slot", top_k=3) == []
    result = await knowledge.sync(_sources())

    assert result == {"added": 0, "updated": 3, "unchanged": 0, "removed": 0}


@pytest.mark.asyncio
async def test_hybrid_search_prioritizes_exact_terms_and_active_context(repositories) -> None:
    knowledge, _ = repositories
    await knowledge.sync(_sources())

    evidence = await knowledge.search(
        "What is a service slot?",
        context_keys={"artifact:code-first-video-02"},
        top_k=3,
    )

    assert len(evidence) == 3
    assert evidence[0].kind in {"video", "documentation"}
    assert "service slot" in evidence[0].text.lower()
    assert any(item.locator.get("line_start") == 418 for item in evidence)
    assert any(item.locator.get("start_seconds") == 286.94 for item in evidence)
    assert all(item.id.startswith("E") for item in evidence)


@pytest.mark.asyncio
async def test_definition_queries_prioritize_glossary_before_unrelated_code(repositories) -> None:
    knowledge, _ = repositories
    await knowledge.sync(
        [
            LearningSourceInput(
                kind="documentation",
                key="docs/course/reference/glossary.md#class",
                title="Beginner glossary — Class",
                text=(
                    "Class. A class is a reusable blueprint that defines what data its objects "
                    "hold and what behavior those objects provide."
                ),
                revision="a" * 40,
                locator={"path": "docs/course/reference/glossary.md", "line_start": 20},
                context_keys=("vocabulary:class", "concept:python-protocols-di"),
            ),
            LearningSourceInput(
                kind="code",
                key="backend/app/runtime/engine.py#class-object",
                title="Runtime class object helpers",
                text="class ObjectRegistry: class_object = object()",
                revision="a" * 40,
                locator={"path": "backend/app/runtime/engine.py", "line_start": 1},
                context_keys=(),
            ),
        ]
    )

    evidence = await knowledge.search(
        "What is the difference between a class and an object?",
        context_keys={"vocabulary:class"},
        top_k=2,
    )

    assert evidence[0].locator["path"] == "docs/course/reference/glossary.md"
    assert evidence[0].score_components["definition_source"] == 1.0
    assert evidence[0].score_components["vocabulary_context"] == 1.0


@pytest.mark.asyncio
async def test_vocabulary_discovery_is_default_off_but_explicit_context_remains_available(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'vocabulary-routing.db'}")
    await store.initialize()
    sources = [
        LearningSourceInput(
            kind="visual",
            key="visual:vocabulary:sse",
            title="Beginner glossary — SSE",
            text="SSE means Server-Sent Events, a one-way HTTP event stream.",
            revision="a" * 40,
            locator={"route": "/learn?view=glossary", "vocabulary_id": "sse"},
            context_keys=("vocabulary:sse",),
        ),
        LearningSourceInput(
            kind="code",
            key="backend/app/routes/learning_tutor.py#stream_learning_answer",
            title="Learning Tutor SSE endpoint",
            text=(
                "The endpoint sends status, progress, heartbeat, answer_delta, result, "
                "and done events."
            ),
            revision="a" * 40,
            locator={"path": "backend/app/routes/learning_tutor.py", "line_start": 87},
            context_keys=("view:roadmap",),
        ),
    ]
    try:
        default_repository = LearningKnowledgeRepository(
            store.session_factory,
            EmbeddingService(provider="mock", dimensions=32),
            PersistenceRedactor(),
        )
        await default_repository.sync(sources)

        general = await default_repository.search(
            "Explain the SSE streaming protocol and disconnect behavior.",
            context_keys={"view:roadmap"},
            top_k=2,
        )
        explicit = await default_repository.search(
            "What is SSE?",
            context_keys={"vocabulary:sse"},
            top_k=2,
        )
        rollout_repository = LearningKnowledgeRepository(
            store.session_factory,
            EmbeddingService(provider="mock", dimensions=32),
            PersistenceRedactor(),
            vocabulary_discovery_enabled=True,
        )
        rollout = await rollout_repository.search(
            "What is SSE?",
            context_keys={"view:roadmap"},
            top_k=2,
        )

        assert all(item.locator.get("vocabulary_id") is None for item in general)
        assert explicit[0].locator.get("vocabulary_id") == "sse"
        assert any(item.locator.get("vocabulary_id") == "sse" for item in rollout)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_tutor_sessions_are_owner_scoped_and_turns_keep_context(repositories) -> None:
    _, tutor = repositories
    session = await tutor.get_or_create_session(
        owner_id="alice",
        project_id="default",
        context_key="artifact:code-first-video-02",
        title="Video 2",
    )
    await tutor.store_turn(
        session_id=session.id,
        owner_id="alice",
        project_id="default",
        question="What is a service slot?",
        answer="A service slot is initialized before startup.",
        context={"artifact_id": "code-first-video-02", "playback_seconds": 300.0},
        evidence=[{"id": "E1", "kind": "video"}],
        diagram=None,
        metrics={"grounded": True},
    )

    loaded = await tutor.get_session(session.id, owner_id="alice")
    assert loaded is not None
    assert loaded.turns[0].context["playback_seconds"] == 300.0
    assert loaded.turns[0].evidence[0]["id"] == "E1"
    assert await tutor.get_session(session.id, owner_id="bob") is None


@pytest.mark.asyncio
async def test_tutor_turn_redacts_structured_evidence_before_json_encoding(repositories) -> None:
    _, tutor = repositories
    session = await tutor.get_or_create_session(
        owner_id="alice",
        project_id="default",
        context_key="view:roadmap",
        title="Roadmap",
    )
    excerpt = ('The JSON example says "contact learner@example.com at 127.0.0.1". ' * 180).strip()

    stored = await tutor.store_turn(
        session_id=session.id,
        owner_id="alice",
        project_id="default",
        question="What is a chunk?",
        answer="A chunk is a bounded unit of text.",
        context={"view": "roadmap"},
        evidence=[{"id": "E1", "kind": "documentation", "excerpt": excerpt}],
        diagram=None,
        metrics={"grounded": True},
    )

    assert stored.evidence[0]["id"] == "E1"
    assert "learner@example.com" not in stored.evidence[0]["excerpt"]
    assert "127.0.0.1" not in stored.evidence[0]["excerpt"]
    assert "[EMAIL]" in stored.evidence[0]["excerpt"]
    assert "[IP_ADDRESS]" in stored.evidence[0]["excerpt"]
