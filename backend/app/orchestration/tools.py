"""Capability-subset construction for child agents."""

from __future__ import annotations

from collections.abc import Iterable

from app.security.policy import RiskClass
from app.tools.registry import SecureToolRegistry

_FORBIDDEN_CHILD_RISKS = frozenset(
    {RiskClass.WRITE, RiskClass.EXECUTE, RiskClass.EXTERNAL_SIDE_EFFECT}
)


def build_read_only_registry(
    parent: SecureToolRegistry,
    allowed_tools: Iterable[str],
) -> SecureToolRegistry:
    """Copy only visible non-effectful tools into an isolated child registry."""

    child = SecureToolRegistry()
    for name in tuple(allowed_tools):
        tool = parent.get_tool(name)
        if tool is None:
            continue
        if tool.effectful or tool.risk_classes & _FORBIDDEN_CHILD_RISKS:
            continue
        child.register(
            name=tool.name,
            handler=tool.handler,
            description=tool.description,
            required_permissions=list(tool.required_permissions or ()),
            input_schema=dict(tool.input_schema or {}),
            timeout=tool.timeout,
            requires_approval=False,
            risk_classes=tool.risk_classes,
            resource_resolver=tool.resource_resolver,
            capability_id=tool.capability_id,
        )
    return child
