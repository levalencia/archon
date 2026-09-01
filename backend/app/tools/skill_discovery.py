"""Scope-bound governed tools for capability discovery and lazy references."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.capabilities.models import PermissionDecision
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
    ) -> None:
        self._service = service
        self._owner_id = owner_id
        self._project_id = project_id
        self._decisions = dict(permission_decisions)
        self._budget = context_budget
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
            )
        )
        self._selected = {item.revision_id for item in result.selected}
        return {
            "selected": [
                dict(
                    item.metadata,
                    capability_id=item.capability_id,
                    revision_id=item.revision_id,
                    reasons=item.reasons,
                )
                for item in result.selected
            ],
            "rejected": [
                {"capability_id": item.capability_id, "reasons": item.reasons}
                for item in result.rejected
            ],
            "context_cost": result.context_cost,
        }

    async def load_skill_reference(self, revision_id: str, path: str) -> dict[str, Any]:
        if revision_id not in self._selected:
            raise PermissionError("reference requires a skill selected in the current scope")
        item = await self._service.load_reference(
            owner_id=self._owner_id, revision_id=revision_id, path=path
        )
        return {
            "revision_id": item.revision_id,
            "path": item.path,
            "content": item.content,
            "content_hash": item.content_hash,
            "byte_count": item.byte_count,
        }


def register_skill_discovery_tools(
    registry: SecureToolRegistry, tools: GovernedSkillDiscoveryTools
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
