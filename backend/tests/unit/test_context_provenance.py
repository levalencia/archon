"""Effective-context provenance contracts and metadata-only persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.runtime.context import build_effective_context
from app.runtime.context_provenance import EffectiveContextManifest
from app.security.persistence_redactor import PersistenceRedactor
from app.services.auto_compact import auto_compact_context
from app.services.context_snapshots import ContextSnapshotConflictError, ContextSnapshotRepository
from app.services.db_store import Base, ContextSnapshotRow
from app.services.run_ledger import RunRepository


class Tools:
    def list_tools(self):
        return [{"name": "safe_tool"}]


class Memory:
    async def retrieve_with_metadata(self, conversation_id, limit=20, user_id="default"):
        del conversation_id, limit, user_id
        return [
            {"id": 11, "role": "user", "content": "old secret one"},
            {"id": 12, "role": "assistant", "content": "old secret two"},
        ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_builder_returns_messages_and_metadata_only_manifest() -> None:
    context = await build_effective_context(
        "current secret",
        "conversation-1",
        Memory(),
        Tools(),
        "\n[Skill content secret]",
        user_id="alice",
        persistent_memory_text="memory secret",
        project_id="project",
        run_id="run-1",
        memory_ids=("memory-1",),
        skill_ids=("skill-1",),
    )

    assert [message.content for message in context.messages][-3:] == [
        "old secret one",
        "old secret two",
        "current secret",
    ]
    assert context.manifest.selected_message_ids == (11, 12)
    assert context.manifest.memory_ids == ("memory-1",)
    assert context.manifest.skill_ids == ("skill-1",)
    encoded = str(context.manifest.semantic_document())
    assert "current secret" not in encoded
    assert "old secret" not in encoded
    assert "memory secret" not in encoded


@pytest.mark.unit
def test_compaction_moves_only_source_ids_and_hash_is_deterministic() -> None:
    manifest = EffectiveContextManifest(
        owner_id="alice",
        project_id="project",
        run_id="run-1",
        conversation_id="conversation-1",
        selected_message_ids=(1, 2, 3, 4),
        memory_ids=("memory-1",),
        skill_ids=("skill-1",),
        estimated_tokens=100,
    )
    compacted = manifest.after_compaction(
        selected_message_ids=(1, 4),
        summarized_message_ids=(2, 3),
        estimated_tokens=40,
    )

    assert compacted.selected_message_ids == (1, 4)
    assert compacted.summarized_message_ids == (2, 3)
    assert compacted.summary_version == "auto-compact-v1"
    assert compacted.truncation_reason == "token_threshold"
    assert compacted.manifest_hash == compacted.manifest_hash
    assert compacted.manifest_hash != manifest.manifest_hash


@pytest.mark.unit
@pytest.mark.asyncio
async def test_compactor_returns_exact_source_ids_with_historical_system_messages() -> None:
    messages = [
        {"role": "system", "content": "root", "_source_message_id": None},
        {"role": "system", "content": "historic system", "_source_message_id": 10},
        {"role": "user", "content": "old user", "_source_message_id": 11},
        {"role": "assistant", "content": "old assistant", "_source_message_id": 12},
        {"role": "user", "content": "current", "_source_message_id": 13},
    ]
    _, stats = await auto_compact_context(messages, max_tokens=1, threshold=0, keep_recent=1)

    assert stats["compacted"] is True
    assert stats["summarized_message_ids"] == [11, 12]
    assert stats["selected_message_ids"] == [10, 13]


@pytest.mark.unit
def test_current_message_id_is_added_to_manifest_and_aligned_context() -> None:
    manifest = EffectiveContextManifest(
        owner_id="alice",
        project_id="project",
        run_id="run-1",
        conversation_id="conversation-1",
        selected_message_ids=(11,),
    )
    assert manifest.with_current_message(12).selected_message_ids == (11, 12)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repository_is_idempotent_scoped_and_stores_no_content(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = ContextSnapshotRepository(sessions)
    await RunRepository(sessions, PersistenceRedactor()).ensure_run(
        run_id="run-1",
        user_id="alice",
        project_id="project",
        conversation_id="conversation-1",
        correlation_id="correlation-1",
        provider="mock",
        model="mock-model",
    )
    manifest = EffectiveContextManifest(
        owner_id="alice",
        project_id="project",
        run_id="run-1",
        conversation_id="conversation-1",
        selected_message_ids=(11, 12),
        memory_ids=("memory-1",),
        skill_ids=("skill-1",),
        estimated_tokens=50,
    )

    first = await repository.record(manifest)
    second = await repository.record(manifest)
    assert first == second == manifest
    assert await repository.get(owner_id="bob", project_id="project", run_id="run-1") is None
    assert await repository.get(owner_id="alice", project_id="project", run_id="run-1") == manifest

    conflicting = EffectiveContextManifest(
        owner_id="alice",
        project_id="project",
        run_id="run-1",
        conversation_id="conversation-1",
        estimated_tokens=51,
    )
    with pytest.raises(ContextSnapshotConflictError):
        await repository.record(conflicting)

    async with sessions() as session:
        row = await session.scalar(select(ContextSnapshotRow))
        assert row is not None
        persisted = " ".join(
            [
                row.selected_message_ids_json,
                row.summarized_message_ids_json,
                row.memory_ids_json,
                row.skill_ids_json,
                row.manifest_hash,
            ]
        )
        assert "secret" not in persisted
        assert not hasattr(row, "content")
        assert not hasattr(row, "prompt")
        assert not hasattr(row, "summary")
    await engine.dispose()
