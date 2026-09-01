"""Deterministic policy-first capability selection with context budgeting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.capabilities.index import CapabilityIndex
from app.capabilities.models import CapabilityDescriptor, PermissionDecision

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class SelectionRequest:
    intent: str
    pinned_ids: frozenset[str] = frozenset()
    current_path: str | None = None
    permission_decisions: Mapping[str, PermissionDecision | str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    context_budget: int = 0
    limit: int | None = None

    def __post_init__(self) -> None:
        if self.context_budget < 0:
            raise ValueError("context_budget must be non-negative")
        if self.limit is not None and self.limit < 0:
            raise ValueError("limit must be non-negative")


@dataclass(frozen=True, slots=True)
class CapabilityMatch:
    descriptor: CapabilityDescriptor
    score: int
    reasons: tuple[str, ...]
    requires_approval: bool = False


@dataclass(frozen=True, slots=True)
class SelectionResult:
    selected: tuple[CapabilityMatch, ...]
    rejected: tuple[CapabilityMatch, ...]
    hidden_ids: tuple[str, ...]
    context_cost: int


def select_capabilities(index: CapabilityIndex, request: SelectionRequest) -> SelectionResult:
    """Filter deny before visibility, then score and budget visible descriptors."""
    intent = _normalize(request.intent)
    intent_words = set(_WORD_RE.findall(intent))
    hidden: list[str] = []
    candidates: list[CapabilityMatch] = []
    rejected: list[CapabilityMatch] = []

    for descriptor in index.all():
        if not descriptor.enabled:
            hidden.append(descriptor.id)
            continue
        decisions = {
            permission: PermissionDecision(request.permission_decisions.get(permission, "deny"))
            for permission in descriptor.required_permissions
        }
        if any(value is PermissionDecision.DENY for value in decisions.values()):
            hidden.append(descriptor.id)
            continue
        negative = next(
            (
                trigger
                for trigger in descriptor.negative_triggers
                if _contains_phrase(intent, _normalize(trigger))
            ),
            None,
        )
        if negative is not None:
            rejected.append(CapabilityMatch(descriptor, 0, (f"negative_trigger:{negative}",)))
            continue
        if not _path_matches(descriptor.path_scopes, request.current_path):
            rejected.append(CapabilityMatch(descriptor, 0, ("path_scope",)))
            continue

        reasons: list[str] = []
        score = descriptor.priority
        if descriptor.id in request.pinned_ids:
            score += 10_000
            reasons.append("project_pin")
        for trigger in descriptor.triggers:
            normalized = _normalize(trigger)
            if normalized and _contains_phrase(intent, normalized):
                score += 100 + len(_WORD_RE.findall(normalized)) * 10
                reasons.append(f"trigger:{trigger}")
        metadata_words = set(
            _WORD_RE.findall(
                _normalize(
                    f"{descriptor.name} {descriptor.description} {' '.join(descriptor.tags)}"
                )
            )
        )
        overlap = len(intent_words & metadata_words)
        if overlap:
            score += overlap
            reasons.append(f"metadata_overlap:{overlap}")
        if descriptor.path_scopes:
            score += 25
            reasons.append("path_scope_match")
        asking = tuple(key for key, value in decisions.items() if value is PermissionDecision.ASK)
        reasons.extend(f"permission_ask:{key}" for key in asking)
        match = CapabilityMatch(descriptor, score, tuple(reasons), bool(asking))
        if score > 0:
            candidates.append(match)
        else:
            rejected.append(CapabilityMatch(descriptor, 0, ("not_relevant",), bool(asking)))

    candidates.sort(key=lambda item: (-item.score, item.descriptor.id))
    selected: list[CapabilityMatch] = []
    spent = 0
    for match in candidates:
        if request.limit is not None and len(selected) >= request.limit:
            rejected.append(
                CapabilityMatch(
                    match.descriptor, match.score, ("selection_limit",), match.requires_approval
                )
            )
        elif spent + match.descriptor.context_cost > request.context_budget:
            rejected.append(
                CapabilityMatch(
                    match.descriptor, match.score, ("context_budget",), match.requires_approval
                )
            )
        else:
            selected.append(match)
            spent += match.descriptor.context_cost
    rejected.sort(key=lambda item: item.descriptor.id)
    return SelectionResult(tuple(selected), tuple(rejected), tuple(sorted(hidden)), spent)


def _normalize(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold()))


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {text} "


def _path_matches(scopes: tuple[str, ...], current_path: str | None) -> bool:
    if not scopes:
        return True
    if current_path is None:
        return False
    normalized = current_path.replace("\\", "/").strip("/")
    if ".." in normalized.split("/"):
        return False
    return any(
        scope == "." or normalized == scope or normalized.startswith(f"{scope}/")
        for scope in scopes
    )
