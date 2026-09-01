from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.db_store import DatabaseStore
from app.skills.parser import parse_skill_markdown
from app.skills.persistence import (
    ProjectInstructionRepository,
    SkillNotFoundError,
    SkillRepository,
)

SKILL = b"""---
name: durable-skill
description: Durable test skill
version: 1.0.0
tags: [test]
references: [refs/guide.md]
---
Always persist safely.
"""


@pytest.mark.asyncio
async def test_repositories_are_scoped_immutable_and_restart_safe(tmp_path: Path) -> None:
    database = tmp_path / "skills.db"
    url = f"sqlite+aiosqlite:///{database}"
    store = DatabaseStore(url)
    await store.initialize()
    skills = SkillRepository(store.session_factory)
    instructions = ProjectInstructionRepository(store.session_factory)

    installed = await skills.install(
        owner_id="owner-a",
        parsed=parse_skill_markdown(SKILL),
        source_url="https://raw.githubusercontent.com/nous/approved/" + "a" * 40 + "/SKILL.md",
        source_revision="a" * 40,
        trust_state="allowlisted",
        review_state="approved",
    )
    duplicate = await skills.install(
        owner_id="owner-a",
        parsed=parse_skill_markdown(SKILL),
        source_url="https://raw.githubusercontent.com/nous/approved/" + "a" * 40 + "/SKILL.md",
        source_revision="a" * 40,
        trust_state="allowlisted",
        review_state="approved",
    )
    assert duplicate == installed
    await skills.bind(
        owner_id="owner-a",
        project_id="project-a",
        package_id=installed.package_id,
        revision_id=installed.revision_id,
    )
    revision = await instructions.append(
        owner_id="owner-a", project_id="project-a", content="Use approved tools only."
    )
    assert revision.revision_number == 1
    with pytest.raises(SkillNotFoundError):
        await skills.get_revision(
            owner_id="owner-b",
            package_id=installed.package_id,
            revision_id=installed.revision_id,
        )
    assert await skills.list_bound(owner_id="owner-b", project_id="project-a") == []
    await store.close()

    restarted = DatabaseStore(url)
    await restarted.initialize()
    restarted_skills = SkillRepository(restarted.session_factory)
    restarted_instructions = ProjectInstructionRepository(restarted.session_factory)
    bound = await restarted_skills.list_bound(owner_id="owner-a", project_id="project-a")
    current = await restarted_instructions.current(owner_id="owner-a", project_id="project-a")
    assert [item.id for item in bound] == [installed.revision_id]
    assert current is not None
    assert current.content == "Use approved tools only."
    assert current.content_hash == revision.content_hash
    await restarted.close()


@pytest.mark.asyncio
async def test_concurrent_revision_allocation_is_serialized(tmp_path: Path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    await store.initialize()
    skills = SkillRepository(store.session_factory)
    instructions = ProjectInstructionRepository(store.session_factory)
    first = parse_skill_markdown(SKILL)
    second = parse_skill_markdown(
        SKILL.replace(b"Always persist safely.", b"Persist concurrently safely.")
    )

    installed = await asyncio.gather(
        skills.install(
            owner_id="owner",
            parsed=first,
            source_url="https://example.invalid/one",
            source_revision="one",
            trust_state="allowlisted",
            review_state="approved",
        ),
        skills.install(
            owner_id="owner",
            parsed=second,
            source_url="https://example.invalid/two",
            source_revision="two",
            trust_state="allowlisted",
            review_state="approved",
        ),
    )
    assert sorted(item.revision_number for item in installed) == [1, 2]

    await asyncio.gather(
        instructions.append(owner_id="owner", project_id="project", content="first"),
        instructions.append(owner_id="owner", project_id="project", content="second"),
    )
    revisions = await instructions.list_revisions(owner_id="owner", project_id="project")
    assert sorted(item.revision_number for item in revisions) == [1, 2]
    await store.close()
