"""Deterministic pure resolver for typed effective-context blocks."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import IntEnum

from app.instructions.loaders import InstructionSource


class InstructionConflictError(ValueError):
    """Structural input conflict that must not be silently merged."""


class ContextLayer(IntEnum):
    """Low numeric values have higher authority and appear first."""

    SYSTEM = 10
    PROJECT_INSTRUCTION = 20
    PINNED_SKILL = 30
    SELECTED_SKILL = 40
    USER_TASK = 50


@dataclass(frozen=True, slots=True)
class ResolvableBlock:
    layer: ContextLayer
    identifier: str
    content: str
    scope_path: str = "."
    revision: str | None = None
    reason: str = "configured"
    source: str = "managed"


@dataclass(frozen=True, slots=True)
class ResolvedBlock:
    layer: ContextLayer
    identifier: str
    content: str
    source: str
    scope_path: str
    revision: str | None
    content_hash: str
    reason: str
    context_cost_bytes: int


@dataclass(frozen=True, slots=True)
class EffectiveContext:
    blocks: tuple[ResolvedBlock, ...]
    omitted: tuple[str, ...]
    context_cost_bytes: int


def resolve_effective_context(
    *,
    system: list[ResolvableBlock] | tuple[ResolvableBlock, ...] = (),
    project_instructions: list[InstructionSource] | tuple[InstructionSource, ...] = (),
    pinned_skills: list[ResolvableBlock] | tuple[ResolvableBlock, ...] = (),
    selected_skills: list[ResolvableBlock] | tuple[ResolvableBlock, ...] = (),
    user_task: str,
    max_context_bytes: int | None = None,
) -> EffectiveContext:
    """Order blocks without semantic merging and apply a deterministic byte budget."""
    if max_context_bytes is not None and max_context_bytes < 0:
        raise ValueError("max_context_bytes must be non-negative")
    project = [
        ResolvableBlock(
            layer=ContextLayer.PROJECT_INSTRUCTION,
            identifier=item.relative_path,
            content=item.content,
            scope_path=item.scope_path,
            revision=item.content_hash,
            reason="root_to_leaf",
            source="project_instruction",
        )
        for item in project_instructions
    ]
    user = ResolvableBlock(
        ContextLayer.USER_TASK,
        "user-task",
        user_task,
        reason="current_request",
        source="user",
    )
    ordered = [
        *sorted(system, key=lambda item: item.identifier),
        *sorted(project, key=lambda item: (_scope_depth(item.scope_path), item.identifier)),
        *sorted(pinned_skills, key=lambda item: item.identifier),
        *sorted(selected_skills, key=lambda item: item.identifier),
        user,
    ]
    _reject_duplicates(ordered)
    resolved = tuple(_resolve(item) for item in ordered)
    if max_context_bytes is None:
        return EffectiveContext(resolved, (), sum(item.context_cost_bytes for item in resolved))

    mandatory_ids = {
        item.identifier
        for item in resolved
        if item.layer in {ContextLayer.SYSTEM, ContextLayer.USER_TASK}
    }
    mandatory_cost = sum(x.context_cost_bytes for x in resolved if x.identifier in mandatory_ids)
    if mandatory_cost > max_context_bytes:
        raise ValueError("context budget cannot fit mandatory system and user blocks")
    remaining = max_context_bytes - mandatory_cost
    kept_ids = set(mandatory_ids)
    omitted: list[str] = []
    for item in resolved:
        if item.identifier in mandatory_ids:
            continue
        if item.context_cost_bytes <= remaining:
            kept_ids.add(item.identifier)
            remaining -= item.context_cost_bytes
        else:
            omitted.append(item.identifier)
    kept = tuple(item for item in resolved if item.identifier in kept_ids)
    return EffectiveContext(kept, tuple(omitted), sum(x.context_cost_bytes for x in kept))


def _resolve(item: ResolvableBlock) -> ResolvedBlock:
    raw = item.content.encode("utf-8")
    return ResolvedBlock(
        layer=item.layer,
        identifier=item.identifier,
        content=item.content,
        source=item.source,
        scope_path=item.scope_path,
        revision=item.revision,
        content_hash=hashlib.sha256(raw).hexdigest(),
        reason=item.reason,
        context_cost_bytes=len(raw),
    )


def _reject_duplicates(items: list[ResolvableBlock]) -> None:
    seen: set[tuple[ContextLayer, str]] = set()
    for item in items:
        key = (item.layer, item.identifier)
        if key in seen:
            raise InstructionConflictError(f"duplicate block: {item.identifier}")
        seen.add(key)


def _scope_depth(scope: str) -> int:
    return 0 if scope == "." else len(scope.split("/"))
