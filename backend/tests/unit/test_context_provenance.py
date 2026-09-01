"""Effective-context provenance contracts and metadata-only persistence."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.runtime.context import build_effective_context, derive_context_asset_hmac_key
from app.runtime.context_provenance import (
    CapabilityContextRef,
    EffectiveContext,
    EffectiveContextManifest,
)
from app.runtime.models import Message, Role
from app.runtime.support import compact_effective_context
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


class CurrentMemory:
    async def retrieve_with_metadata(self, conversation_id, limit=20, user_id="default"):
        del conversation_id, limit, user_id
        return [{"id": 21, "role": "user", "content": "[REDACTED] visible"}]


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
@pytest.mark.asyncio
async def test_persisted_current_message_and_image_fingerprint_match_provider_context() -> None:
    image = "data:image/png;base64,AAAA"
    fingerprint_key = derive_context_asset_hmac_key("application-secret-for-tests")
    context = await build_effective_context(
        "raw secret input",
        "conversation-1",
        CurrentMemory(),
        Tools(),
        images=[image],
        user_id="alice",
        project_id="project",
        run_id="run-1",
        current_message_id=21,
        asset_hmac_key=fingerprint_key,
    )

    assert context.messages[-1].content == "[REDACTED] visible"
    assert context.messages[-1].images == (image,)
    assert context.source_message_ids[-1] == 21
    assert context.manifest.selected_message_ids == (21,)
    expected = hmac.new(
        fingerprint_key,
        b"archon/context-asset/v1\0alice\0project\0run-1\0" + image.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert context.manifest.input_asset_fingerprints == (expected,)
    other_owner = hmac.new(
        fingerprint_key,
        b"archon/context-asset/v1\0bob\0project\0run-1\0" + image.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert expected != other_owner
    assert expected != hashlib.sha256(image.encode("utf-8")).hexdigest()
    assert "raw secret input" not in str(context.manifest.semantic_document())


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
        capability_references=(
            CapabilityContextRef(
                capability_id="native.read_file",
                name="read_file",
                permission="allow",
                reason="provider_visible_after_scope_policy",
                schema_hash="a" * 64,
            ),
        ),
        selected_capability_ids=("native.read_file",),
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
                row.capability_references_json,
                row.manifest_hash,
            ]
        )
        assert "secret" not in persisted
        assert not hasattr(row, "content")
        assert not hasattr(row, "prompt")
        assert not hasattr(row, "summary")
    await engine.dispose()


@pytest.mark.asyncio
async def test_shared_compaction_updates_messages_sources_and_manifest(monkeypatch) -> None:
    async def fake_compact(messages, **kwargs):
        assert kwargs["max_tokens"] == 5_904
        return (
            [
                {"role": "system", "content": "summary", "images": []},
                {
                    "role": "user",
                    "content": "current",
                    "images": [],
                    "_source_message_id": 12,
                },
            ],
            {
                "compacted": True,
                "tokens": 42,
                "selected_message_ids": [12],
                "summarized_message_ids": [11],
            },
        )

    monkeypatch.setattr("app.runtime.support.auto_compact_context", fake_compact)
    original = EffectiveContext(
        (Message(Role.USER, "old"), Message(Role.USER, "current")),
        (11, 12),
        EffectiveContextManifest(
            owner_id="alice",
            project_id="project",
            run_id="run-1",
            conversation_id="conversation",
            selected_message_ids=(11, 12),
            estimated_tokens=10_000,
        ),
    )

    compacted, stats = await compact_effective_context(
        original, max_tokens=10_000, reserve_for_response=4_096
    )

    assert stats["compacted"] is True
    assert [message.content for message in compacted.messages] == ["summary", "current"]
    assert compacted.source_message_ids == (None, 12)
    assert compacted.manifest.selected_message_ids == (12,)
    assert compacted.manifest.summarized_message_ids == (11,)
    assert compacted.manifest.estimated_tokens == 42
