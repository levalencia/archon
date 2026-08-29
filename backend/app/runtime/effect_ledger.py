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
    ResourceKind,
    ResourcePattern,
    canonical_arguments_snapshot,
    canonical_tool_name,
)

IDENTITY_VERSION = 1
_MIN_SECRET_BYTES = 32
_EFFECT_ID = re.compile(r"^eff_v1_[0-9a-f]{64}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_IDENTITY_NESTING_DEPTH = 32
MAX_IDENTITY_NODES = 4096
MAX_IDENTITY_STRING_BYTES = 16 * 1024
MAX_CANONICAL_DOCUMENT_BYTES = 256 * 1024
MAX_IDENTITY_RESOURCES = 64
MAX_RESOURCE_PATTERN_BYTES = 2048


def _unicode_bytes(value: str, label: str, maximum: int) -> bytes:
    """Encode safe Unicode scalar text without reflecting attacker-controlled content."""

    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} must contain only Unicode scalar values") from None
    if len(encoded) > maximum:
        raise ValueError(f"{label} is too long")
    return encoded


class EffectState(StrEnum):
    """Closed durable lifecycle for an effect tombstone."""

    RESERVED = "reserved"
    COMMITTED = "committed"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"


def _identifier(value: str, label: str, maximum: int) -> str:
    _unicode_bytes(value, label, MAX_IDENTITY_STRING_BYTES)
    normalized = unicodedata.normalize("NFC", value)
    _unicode_bytes(normalized, label, MAX_IDENTITY_STRING_BYTES)
    if not normalized or normalized != normalized.strip():
        raise ValueError(f"{label} must be non-empty without surrounding whitespace")
    if len(normalized) > maximum:
        raise ValueError(f"{label} is too long")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{label} cannot contain control characters")
    return normalized


def _validate_canonical_value(value: object, label: str) -> None:
    """Bound JSON traversal iteratively before the recursive canonical snapshot is called."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    nodes = 0
    active: set[int] = set()
    # Events are value, mapping iterator, list iterator, and container leave markers.
    stack: list[tuple[str, object, int]] = [("value", value, 0)]
    while stack:
        event, current, depth = stack.pop()
        if event == "leave":
            active.remove(id(current))
            continue
        if event in {"mapping", "list"}:
            iterator = current
            try:
                item = next(iterator)  # type: ignore[arg-type]
            except StopIteration:
                continue
            stack.append((event, iterator, depth))
            if event == "mapping":
                key, child = item
                nodes += 1
                if nodes > MAX_IDENTITY_NODES:
                    raise ValueError(f"{label} is too complex")
                _unicode_bytes(key, f"{label} key", MAX_IDENTITY_STRING_BYTES)
            else:
                child = item
            stack.append(("value", child, depth))
            continue

        nodes += 1
        if nodes > MAX_IDENTITY_NODES:
            raise ValueError(f"{label} is too complex")
        if current is None or isinstance(current, (bool, int)):
            continue
        if isinstance(current, float):
            if current != current or current in {float("inf"), float("-inf")}:
                raise ValueError(f"{label} cannot contain NaN or infinity")
            continue
        if isinstance(current, str):
            _unicode_bytes(current, f"{label} string", MAX_IDENTITY_STRING_BYTES)
            continue
        if isinstance(current, (Mapping, list)):
            if depth >= MAX_IDENTITY_NESTING_DEPTH:
                raise ValueError(f"{label} exceeds maximum nesting depth")
            identity = id(current)
            if identity in active:
                raise ValueError(f"{label} cannot contain cycles")
            active.add(identity)
            stack.append(("leave", current, depth))
            if isinstance(current, Mapping):
                stack.append(("mapping", iter(current.items()), depth + 1))
            else:
                stack.append(("list", iter(current), depth + 1))
            continue
        raise TypeError(f"unsupported {label} value: {type(current).__name__}")


def _canonical_document(value: object, label: str) -> tuple[dict[str, object], bytes]:
    _validate_canonical_value(value, label)
    snapshot = canonical_arguments_snapshot(value)
    try:
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ValueError(f"{label} cannot be encoded as canonical JSON") from None
    if len(encoded) > MAX_CANONICAL_DOCUMENT_BYTES:
        raise ValueError(f"{label} canonical JSON is too large")
    return snapshot, encoded


def _canonical_json(value: object) -> bytes:
    """Encode an internally constructed, already validated identity document."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise ValueError("effect identity cannot be encoded as canonical JSON") from None


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
        _unicode_bytes(self.tool_name, "tool_name", MAX_IDENTITY_STRING_BYTES)
        canonical_name = canonical_tool_name(self.tool_name)
        object.__setattr__(self, "tool_name", _identifier(canonical_name, "tool_name", 255))

        arguments, arguments_json = _canonical_document(self.arguments, "arguments")
        schema, schema_json = _canonical_document(self.input_schema, "input schema")

        resources_list: list[ResourcePattern] = []
        resource_iterator = iter(self.resources)
        for _ in range(MAX_IDENTITY_RESOURCES + 1):
            try:
                resource = next(resource_iterator)
            except StopIteration:
                break
            if len(resources_list) == MAX_IDENTITY_RESOURCES:
                raise ValueError("resources exceeds maximum count")
            if not isinstance(resource, ResourcePattern):
                raise TypeError("resources must contain only ResourcePattern values")
            if not isinstance(resource.kind, ResourceKind):
                raise TypeError("resource kind must be a ResourceKind")
            _unicode_bytes(resource.kind.value, "resource kind", MAX_IDENTITY_STRING_BYTES)
            _unicode_bytes(resource.pattern, "resource pattern", MAX_RESOURCE_PATTERN_BYTES)
            resources_list.append(resource)
        resources = tuple(sorted(resources_list, key=lambda item: (item.kind.value, item.pattern)))
        if len(resources) != len(set(resources)):
            raise ValueError("resources cannot contain a duplicate canonical resource")

        # Detached snapshots prevent later caller mutation from changing the already-bound hashes.
        object.__setattr__(self, "arguments", MappingProxyType(arguments))
        object.__setattr__(self, "input_schema", MappingProxyType(schema))
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "_arguments_hash", hashlib.sha256(arguments_json).hexdigest())
        object.__setattr__(self, "_schema_hash", hashlib.sha256(schema_json).hexdigest())


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
        _unicode_bytes(self.tool_name, "tool_name", MAX_IDENTITY_STRING_BYTES)
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
