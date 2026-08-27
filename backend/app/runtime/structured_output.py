"""Immutable contracts for parsing and validating structured model responses."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

StructuredOutputErrorCode = Literal["malformed_json", "schema_mismatch"]


class StructuredOutputError(ValueError):
    """Typed failure raised when structured model output cannot be trusted."""

    def __init__(self, code: StructuredOutputErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


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


@dataclass(frozen=True, slots=True)
class ResponseContract:
    """Versioned JSON schema metadata paired with an authoritative validator."""

    schema_id: str
    schema_version: str
    json_schema: Mapping[str, Any]
    validator: Callable[[Any], Any] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.schema_id.strip():
            raise ValueError("schema_id must be nonblank")
        if not self.schema_version.strip():
            raise ValueError("schema_version must be nonblank")
        if not callable(self.validator):
            raise TypeError("validator must be callable")
        if not isinstance(self.json_schema, Mapping):
            raise TypeError("json_schema must be a mapping")
        object.__setattr__(self, "json_schema", _immutable_copy(self.json_schema))

    def parse_and_validate(self, text: str) -> Any:
        """Parse JSON and return only the validator's successful result."""
        try:
            parsed = json.loads(text, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise StructuredOutputError("malformed_json", "Response is not valid JSON") from exc

        try:
            return self.validator(parsed)
        except Exception as exc:
            raise StructuredOutputError(
                "schema_mismatch", "Response does not satisfy the declared schema"
            ) from exc
