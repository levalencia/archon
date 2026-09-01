"""Durable metadata-first skill discovery and bounded lazy loading."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from app.capabilities.index import CapabilityIndex
from app.capabilities.models import CapabilityDescriptor, PermissionDecision
from app.capabilities.selector import SelectionRequest, select_capabilities
from app.skills.bundled import ARCHON_OWNER_ID
from app.skills.catalog import ExternalSkillMetadata, SkillCatalogProvider
from app.skills.parser import parse_skill_markdown
from app.skills.persistence import SkillRepository


@dataclass(frozen=True, slots=True)
class DiscoveryRequest:
    owner_id: str
    project_id: str
    intent: str
    explicit_ids: tuple[str, ...] = ()
    permission_decisions: Mapping[str, PermissionDecision | str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    context_budget: int = 16_384
    limit: int | None = None
    current_path: str | None = None
    disabled_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DiscoveryCandidate:
    capability_id: str
    revision_id: str
    package_id: str
    metadata: Mapping[str, Any]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    candidates: tuple[DiscoveryCandidate, ...]
    selected: tuple[DiscoveryCandidate, ...]
    rejected: tuple[DiscoveryCandidate, ...]
    hidden_ids: tuple[str, ...]
    context_cost: int
    available: tuple[ExternalSkillMetadata, ...] = ()

    @property
    def visible_ids(self) -> tuple[str, ...]:
        return tuple(item.capability_id for item in self.candidates)


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    capability_id: str
    revision_id: str
    content: str
    content_hash: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedReference:
    revision_id: str
    path: str
    content: str
    content_hash: str
    byte_count: int


class SkillDiscoveryService:
    def __init__(
        self, repository: SkillRepository, catalog_provider: SkillCatalogProvider | None = None
    ) -> None:
        self._repository = repository
        self._catalog_provider = catalog_provider

    @property
    def repository(self) -> SkillRepository:
        return self._repository

    async def discover(self, request: DiscoveryRequest) -> DiscoveryResult:
        rows = await self._repository.list_project_discoverable(
            owner_id=request.owner_id, project_id=request.project_id
        )
        pins = set(
            await self._repository.list_pin_ids(
                owner_id=request.owner_id, project_id=request.project_id
            )
        )
        descriptors: list[CapabilityDescriptor] = []
        by_id: dict[str, Any] = {}
        for row in rows:
            parsed = parse_skill_markdown(row.content.encode("utf-8"))
            prefix = "archon" if row.owner_id == ARCHON_OWNER_ID else "owner"
            capability_id = f"{prefix}.{parsed.name}"
            descriptor = CapabilityDescriptor(
                id=capability_id,
                kind="skill",
                name=parsed.name,
                description=row.description,
                triggers=tuple(json.loads(row.triggers_json)),
                negative_triggers=tuple(json.loads(row.negative_triggers_json)),
                tags=tuple(json.loads(row.tags_json)),
                # Skill metadata never grants tool permissions. Required capabilities
                # remain descriptive and are evaluated by the independent tool policy.
                context_cost=row.context_cost,
                priority=100 if row.id in pins else 0,
                version=row.declared_version,
                content_hash=row.content_hash,
            )
            if capability_id not in request.disabled_ids:
                descriptors.append(descriptor)
                by_id[capability_id] = row
        explicit = set(request.explicit_ids)
        if explicit - set(by_id):
            raise LookupError("explicit skill invocation is not visible in scope")
        pinned_ids = {cid for cid, row in by_id.items() if row.id in pins} | explicit
        selection = select_capabilities(
            CapabilityIndex(descriptors),
            SelectionRequest(
                intent=request.intent,
                pinned_ids=frozenset(pinned_ids),
                current_path=request.current_path,
                permission_decisions=request.permission_decisions,
                context_budget=request.context_budget,
                limit=request.limit,
            ),
        )

        def candidate(match: Any) -> DiscoveryCandidate:
            row = by_id[match.descriptor.id]
            metadata = {
                "name": match.descriptor.name,
                "description": match.descriptor.description,
                "version": match.descriptor.version,
                "tags": match.descriptor.tags,
                "triggers": match.descriptor.triggers,
                "negative_triggers": match.descriptor.negative_triggers,
                "required_capability_ids": tuple(json.loads(row.required_capability_ids_json)),
                "context_cost": match.descriptor.context_cost,
                "content_hash": match.descriptor.content_hash,
            }
            return DiscoveryCandidate(
                match.descriptor.id, row.id, row.package_id, metadata, match.reasons
            )

        chosen = tuple(candidate(item) for item in selection.selected)
        rejected = tuple(candidate(item) for item in selection.rejected)
        visible = tuple(sorted((*chosen, *rejected), key=lambda item: item.capability_id))
        available = (
            ()
            if self._catalog_provider is None
            else await self._catalog_provider.search(request.intent, limit=request.limit or 20)
        )
        return DiscoveryResult(
            visible, chosen, rejected, selection.hidden_ids, selection.context_cost, available
        )

    async def load_selected(
        self, *, owner_id: str, project_id: str, revision_id: str
    ) -> LoadedSkill:
        row = await self._repository.get_project_visible_revision(
            owner_id=owner_id, project_id=project_id, revision_id=revision_id
        )
        parsed = parse_skill_markdown(row.content.encode("utf-8"))
        prefix = "archon" if row.owner_id == ARCHON_OWNER_ID else "owner"
        return LoadedSkill(
            f"{prefix}.{parsed.name}",
            row.id,
            parsed.instructions,
            row.content_hash,
            parsed.references,
        )

    async def load_reference(
        self,
        *,
        owner_id: str,
        project_id: str,
        revision_id: str,
        path: str,
        disabled_ids: frozenset[str] = frozenset(),
        max_bytes: int = 16_384,
    ) -> LoadedReference:
        if not 1 <= max_bytes <= 65_536:
            raise ValueError("max_bytes must be between 1 and 65536")
        revision = await self._repository.get_project_visible_revision(
            owner_id=owner_id, project_id=project_id, revision_id=revision_id
        )
        parsed = parse_skill_markdown(revision.content.encode("utf-8"))
        prefix = "archon" if revision.owner_id == ARCHON_OWNER_ID else "owner"
        if f"{prefix}.{parsed.name}" in disabled_ids:
            raise PermissionError("skill is disabled in the current scope")
        row = await self._repository.get_reference(
            owner_id=owner_id,
            project_id=project_id,
            revision_id=revision_id,
            path=path,
            max_bytes=max_bytes,
        )
        return LoadedReference(
            row.revision_id, row.path, row.content, row.content_hash, row.byte_count
        )
