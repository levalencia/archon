"""Scope-bound governed tools for capability discovery and lazy references."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.capabilities.models import PermissionDecision
from app.mcp.runtime import MCPRuntimeToolMetadata
from app.security.policy import RiskClass
from app.skills.discovery import DiscoveryRequest, SkillDiscoveryService
from app.tools.registry import SecureToolRegistry


class GovernedSkillDiscoveryTools:
    def __init__(
        self,
        service: SkillDiscoveryService,
        *,
        owner_id: str,
        project_id: str,
        permission_decisions: Mapping[str, PermissionDecision | str],
        context_budget: int = 16_384,
        mcp_metadata: Sequence[MCPRuntimeToolMetadata] = (),
        disabled_ids: frozenset[str] = frozenset(),
    ) -> None:
        self._service = service
        self._owner_id = owner_id
        self._project_id = project_id
        self._decisions = dict(permission_decisions)
        self._budget = context_budget
        self._mcp_metadata = tuple(mcp_metadata)
        self._disabled_ids = frozenset(disabled_ids)
        self._selected: set[str] = set()

    async def discover_capabilities(self, intent: str, explicit_id: str = "") -> dict[str, Any]:
        result = await self._service.discover(
            DiscoveryRequest(
                owner_id=self._owner_id,
                project_id=self._project_id,
                intent=intent,
                explicit_ids=(explicit_id,) if explicit_id else (),
                permission_decisions=self._decisions,
                context_budget=self._budget,
                disabled_ids=self._disabled_ids,
            )
        )
        self._selected = {item.revision_id for item in result.selected}
        intent_words = set(re.findall(r"[a-z0-9]+", intent.casefold()))
        mcp = []
        for item in self._mcp_metadata:
            words = set(
                re.findall(
                    r"[a-z0-9]+",
                    f"{item.name} {item.title or ''} {item.description}".casefold(),
                )
            )
            if explicit_id == item.capability_id or intent_words.intersection(words):
                mcp.append(
                    {
                        "capability_id": item.capability_id,
                        "kind": "mcp",
                        "name": item.name,
                        "title": item.title,
                        "description": item.description,
                        "read_only": item.read_only,
                        "destructive": item.destructive,
                        "version": item.version,
                        "schema_hash": item.schema_hash,
                        "authorized": False,
                    }
                )
        return {
            "selected": [
                dict(
                    item.metadata,
                    capability_id=item.capability_id,
                    revision_id=item.revision_id,
                    reasons=item.reasons,
                )
                for item in result.selected
            ]
            + sorted(mcp, key=lambda item: str(item["capability_id"])),
            "rejected": [
                {"capability_id": item.capability_id, "reasons": item.reasons}
                for item in result.rejected
            ],
            # External results are summaries marked available. They are never selected,
            # enabled, loaded, or treated as permission-bearing skill content.
            "available": [
                {
                    "external_id": item.external_id,
                    "name": item.name,
                    "description": item.description,
                    "source_url": item.source_url,
                    "repository": item.repository,
                    "path": item.path,
                    "revision": item.revision,
                    "status": "available",
                    "source_label": "agent-god-mode",
                }
                for item in result.available
            ],
            "context_cost": result.context_cost,
        }

    async def load_skill_reference(self, revision_id: str, path: str) -> dict[str, Any]:
        if revision_id not in self._selected:
            raise PermissionError("reference requires a skill selected in the current scope")
        item = await self._service.load_reference(
            owner_id=self._owner_id,
            project_id=self._project_id,
            revision_id=revision_id,
            path=path,
            disabled_ids=self._disabled_ids,
        )
        return {
            "revision_id": item.revision_id,
            "path": item.path,
            "content": item.content,
            "content_hash": item.content_hash,
            "byte_count": item.byte_count,
        }


def register_skill_discovery_tools(
    registry: SecureToolRegistry,
    tools: GovernedSkillDiscoveryTools,
    *,
    include_reference: bool = True,
) -> None:
    registry.register(
        name="discover_capabilities",
        handler=tools.discover_capabilities,
        description="Discover policy-visible capabilities from durable metadata",
        required_permissions=["discover_capabilities"],
        input_schema={
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "explicit_id": {"type": "string"},
            },
            "required": ["intent"],
            "additionalProperties": False,
        },
        risk_classes=frozenset({RiskClass.READ}),
    )
    if not include_reference:
        return
    registry.register(
        name="load_skill_reference",
        handler=tools.load_skill_reference,
        description="Load one bounded reference for a selected skill revision",
        required_permissions=["load_skill_reference"],
        input_schema={
            "type": "object",
            "properties": {
                "revision_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["revision_id", "path"],
            "additionalProperties": False,
        },
        risk_classes=frozenset({RiskClass.READ}),
    )
