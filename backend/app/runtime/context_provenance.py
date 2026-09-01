"""Metadata-only provenance for the exact context selected for one model run."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from dataclasses import dataclass, replace
from typing import Any

from app.runtime.models import Message

_SCHEMA_VERSION = 1
_SUMMARY_VERSION = "auto-compact-v1"
_MAX_BIGINT = 2**63 - 1
_CONTEXT_NAMESPACE = uuid.UUID("8b8456c5-c42a-4a44-8e10-81bb742a35ec")


def _text(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a bounded non-empty string")
    value = unicodedata.normalize("NFC", value)
    if len(value) > maximum:
        raise ValueError(f"{label} must be a bounded non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} must contain Unicode scalar values") from None
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError(f"{label} must not contain control characters")
    return value


def _unique_text(values: tuple[str, ...], label: str, maximum: int) -> tuple[str, ...]:
    if len(values) > maximum:
        raise ValueError(f"{label} has too many values")
    normalized = tuple(_text(value, label, 255) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} values must be unique")
    return normalized


def _message_ids(values: tuple[int, ...], label: str) -> tuple[int, ...]:
    if len(values) > 10_000:
        raise ValueError(f"{label} has too many values")
    if any(type(value) is not int or value < 1 or value > _MAX_BIGINT for value in values):
        raise ValueError(f"{label} values must be positive integers")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} values must be unique")
    return values


@dataclass(frozen=True, slots=True)
class InstructionRevisionRef:
    revision_id: str
    content_hash: str
    order: int
    relative_path: str = ".archon/instructions.md"
    scope_path: str = "."
    family: str = "archon"
    is_override: bool = False
    byte_count: int = 0

    def __post_init__(self) -> None:
        _text(self.revision_id, "instruction revision_id", 255)
        _hash(self.content_hash, "instruction content_hash")
        _text(self.relative_path, "instruction relative_path", 1024)
        _text(self.scope_path, "instruction scope_path", 1024)
        if self.family not in {"archon", "agents", "claude", "manual"}:
            raise ValueError("invalid instruction family")
        if type(self.is_override) is not bool:
            raise ValueError("instruction is_override must be boolean")
        if type(self.order) is not int or self.order < 0:
            raise ValueError("instruction order must be non-negative")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise ValueError("instruction byte_count must be non-negative")


@dataclass(frozen=True, slots=True)
class SkillRevisionRef:
    capability_id: str
    revision_id: str
    content_hash: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.capability_id, "capability_id", 255)
        _text(self.revision_id, "skill revision_id", 255)
        _hash(self.content_hash, "skill content_hash")
        _unique_text(tuple(self.reasons), "skill reasons", 32)


def _hash(value: str, label: str) -> str:
    value = _text(value, label, 64)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be canonical SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class CapabilityContextRef:
    capability_id: str
    name: str
    permission: str
    reason: str
    schema_hash: str

    def __post_init__(self) -> None:
        _text(self.capability_id, "capability_id", 255)
        _text(self.name, "capability name", 255)
        if self.permission not in {"allow", "ask"}:
            raise ValueError("provider-visible capability permission must be allow or ask")
        _text(self.reason, "capability reason", 255)
        _hash(self.schema_hash, "capability schema_hash")


@dataclass(frozen=True, slots=True)
class EffectiveContextManifest:
    owner_id: str
    project_id: str
    run_id: str
    conversation_id: str
    selected_message_ids: tuple[int, ...] = ()
    summarized_message_ids: tuple[int, ...] = ()
    memory_ids: tuple[str, ...] = ()
    skill_ids: tuple[str, ...] = ()
    instruction_revisions: tuple[InstructionRevisionRef, ...] = ()
    skill_revisions: tuple[SkillRevisionRef, ...] = ()
    capability_references: tuple[CapabilityContextRef, ...] = ()
    selected_capability_ids: tuple[str, ...] = ()
    rejected_capability_ids: tuple[str, ...] = ()
    context_cost_bytes: int = 0
    input_asset_fingerprints: tuple[str, ...] = ()
    estimated_tokens: int = 0
    summary_version: str | None = None
    truncation_reason: str | None = None
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id", 255))
        object.__setattr__(self, "project_id", _text(self.project_id, "project_id", 255))
        object.__setattr__(self, "run_id", _text(self.run_id, "run_id", 36))
        object.__setattr__(
            self, "conversation_id", _text(self.conversation_id, "conversation_id", 255)
        )
        object.__setattr__(
            self,
            "selected_message_ids",
            _message_ids(tuple(self.selected_message_ids), "selected_message_ids"),
        )
        object.__setattr__(
            self,
            "summarized_message_ids",
            _message_ids(tuple(self.summarized_message_ids), "summarized_message_ids"),
        )
        if set(self.selected_message_ids) & set(self.summarized_message_ids):
            raise ValueError("selected and summarized message IDs must be disjoint")
        object.__setattr__(
            self, "memory_ids", _unique_text(tuple(self.memory_ids), "memory_ids", 1000)
        )
        object.__setattr__(self, "skill_ids", _unique_text(tuple(self.skill_ids), "skill_ids", 100))
        object.__setattr__(self, "instruction_revisions", tuple(self.instruction_revisions))
        object.__setattr__(self, "skill_revisions", tuple(self.skill_revisions))
        object.__setattr__(self, "capability_references", tuple(self.capability_references))
        object.__setattr__(
            self,
            "selected_capability_ids",
            _unique_text(tuple(self.selected_capability_ids), "selected_capability_ids", 100),
        )
        object.__setattr__(
            self,
            "rejected_capability_ids",
            _unique_text(tuple(self.rejected_capability_ids), "rejected_capability_ids", 100),
        )
        if (
            type(self.context_cost_bytes) is not int
            or not 0 <= self.context_cost_bytes <= _MAX_BIGINT
        ):
            raise ValueError("context_cost_bytes must be a non-negative integer")
        asset_fingerprints = _unique_text(
            tuple(self.input_asset_fingerprints), "input_asset_fingerprints", 16
        )
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in asset_fingerprints
        ):
            raise ValueError("input_asset_fingerprints must contain canonical HMAC-SHA256 values")
        object.__setattr__(self, "input_asset_fingerprints", asset_fingerprints)
        if type(self.estimated_tokens) is not int or not 0 <= self.estimated_tokens <= _MAX_BIGINT:
            raise ValueError("estimated_tokens must be a non-negative integer")
        if self.summary_version is not None:
            object.__setattr__(
                self, "summary_version", _text(self.summary_version, "summary_version", 64)
            )
        if self.truncation_reason is not None:
            object.__setattr__(
                self, "truncation_reason", _text(self.truncation_reason, "truncation_reason", 64)
            )
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError("unsupported context manifest schema version")

    @property
    def snapshot_id(self) -> str:
        identity = f"{self.owner_id}\0{self.project_id}\0{self.run_id}"
        return str(uuid.uuid5(_CONTEXT_NAMESPACE, identity))

    def semantic_document(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_id": self.owner_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "selected_message_ids": list(self.selected_message_ids),
            "summarized_message_ids": list(self.summarized_message_ids),
            "memory_ids": list(self.memory_ids),
            "skill_ids": list(self.skill_ids),
            "instruction_revisions": [
                {
                    "revision_id": item.revision_id,
                    "content_hash": item.content_hash,
                    "order": item.order,
                    "relative_path": item.relative_path,
                    "scope_path": item.scope_path,
                    "family": item.family,
                    "is_override": item.is_override,
                    "byte_count": item.byte_count,
                }
                for item in self.instruction_revisions
            ],
            "skill_revisions": [
                {
                    "capability_id": item.capability_id,
                    "revision_id": item.revision_id,
                    "content_hash": item.content_hash,
                    "reasons": list(item.reasons),
                }
                for item in self.skill_revisions
            ],
            "capability_references": [
                {
                    "capability_id": item.capability_id,
                    "name": item.name,
                    "permission": item.permission,
                    "reason": item.reason,
                    "schema_hash": item.schema_hash,
                }
                for item in self.capability_references
            ],
            "selected_capability_ids": list(self.selected_capability_ids),
            "rejected_capability_ids": list(self.rejected_capability_ids),
            "context_cost_bytes": self.context_cost_bytes,
            "input_asset_fingerprints": list(self.input_asset_fingerprints),
            "estimated_tokens": self.estimated_tokens,
            "summary_version": self.summary_version,
            "truncation_reason": self.truncation_reason,
        }

    @property
    def manifest_hash(self) -> str:
        encoded = json.dumps(
            self.semantic_document(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def with_current_message(self, message_id: int) -> EffectiveContextManifest:
        validated = _message_ids((message_id,), "current_message_id")[0]
        if validated in self.selected_message_ids or validated in self.summarized_message_ids:
            raise ValueError("current message ID must be unique")
        return replace(self, selected_message_ids=(*self.selected_message_ids, validated))

    def after_compaction(
        self,
        *,
        selected_message_ids: tuple[int, ...],
        summarized_message_ids: tuple[int, ...],
        estimated_tokens: int,
    ) -> EffectiveContextManifest:
        selected = _message_ids(selected_message_ids, "selected_message_ids")
        summarized = _message_ids(summarized_message_ids, "summarized_message_ids")
        before = set(self.selected_message_ids)
        if set(selected) & set(summarized) or set(selected) | set(summarized) != before:
            raise ValueError("compaction lineage must partition selected message IDs")
        return replace(
            self,
            selected_message_ids=selected,
            summarized_message_ids=summarized,
            estimated_tokens=estimated_tokens,
            summary_version=_SUMMARY_VERSION if summarized else None,
            truncation_reason="token_threshold" if summarized else None,
        )


@dataclass(frozen=True, slots=True)
class EffectiveContext:
    messages: tuple[Message, ...]
    source_message_ids: tuple[int | None, ...]
    manifest: EffectiveContextManifest

    def __post_init__(self) -> None:
        if len(self.messages) != len(self.source_message_ids):
            raise ValueError("context messages and source IDs must align")
        for source_id in self.source_message_ids:
            if source_id is not None:
                _message_ids((source_id,), "source_message_id")

    def with_current_message(self, message_id: int) -> EffectiveContext:
        if not self.messages or self.messages[-1].role.value != "user":
            raise ValueError("current user message is unavailable")
        source_ids = (*self.source_message_ids[:-1], message_id)
        return replace(
            self,
            source_message_ids=source_ids,
            manifest=self.manifest.with_current_message(message_id),
        )
