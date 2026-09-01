"""Typed metadata contracts for searchable skills and tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class CapabilityKind(StrEnum):
    SKILL = "skill"
    NATIVE = "native"
    MCP = "mcp"


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Compact metadata only; executable schema or full skill text lives elsewhere."""

    id: str
    kind: CapabilityKind | str
    name: str
    description: str
    triggers: tuple[str, ...] = ()
    negative_triggers: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    path_scopes: tuple[str, ...] = ()
    context_cost: int = 0
    priority: int = 0
    version: str | None = None
    content_hash: str | None = None
    enabled: bool = True
    executable_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", CapabilityKind(self.kind))
        if not _ID_RE.fullmatch(self.id):
            raise ValueError("invalid capability id")
        if not self.name.strip():
            raise ValueError("capability name must not be blank")
        if self.context_cost < 0:
            raise ValueError("context_cost must be non-negative")
        if self.executable_name is not None and (
            not self.executable_name.strip() or len(self.executable_name) > 128
        ):
            raise ValueError("invalid executable tool name")
        if any(
            not value.strip() for value in (*self.triggers, *self.negative_triggers, *self.tags)
        ):
            raise ValueError("capability metadata terms must not be blank")
        normalized_scopes = tuple(_scope(value) for value in self.path_scopes)
        object.__setattr__(self, "path_scopes", normalized_scopes)
        object.__setattr__(
            self, "required_permissions", tuple(sorted(set(self.required_permissions)))
        )


def _scope(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path scope must be canonical and relative")
    return path.as_posix().rstrip("/") or "."
