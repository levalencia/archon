"""Persistence and retrieval contracts for curated learning knowledge."""

from __future__ import annotations

from pathlib import Path

import pytest

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
