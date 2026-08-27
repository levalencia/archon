"""Pure HMAC-bound identity for durable external effects.

Only :class:`EffectBinding` crosses the persistence boundary. Raw arguments, resource
patterns, schemas, and the HMAC key intentionally are not represented by that safe DTO.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.security.policy import (
    ResourcePattern,
    canonical_arguments_hash,
    canonical_arguments_snapshot,
    canonical_tool_name,
)

IDENTITY_VERSION = 1
_MIN_SECRET_BYTES = 32
_EFFECT_ID = re.compile(r"^eff_v1_[0-9a-f]{64}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class EffectState(StrEnum):
    """Closed durable lifecycle for an effect tombstone."""

    RESERVED = "reserved"
    COMMITTED = "committed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


def _identifier(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip():
        raise ValueError(f"{label} must be non-empty without surrounding whitespace")
    if len(normalized) > maximum:
        raise ValueError(f"{label} is too long")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{label} cannot contain control characters")
    return normalized


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class EffectIdentityInput:
    """Validated inputs to a version-1 effect identity.

    ``tool_call_id`` is accepted as routing context to make its deliberate exclusion from
    identity explicit. Provider retries may assign a new call ID to the same logical effect.
    """

    owner_id: str
    project_id: str
    run_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    resources: tuple[ResourcePattern, ...] = field(default_factory=tuple, repr=False)
    input_schema: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)
    tool_call_id: str | None = field(default=None, repr=False, compare=False)
    _arguments_hash: str = field(init=False, repr=False)
    _schema_hash: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id", 255))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id", 255))
        object.__setattr__(self, "run_id", _identifier(self.run_id, "run_id", 36))
        canonical_name = canonical_tool_name(self.tool_name)
        object.__setattr__(self, "tool_name", _identifier(canonical_name, "tool_name", 255))

        arguments = canonical_arguments_snapshot(self.arguments)
        schema = canonical_arguments_snapshot(self.input_schema)
        resources = tuple(self.resources)
        if not all(isinstance(resource, ResourcePattern) for resource in resources):
            raise TypeError("resources must contain only ResourcePattern values")
        resources = tuple(sorted(resources, key=lambda item: (item.kind.value, item.pattern)))
        if len(resources) != len(set(resources)):
            raise ValueError("resources cannot contain a duplicate canonical resource")

        # Detached snapshots prevent later caller mutation from changing the already-bound hashes.
        object.__setattr__(self, "arguments", MappingProxyType(arguments))
        object.__setattr__(self, "input_schema", MappingProxyType(schema))
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "_arguments_hash", canonical_arguments_hash(arguments))
        object.__setattr__(
            self, "_schema_hash", hashlib.sha256(_canonical_json(schema)).hexdigest()
        )


@dataclass(frozen=True, slots=True)
class EffectBinding:
    """Safe metadata sufficient to reserve an effect; contains no effect payload."""

    effect_id: str
    identity_version: int
    owner_id: str
    project_id: str
    run_id: str
    tool_name: str
    schema_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.effect_id, str) or not _EFFECT_ID.fullmatch(self.effect_id):
            raise ValueError("effect_id must be a version-1 effect digest")
        if self.identity_version != IDENTITY_VERSION:
            raise ValueError("unsupported effect identity version")
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id", 255))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "project_id", 255))
        object.__setattr__(self, "run_id", _identifier(self.run_id, "run_id", 36))
        canonical_name = canonical_tool_name(self.tool_name)
        object.__setattr__(self, "tool_name", _identifier(canonical_name, "tool_name", 255))
        if not isinstance(self.schema_hash, str) or not _HASH.fullmatch(self.schema_hash):
            raise ValueError("schema_hash must be a lowercase SHA-256 digest")


def bind_effect_identity(identity: EffectIdentityInput, secret: bytes) -> EffectBinding:
    """Return a safe HMAC identity binding for one logical external effect."""

    if not isinstance(identity, EffectIdentityInput):
        raise TypeError("identity must be an EffectIdentityInput")
    if not isinstance(secret, bytes):
        raise TypeError("effect identity secret must be bytes")
    if len(secret) < _MIN_SECRET_BYTES:
        raise ValueError("effect identity secret must contain at least 32 bytes")
    document = {
        "arguments_hash": identity._arguments_hash,
        "identity_version": IDENTITY_VERSION,
        "owner_id": identity.owner_id,
        "project_id": identity.project_id,
        "resources": [
            {"kind": resource.kind.value, "pattern": resource.pattern}
            for resource in identity.resources
        ],
        "run_id": identity.run_id,
        "schema_hash": identity._schema_hash,
        "tool_name": identity.tool_name,
    }
    digest = hmac.new(secret, _canonical_json(document), hashlib.sha256).hexdigest()
    return EffectBinding(
        effect_id=f"eff_v1_{digest}",
        identity_version=IDENTITY_VERSION,
        owner_id=identity.owner_id,
        project_id=identity.project_id,
        run_id=identity.run_id,
        tool_name=identity.tool_name,
        schema_hash=identity._schema_hash,
    )


# Explicit discoverable alias for callers that use "compute" terminology.
compute_effect_binding = bind_effect_identity
