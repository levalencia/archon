"""Typed effective-context enrichment from durable instruction and skill revisions."""

from __future__ import annotations

from dataclasses import dataclass

from app.runtime.context_provenance import (
    EffectiveContextManifest,
    InstructionRevisionRef,
    SkillRevisionRef,
)
from app.skills.discovery import DiscoveryResult
from app.skills.parser import parse_skill_markdown
from app.skills.persistence import ProjectInstructionRepository, SkillRepository


@dataclass(frozen=True, slots=True)
class ContextBlock:
    kind: str
    identifier: str
    content: str
    content_hash: str
    reason: str
    order: int
    context_cost_bytes: int


@dataclass(frozen=True, slots=True)
class EnrichedContext:
    blocks: tuple[ContextBlock, ...]
    manifest: EffectiveContextManifest


class EffectiveContextEnrichmentService:
    def __init__(self, skills: SkillRepository, instructions: ProjectInstructionRepository) -> None:
        self._skills = skills
        self._instructions = instructions

    async def enrich(
        self,
        *,
        owner_id: str,
        project_id: str,
        selection: DiscoveryResult,
        max_context_bytes: int,
        run_id: str = "enrichment",
        conversation_id: str = "enrichment",
    ) -> EnrichedContext:
        if max_context_bytes < 0:
            raise ValueError("max_context_bytes must be non-negative")
        blocks: list[ContextBlock] = []
        instruction_refs: list[InstructionRevisionRef] = []
        skill_refs: list[SkillRevisionRef] = []
        rejected = [item.capability_id for item in selection.rejected]
        spent = 0
        snapshot = await self._instructions.current_snapshot(
            owner_id=owner_id, project_id=project_id
        )
        if snapshot is not None and snapshot.revision.review_state == "approved":
            instruction_cost = sum(source.byte_count for source in snapshot.sources)
            if instruction_cost > max_context_bytes:
                raise ValueError("context budget cannot fit project instructions")
            for source in snapshot.sources:
                order = len(blocks)
                blocks.append(
                    ContextBlock(
                        "project_instruction",
                        source.relative_path,
                        source.content,
                        source.content_hash,
                        "current_snapshot_root_to_leaf",
                        order,
                        source.byte_count,
                    )
                )
                instruction_refs.append(
                    InstructionRevisionRef(
                        revision_id=snapshot.revision.id,
                        content_hash=source.content_hash,
                        order=source.ordinal,
                        relative_path=source.relative_path,
                        scope_path=source.scope_path,
                        family=source.family,
                        is_override=source.is_override,
                        byte_count=source.byte_count,
                    )
                )
            spent += instruction_cost
        for selected in selection.selected:
            row = await self._skills.get_visible_revision(
                owner_id=owner_id, revision_id=selected.revision_id
            )
            parsed = parse_skill_markdown(row.content.encode("utf-8"))
            cost = len(parsed.instructions.encode("utf-8"))
            if spent + cost > max_context_bytes:
                rejected.append(selected.capability_id)
                continue
            order = len(blocks)
            blocks.append(
                ContextBlock(
                    "skill",
                    selected.capability_id,
                    parsed.instructions,
                    row.content_hash,
                    ",".join(selected.reasons),
                    order,
                    cost,
                )
            )
            skill_refs.append(
                SkillRevisionRef(selected.capability_id, row.id, row.content_hash, selected.reasons)
            )
            spent += cost
        selected_ids = tuple(
            item.capability_id for item in selection.selected if item.capability_id not in rejected
        )
        manifest = EffectiveContextManifest(
            owner_id=owner_id,
            project_id=project_id,
            run_id=run_id,
            conversation_id=conversation_id,
            instruction_revisions=tuple(instruction_refs),
            skill_revisions=tuple(skill_refs),
            selected_capability_ids=selected_ids,
            rejected_capability_ids=tuple(dict.fromkeys(rejected)),
            context_cost_bytes=spent,
            skill_ids=tuple(item.revision_id for item in skill_refs),
        )
        return EnrichedContext(tuple(blocks), manifest)
