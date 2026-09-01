from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.db_store import DatabaseStore
from app.skills.bootstrap import BundledSkillBootstrap
from app.skills.bundled import ARCHON_OWNER_ID, bundled_skills
from app.skills.context import EffectiveContextEnrichmentService
from app.skills.discovery import DiscoveryRequest, SkillDiscoveryService
from app.skills.parser import parse_skill_markdown
from app.skills.persistence import ProjectInstructionRepository, SkillRepository
from app.tools.skill_discovery import GovernedSkillDiscoveryTools

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_bundled_bootstrap_is_strict_idempotent_and_restart_safe(tmp_path: Path) -> None:
    catalog = bundled_skills()
    assert len(catalog) == 10
    assert all(x.parsed.triggers and x.parsed.negative_triggers for x in catalog)
    assert all(x.parsed.required_capability_ids for x in catalog)
    checklists = [next(iter(item.references.values())) for item in catalog]
    assert all(len(checklist.encode("utf-8")) >= 500 for checklist in checklists)
    assert len(set(checklists)) == len(checklists)
    url = f"sqlite+aiosqlite:///{tmp_path / 'bundled.db'}"
    store = DatabaseStore(url)
    await store.initialize()
    first = await BundledSkillBootstrap(SkillRepository(store.session_factory)).install()
    second = await BundledSkillBootstrap(SkillRepository(store.session_factory)).install()
    assert first == second
    assert len(first) == 10
    await store.close()
    restarted = DatabaseStore(url)
    await restarted.initialize()
    rows = await SkillRepository(restarted.session_factory).list_discoverable(
        owner_id=ARCHON_OWNER_ID
    )
    assert len(rows) == 10
    assert all(x.trust_state == "verified" and x.review_state == "approved" for x in rows)
    await restarted.close()


@pytest.mark.asyncio
async def test_metadata_first_discovery_negative_denied_budget_and_lazy_reference(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'discover.db'}")
    await store.initialize()
    repository = SkillRepository(store.session_factory)
    installed = await BundledSkillBootstrap(repository).install()
    for name in ("code-review", "deploy-safety"):
        skill = next(item for item in installed if item.name == name)
        await repository.bind(
            owner_id="alice",
            project_id="p",
            package_id=skill.package_id,
            revision_id=skill.revision_id,
            revision_owner_id=ARCHON_OWNER_ID,
        )
    service = SkillDiscoveryService(repository)
    result = await service.discover(
        DiscoveryRequest(
            owner_id="alice",
            project_id="p",
            intent="review python code, do not deploy",
            context_budget=5000,
            permission_decisions={},
        )
    )
    assert result.selected
    assert result.selected[0].metadata["required_capability_ids"]
    assert all("instructions" not in json.dumps(item.metadata) for item in result.candidates)
    deploy = next(item for item in result.rejected if item.capability_id == "archon.deploy-safety")
    assert any(reason.startswith("negative_trigger:") for reason in deploy.reasons)
    selected = result.selected[0]
    loaded = await service.load_selected(
        owner_id="alice", project_id="p", revision_id=selected.revision_id
    )
    assert loaded.content
    with pytest.raises(LookupError):
        await service.load_reference(
            owner_id="alice",
            project_id="p",
            revision_id=selected.revision_id,
            path="references/not-declared.md",
        )
    reference = await service.load_reference(
        owner_id="alice",
        project_id="p",
        revision_id=selected.revision_id,
        path=loaded.references[0],
        max_bytes=4096,
    )
    assert reference.content
    tiny = await service.discover(
        DiscoveryRequest(
            owner_id="alice",
            project_id="p",
            intent="review python code",
            context_budget=1,
            permission_decisions={"capability.code.read": "allow"},
        )
    )
    assert not tiny.selected
    assert any("context_budget" in item.reasons for item in tiny.rejected)
    await store.close()


