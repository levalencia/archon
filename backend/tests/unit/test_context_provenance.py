"""Effective-context provenance contracts and metadata-only persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pytest

from app.runtime.context import build_effective_context
from app.runtime.context_provenance import EffectiveContextManifest
from app.services.context_snapshots import ContextSnapshotConflictError, ContextSnapshotRepository
from app.services.db_store import Base, ContextSnapshotRow


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
    compacted = manifest.after_compaction(summarized_messages=2, estimated_tokens=40)

    assert compacted.selected_message_ids == (3, 4)
    assert compacted.summarized_message_ids == (1, 2)
    assert compacted.summary_version == "auto-compact-v1"
    assert compacted.truncation_reason == "token_threshold"
    assert compacted.manifest_hash == compacted.manifest_hash
    assert compacted.manifest_hash != manifest.manifest_hash


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repository_is_idempotent_scoped_and_stores_no_content(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = ContextSnapshotRepository(sessions)
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
