"""Shared durable request-context preparation for synchronous and streaming chat."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from app.capabilities.models import PermissionDecision
from app.capabilities.persistence import CapabilityPreferenceRepository
from app.runtime.context import derive_context_asset_hmac_key
from app.runtime.context_provenance import CapabilityContextRef, EffectiveContext
from app.runtime.support import compact_effective_context, prepare_effective_context
from app.services.context_snapshots import ContextSnapshotRepository
from app.skills.context import EffectiveContextEnrichmentService
from app.skills.discovery import DiscoveryRequest, SkillDiscoveryService


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class PreparedRequestContext:
    effective_context: EffectiveContext
    compact_stats: dict[str, int | bool]
    skills_used: tuple[dict[str, Any], ...]
    permission_decisions: dict[str, PermissionDecision]
    disabled_capability_ids: frozenset[str]


class RequestContextPreparationService:
    """The sole production path for selecting and recording durable context assets."""

    def __init__(
        self,
        discovery: SkillDiscoveryService,
        enrichment: EffectiveContextEnrichmentService,
        snapshots: ContextSnapshotRepository,
        preferences: CapabilityPreferenceRepository,
    ) -> None:
        self.discovery = discovery
        self.enrichment = enrichment
        self.snapshots = snapshots
        self.preferences = preferences

    async def scope_policy(
        self, *, owner_id: str, project_id: str
    ) -> tuple[dict[str, PermissionDecision], frozenset[str]]:
        rows = await self.preferences.list(owner_id=owner_id, project_id=project_id)
        decisions: dict[str, PermissionDecision] = {}
        disabled: set[str] = set()
        for row in rows:
            if row.capability_id.startswith("capability."):
                decisions[row.capability_id] = (
                    PermissionDecision.ALLOW if row.enabled else PermissionDecision.DENY
                )
            elif not row.enabled:
                disabled.add(row.capability_id)
        return decisions, frozenset(disabled)

    async def prepare(
        self,
        *,
        owner_id: str,
        project_id: str,
        intent: str,
        current_path: str | None,
        run_id: str,
        conversation_id: str,
        memory: Any,
        tools: Any,
        images: list[str] | None,
        persistent_memory_text: str,
        memory_ids: tuple[str, ...],
        current_message_id: int,
        application_secret: str,
        max_context_bytes: int,
        max_tokens: int,
        selection_limit: int = 3,
    ) -> PreparedRequestContext:
        decisions, disabled = await self.scope_policy(owner_id=owner_id, project_id=project_id)
        # Skill metadata is discovery guidance only. Tool authorization is
        # evaluated independently by SecureToolRegistry and project policy.
        selection = await self.discovery.discover(
            DiscoveryRequest(
                owner_id=owner_id,
                project_id=project_id,
                intent=intent,
                permission_decisions=decisions,
                context_budget=max_context_bytes,
                limit=selection_limit,
                current_path=current_path,
                disabled_ids=disabled,
            )
        )
        enriched = await self.enrichment.enrich(
            owner_id=owner_id,
            project_id=project_id,
            selection=selection,
            max_context_bytes=max_context_bytes,
            run_id=run_id,
            conversation_id=conversation_id,
        )
        context_text = "".join(
            f"\n\n[{block.kind}: {block.identifier}]\n{block.content}" for block in enriched.blocks
        )
        effective = await prepare_effective_context(
            intent,
            conversation_id,
            memory,
            tools,
            context_text,
            images,
            owner_id,
            persistent_memory_text,
            project_id=project_id,
            run_id=run_id,
            memory_ids=memory_ids,
            skill_ids=enriched.manifest.skill_ids,
            current_message_id=current_message_id,
            asset_hmac_key=derive_context_asset_hmac_key(application_secret),
        )
        capability_references: list[CapabilityContextRef] = []
        for definition in tools.definitions():
            tool = tools.get_tool(definition.name)
            if tool is None:
                continue
            schema_document = json.dumps(
                _plain_json(definition.input_schema),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            capability_references.append(
                CapabilityContextRef(
                    capability_id=str(tool.capability_id or definition.name),
                    name=definition.name,
                    permission="ask" if tool.requires_approval else "allow",
                    reason=(
                        "provider_visible_requires_approval"
                        if tool.requires_approval
                        else "provider_visible_after_scope_policy"
                    ),
                    schema_hash=hashlib.sha256(schema_document).hexdigest(),
                )
            )
        selected_capability_ids = tuple(
            dict.fromkeys(
                (
                    *enriched.manifest.selected_capability_ids,
                    *(item.capability_id for item in capability_references),
                )
            )
        )
        effective = replace(
            effective,
            manifest=replace(
                effective.manifest,
                instruction_revisions=enriched.manifest.instruction_revisions,
                skill_revisions=enriched.manifest.skill_revisions,
                capability_references=tuple(capability_references),
                selected_capability_ids=selected_capability_ids,
                rejected_capability_ids=enriched.manifest.rejected_capability_ids,
                context_cost_bytes=enriched.manifest.context_cost_bytes,
            ),
        )
        effective, stats = await compact_effective_context(effective, max_tokens=max_tokens)
        await self.snapshots.record(effective.manifest)
        used = tuple(
            {
                "name": item.capability_id,
                "revision_id": item.revision_id,
                "reason": ",".join(item.reasons) or "selected",
            }
            for item in effective.manifest.skill_revisions
        )
        return PreparedRequestContext(effective, stats, used, decisions, disabled)
