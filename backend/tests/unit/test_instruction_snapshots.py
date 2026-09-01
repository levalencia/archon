from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.instructions.loaders import load_project_instructions
from app.services.db_store import DatabaseStore
from app.skills.context import EffectiveContextEnrichmentService
from app.skills.discovery import DiscoveryResult
from app.skills.persistence import ProjectInstructionRepository, SkillRepository

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_scan_snapshot_is_exact_ordered_restart_safe_and_owner_scoped(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / ".archon").mkdir(parents=True)
    (workspace / "service" / ".archon").mkdir(parents=True)
    (workspace / ".archon" / "instructions.md").write_text("root policy" + chr(10))
    (workspace / "service" / ".archon" / "instructions.md").write_text("leaf policy" + chr(10))
    loaded = load_project_instructions(workspace, "service")
    assert [source.relative_path for source in loaded] == [
        ".archon/instructions.md",
        "service/.archon/instructions.md",
    ]

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'snapshots.db'}"
    store = DatabaseStore(database_url)
    await store.initialize()
    repository = ProjectInstructionRepository(store.session_factory)
    snapshot = await repository.append_sources(
        owner_id="alice", project_id="project", sources=loaded
    )
    assert snapshot.revision.content == ""
    assert [source.content_hash for source in snapshot.sources] == [
        source.content_hash for source in loaded
    ]
    assert (
        await repository.set_current(
            owner_id="mallory", project_id="project", revision_id=snapshot.revision.id
        )
        is None
    )
    approved = await repository.set_current(
        owner_id="alice", project_id="project", revision_id=snapshot.revision.id
    )
    assert approved is not None and approved.review_state == "approved"
    await store.close()

    restarted = DatabaseStore(database_url)
    await restarted.initialize()
    restarted_repository = ProjectInstructionRepository(restarted.session_factory)
    current = await restarted_repository.current_snapshot(owner_id="alice", project_id="project")
    assert current is not None
    assert [source.relative_path for source in current.sources] == [
        ".archon/instructions.md",
        "service/.archon/instructions.md",
    ]
    assert [source.content for source in current.sources] == ["root policy", "leaf policy"]

    selection = DiscoveryResult((), (), (), (), 0)
    enriched = await EffectiveContextEnrichmentService(
        SkillRepository(restarted.session_factory), restarted_repository
    ).enrich(
        owner_id="alice",
        project_id="project",
        selection=selection,
        max_context_bytes=1000,
    )
    assert [block.identifier for block in enriched.blocks] == [
        ".archon/instructions.md",
        "service/.archon/instructions.md",
    ]
    refs = enriched.manifest.instruction_revisions
    assert [ref.order for ref in refs] == [0, 1]
    assert [ref.relative_path for ref in refs] == [block.identifier for block in enriched.blocks]
    assert [ref.content_hash for ref in refs] == [block.content_hash for block in enriched.blocks]
    assert all(ref.scope_path in {".", "service"} for ref in refs)
    assert "root policy" not in str(enriched.manifest.semantic_document())

    # Runtime verification also fails closed if a store was created without migration triggers.
    async with restarted.session_factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE project_instruction_sources SET content='tampered' "
                "WHERE revision_id=:revision_id AND ordinal=0"
            ),
            {"revision_id": snapshot.revision.id},
        )
    with pytest.raises(ValueError, match="integrity check failed"):
        await restarted_repository.current_snapshot(owner_id="alice", project_id="project")
    await restarted.close()
