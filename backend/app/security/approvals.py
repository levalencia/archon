"""Immutable values exchanged with runtime approval adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.security.policy import RiskClass, canonical_tool_name

_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


def _validate_binding(
    tool_call_id: str, tool_name: str, arguments_hash: str
) -> tuple[str, str, str]:
    if not isinstance(tool_call_id, str) or not tool_call_id:
        raise ValueError("tool_call_id must be non-empty")
    if not isinstance(arguments_hash, str) or not _HASH.fullmatch(arguments_hash):
        raise ValueError("arguments_hash must be a lowercase SHA-256 digest")
    canonical_name = canonical_tool_name(tool_name)
    if tool_name != canonical_name:
        raise ValueError("tool_name must be canonical")
    return tool_call_id, tool_name, arguments_hash


def _validate_reason_code(reason_code: str) -> str:
    if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
        raise ValueError("reason_code must be a sanitized lowercase identifier")
    return reason_code


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """An approval request bound to one exact native provider tool call."""

    tool_call_id: str
    tool_name: str
    arguments_hash: str
    risk_classes: frozenset[RiskClass] = field(default_factory=frozenset)
    matched_rule_id: str | None = None

    def __post_init__(self) -> None:
        call_id, name, digest = _validate_binding(
            self.tool_call_id, self.tool_name, self.arguments_hash
        )
        object.__setattr__(self, "tool_call_id", call_id)
        object.__setattr__(self, "tool_name", name)
        object.__setattr__(self, "arguments_hash", digest)
        object.__setattr__(
            self, "risk_classes", frozenset(RiskClass(risk) for risk in self.risk_classes)
        )
        if self.matched_rule_id is not None and (
            not isinstance(self.matched_rule_id, str) or not self.matched_rule_id
        ):
            raise ValueError("matched_rule_id must be non-empty when supplied")


@dataclass(frozen=True, slots=True)
class AuthorizationOutcome:
    """A decision carrying the exact binding it authorizes or denies."""

    approved: bool
    tool_call_id: str
    tool_name: str
    arguments_hash: str
    reason_code: str

    def __post_init__(self) -> None:
        if type(self.approved) is not bool:
            raise TypeError("approved must be a bool")
        call_id, name, digest = _validate_binding(
            self.tool_call_id, self.tool_name, self.arguments_hash
        )
        object.__setattr__(self, "tool_call_id", call_id)
        object.__setattr__(self, "tool_name", name)
        object.__setattr__(self, "arguments_hash", digest)
        object.__setattr__(self, "reason_code", _validate_reason_code(self.reason_code))

    def binds(self, request: AuthorizationRequest) -> bool:
        return (
            self.tool_call_id == request.tool_call_id
            and self.tool_name == request.tool_name
            and self.arguments_hash == request.arguments_hash
        )