@pytest.mark.asyncio
async def test_runtime_is_project_scoped_pins_exact_revision_and_revalidates_reference(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
    await store.initialize()
    repository = SkillRepository(store.session_factory)
    bundled = await BundledSkillBootstrap(repository).install()
    review = next(item for item in bundled if item.name == "code-review")
    await repository.bind(
        owner_id="alice",
        project_id="one",
        package_id=review.package_id,
        revision_id=review.revision_id,
        revision_owner_id=ARCHON_OWNER_ID,
    )
    service = SkillDiscoveryService(repository)
    with pytest.raises(LookupError):
        await service.discover(
            DiscoveryRequest(
                owner_id="alice",
                project_id="two",
                intent="review code",
                explicit_ids=("archon.code-review",),
            )
        )
    assert not (
        await service.discover(
            DiscoveryRequest(owner_id="alice", project_id="two", intent="review code")
        )
    ).candidates

    def source(version: str, instruction: str) -> bytes:
        return f"""---
name: versioned
description: Exact revision test
version: {version}
tags: [version]
references: [refs/guide.md]
triggers: [version]
---
{instruction}
""".encode()

    old = await repository.install(
        owner_id="alice",
        parsed=parse_skill_markdown(source("1.0.0", "Use old rules.")),
        source_url="https://example.test/old",
        source_revision="a" * 40,
        trust_state="allowlisted",
        review_state="approved",
        reference_contents={"refs/guide.md": "old reference"},
    )
    await repository.install(
        owner_id="alice",
        parsed=parse_skill_markdown(source("2.0.0", "Use new rules.")),
        source_url="https://example.test/new",
        source_revision="b" * 40,
        trust_state="allowlisted",
        review_state="approved",
    )
    await repository.bind(
        owner_id="alice",
        project_id="one",
        package_id=old.package_id,
        revision_id=old.revision_id,
    )
    exact = await service.discover(
        DiscoveryRequest(
            owner_id="alice",
            project_id="one",
            intent="version",
            explicit_ids=("owner.versioned",),
        )
    )
    selected = next(item for item in exact.selected if item.capability_id == "owner.versioned")
    assert selected.revision_id == old.revision_id

    tools = GovernedSkillDiscoveryTools(
        service, owner_id="alice", project_id="one", permission_decisions={}
    )
    await tools.discover_capabilities("version", "owner.versioned")
    await repository.bind(
        owner_id="alice",
        project_id="one",
        package_id=old.package_id,
        revision_id=old.revision_id,
        enabled=False,
    )
    with pytest.raises(LookupError):
        await tools.load_skill_reference(old.revision_id, "refs/guide.md")
    disabled_tools = GovernedSkillDiscoveryTools(
        service,
        owner_id="alice",
        project_id="one",
        permission_decisions={},
        disabled_ids=frozenset({"archon.code-review"}),
    )
    with pytest.raises(LookupError):
        await disabled_tools.discover_capabilities("review", "archon.code-review")
    await store.close()


@pytest.mark.asyncio
async def test_explicit_invocation_and_enrichment_provenance_have_no_raw_content(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'context.db'}")
    await store.initialize()
    skills = SkillRepository(store.session_factory)
    installed = await BundledSkillBootstrap(skills).install()
    review = next(x for x in installed if x.name == "code-review")
    await skills.bind(
        owner_id="alice",
        project_id="p",
        package_id=review.package_id,
        revision_id=review.revision_id,
        revision_owner_id=ARCHON_OWNER_ID,
    )
    instructions = ProjectInstructionRepository(store.session_factory)
    instruction = await instructions.append(
        owner_id="alice", project_id="p", content="SECRET instruction"
    )
    discovery = SkillDiscoveryService(skills)
    discovered = await discovery.discover(
        DiscoveryRequest(
            owner_id="alice",
            project_id="p",
            intent="unrelated",
            explicit_ids=("archon.code-review",),
            context_budget=10000,
            permission_decisions={"capability.code.read": "allow"},
        )
    )
    enriched = await EffectiveContextEnrichmentService(skills, instructions).enrich(
        owner_id="alice", project_id="p", selection=discovered, max_context_bytes=10000
    )
    assert enriched.blocks[0].kind == "project_instruction"
    assert enriched.manifest.instruction_revisions[0].revision_id == instruction.id
    assert enriched.manifest.skill_revisions[0].revision_id == review.revision_id
    serialized = json.dumps(enriched.manifest.semantic_document())
    assert "SECRET" not in serialized
    assert enriched.manifest.context_cost_bytes > 0
    assert enriched.manifest.selected_capability_ids == ("archon.code-review",)
    await store.close()
