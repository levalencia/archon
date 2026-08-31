"""Immutable contracts for parsing and validating structured model responses."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

StructuredOutputErrorCode = Literal["malformed_json", "schema_mismatch"]
_MAX_SCHEMA_BYTES = 32_768
_DEFAULT_MAX_OUTPUT_BYTES = 1_048_576
_DEFAULT_MAX_DEPTH = 64
_DEFAULT_MAX_NODES = 20_000


class StructuredOutputError(ValueError):
    """Typed failure raised when structured model output cannot be trusted."""

    def __init__(self, code: StructuredOutputErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object key")
        value[key] = item
    return value


def _immutable_copy(value: Any, *, seen: frozenset[int] = frozenset()) -> Any:
    """Copy JSON-compatible values into immutable containers and reject cycles/leaves."""
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("json_schema numbers must be finite")
        return value
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in seen:
            raise TypeError("json_schema must not contain cycles")
        nested_seen = seen | {identity}
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise TypeError("json_schema mapping keys must be strings")
            return MappingProxyType(
                {key: _immutable_copy(item, seen=nested_seen) for key, item in value.items()}
            )
        return tuple(_immutable_copy(item, seen=nested_seen) for item in value)
    raise TypeError(f"json_schema contains unsupported value type: {type(value).__name__}")


def _plain_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_copy(item) for item in value]
    return value


def _reject_remote_references(value: Any) -> None:
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#"):
            raise ValueError("remote JSON Schema references are prohibited")
        for item in value.values():
            _reject_remote_references(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_remote_references(item)


def _validate_bounds(value: Any, *, max_depth: int, max_nodes: int) -> None:
    stack = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ValueError("structured output exceeds complexity limits")
        if isinstance(current, Mapping):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)


@dataclass(frozen=True, slots=True)
class ResponseContract:
    """Versioned JSON Schema plus an authoritative strict local validator."""

    schema_id: str
    schema_version: str
    json_schema: Mapping[str, Any]
    validator: Callable[[Any], Any] = field(repr=False, compare=False)
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES
    max_depth: int = _DEFAULT_MAX_DEPTH
    max_nodes: int = _DEFAULT_MAX_NODES

    def __post_init__(self) -> None:
        if not self.schema_id.strip():
            raise ValueError("schema_id must be nonblank")
        if not self.schema_version.strip():
            raise ValueError("schema_version must be nonblank")
        if not callable(self.validator):
            raise TypeError("validator must be callable")
        if not isinstance(self.json_schema, Mapping):
            raise TypeError("json_schema must be a mapping")
        if not 1 <= self.max_output_bytes <= 4_194_304:
            raise ValueError("max_output_bytes must be between 1 and 4194304")
        if not 1 <= self.max_depth <= 128 or not 1 <= self.max_nodes <= 100_000:
            raise ValueError("structured output complexity limits are invalid")

        immutable = _immutable_copy(self.json_schema)
        plain = _plain_copy(immutable)
        encoded = json.dumps(plain, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > _MAX_SCHEMA_BYTES:
            raise ValueError("json_schema exceeds the size limit")
        _reject_remote_references(plain)
        try:
            Draft202012Validator.check_schema(plain)
        except SchemaError as exc:
            raise ValueError("json_schema is invalid") from exc
        object.__setattr__(self, "json_schema", immutable)

    def parse_and_validate(self, text: str) -> Any:
        """Return only a bounded JSON value accepted by schema and domain validator."""
        if not isinstance(text, str) or len(text.encode("utf-8")) > self.max_output_bytes:
            raise StructuredOutputError("malformed_json", "Response is not valid JSON")
        try:
            parsed = json.loads(
                text,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_object_without_duplicates,
            )
            _validate_bounds(parsed, max_depth=self.max_depth, max_nodes=self.max_nodes)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise StructuredOutputError("malformed_json", "Response is not valid JSON") from exc

        try:
            Draft202012Validator(_plain_copy(self.json_schema)).validate(parsed)
            return self.validator(parsed)
        except Exception as exc:
            raise StructuredOutputError(
                "schema_mismatch", "Response does not satisfy the declared schema"
            ) from exc
