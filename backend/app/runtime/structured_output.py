"""Immutable contracts for parsing and validating structured model responses."""

from __future__ import annotations

import json
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


def _immutable_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _immutable_copy(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable_copy(item) for item in value)
    if isinstance(value, set):
        return frozenset(_immutable_copy(item) for item in value)
    return value


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
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise StructuredOutputError("malformed_json", "Response is not valid JSON") from exc

        try:
            return self.validator(parsed)
        except Exception as exc:
            raise StructuredOutputError(
                "schema_mismatch", "Response does not satisfy the declared schema"
            ) from exc
