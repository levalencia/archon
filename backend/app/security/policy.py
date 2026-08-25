"""Pure, deterministic policy models and rule evaluation.

This module deliberately has no persistence, routing, filesystem I/O, or runtime dependencies.
Path normalization and matching are lexical only: they do not resolve symlinks or provide a
filesystem containment guarantee. Execution-layer resource resolvers must pass resolved,
canonical paths into policy evaluation and recheck containment immediately before execution to
protect against symlink changes and other TOCTOU races.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import posixpath
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import idna


class PolicyAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ApprovalScope(StrEnum):
    ONCE = "once"
    RUN = "run"
    SESSION = "session"
    RULE = "rule"


class RiskClass(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    SECRET = "secret"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"


class ResourceKind(StrEnum):
    TOOL = "tool"
    PATH = "path"
    HOST = "host"


def _text(value: str, label: str, *, strip: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{label} cannot contain control characters")
    value = unicodedata.normalize("NFC", value)
    if strip:
        value = value.strip()
    if not value:
        raise ValueError(f"{label} must be non-empty")
    return value


def _canonical_tool(value: str, *, pattern: bool) -> str:
    value = _text(value, "tool name").lower()
    if pattern and value == "*":
        return value
    if "*" in value:
        raise ValueError("tool wildcard must be exactly '*'")
    return value


def canonical_tool_name(value: str) -> str:
    """Return the canonical concrete tool identity used by policy and registries."""

    return _canonical_tool(value, pattern=False)


def _normalize_absolute_path(value: str) -> str:
    value = value.replace("\\", "/")
    if not value.startswith("/"):
        raise ValueError("path must be absolute")
    # posixpath intentionally resolves repeated separators and dot segments lexically.
    value = posixpath.normpath("/" + value.lstrip("/"))
    return value


def _canonical_path(value: str, *, pattern: bool) -> str:
    value = _text(value, "path", strip=False)
    if not pattern and "*" in value:
        raise ValueError("request resources must be concrete, not wildcard patterns")
    if "*" not in value:
        return _normalize_absolute_path(value)
    if not pattern:
        raise ValueError("request resources must be concrete, not wildcard patterns")
    value = value.replace("\\", "/")
    if value == "/**":
        return value
    if not value.endswith("/**") or "*" in value[:-3]:
        raise ValueError("path pattern must be exact, '/**', or end in '/**'")
    prefix = _normalize_absolute_path(value[:-3])
    return "/**" if prefix == "/" else f"{prefix}/**"


def _canonical_hostname(value: str) -> str:
    if any(marker in value for marker in ("/", "@", ":")):
        raise ValueError("host must not contain a URL, userinfo, or port")
    value = value.rstrip(".")
    if not value or value.startswith("."):
        raise ValueError("host must be non-empty and cannot start with a dot")
    try:
        ascii_host = idna.encode(value, uts46=True, std3_rules=True).decode("ascii").lower()
    except idna.IDNAError as error:
        raise ValueError("host is not valid IDNA") from error
    try:
        return str(ipaddress.IPv4Address(ascii_host))
    except ipaddress.AddressValueError:
        labels = ascii_host.split(".")
        if all(
            label.isdigit()
            or (
                label.startswith("0x")
                and len(label) > 2
                and all(character in "0123456789abcdef" for character in label[2:])
            )
            for label in labels
        ):
            raise ValueError("host is a noncanonical IPv4 numeric alias") from None
    if len(ascii_host) > 253:
        raise ValueError("host is too long")
    labels = ascii_host.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("host contains an invalid label")
    return ascii_host


def _canonical_host(value: str, *, pattern: bool) -> str:
    value = _text(value, "host").lower()
    if pattern and value == "*":
        return value
    if value.startswith("*.") and pattern:
        suffix = _canonical_hostname(value[2:])
        return f"*.{suffix}"
    if "*" in value:
        raise ValueError("host wildcard must be '*' or a leading '*.'")
    return _canonical_hostname(value)


def _canonical_resource(kind: ResourceKind, value: str, *, pattern: bool) -> str:
    if kind is ResourceKind.TOOL:
        return _canonical_tool(value, pattern=pattern)
    if kind is ResourceKind.PATH:
        return _canonical_path(value, pattern=pattern)
    return _canonical_host(value, pattern=pattern)


@dataclass(frozen=True, slots=True)
class ResourcePattern:
    """A canonical resource value, optionally containing a narrow rule wildcard.

    Path values are canonical only in the lexical policy-domain sense; see the module contract.
    """

    kind: ResourceKind
    pattern: str

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, ResourceKind) else ResourceKind(self.kind)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "pattern", _canonical_resource(kind, self.pattern, pattern=True))

    @property
    def is_wildcard(self) -> bool:
        return "*" in self.pattern


@dataclass(frozen=True, slots=True)
class PolicyRule:
    id: str
    action: PolicyAction
    resources: tuple[ResourcePattern, ...] = ()
    risk_classes: frozenset[RiskClass] = field(default_factory=frozenset)
    description: str = ""
    enabled: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _text(self.id, "rule id"))
        action = self.action if isinstance(self.action, PolicyAction) else PolicyAction(self.action)
        object.__setattr__(self, "action", action)
        resources = tuple(self.resources)
        if not all(isinstance(resource, ResourcePattern) for resource in resources):
            raise TypeError("rule resources must contain only ResourcePattern values")
        if len(resources) != len(set(resources)):
            raise ValueError("rule resources cannot contain a duplicate canonical resource")
        object.__setattr__(self, "resources", resources)
        object.__setattr__(
            self, "risk_classes", frozenset(RiskClass(risk) for risk in self.risk_classes)
        )
        if not isinstance(self.description, str):
            raise TypeError("rule description must be a string")
        if any(unicodedata.category(character).startswith("C") for character in self.description):
            raise ValueError("rule description cannot contain control characters")
        if type(self.enabled) is not bool:
            raise TypeError("rule enabled must be a bool")
        if (
            action in {PolicyAction.ALLOW, PolicyAction.ASK}
            and not resources
            and not self.risk_classes
        ):
            raise ValueError("ALLOW and ASK rules require explicit resources or risk classes")


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    tool_name: str
    resources: tuple[ResourcePattern, ...]
    risk_classes: frozenset[RiskClass]
    legacy_requires_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", _canonical_tool(self.tool_name, pattern=False))
        resources = tuple(self.resources)
        if not all(isinstance(resource, ResourcePattern) for resource in resources):
            raise TypeError("request resources must contain only ResourcePattern values")
        if any(resource.kind is ResourceKind.TOOL for resource in resources):
            raise ValueError(
                "request resources cannot contain TOOL entries; tool_name is the sole tool identity"
            )
        if any(resource.is_wildcard for resource in resources):
            raise ValueError("request resources must be concrete, not wildcard patterns")
        object.__setattr__(self, "resources", resources)
        object.__setattr__(
            self, "risk_classes", frozenset(RiskClass(risk) for risk in self.risk_classes)
        )
        if type(self.legacy_requires_approval) is not bool:
            raise TypeError("request legacy_requires_approval must be a bool")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    action: PolicyAction
    risk_classes: frozenset[RiskClass]
    matched_rule_id: str | None
    reason: str
    specificity: tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self) -> None:
        action = self.action if isinstance(self.action, PolicyAction) else PolicyAction(self.action)
        object.__setattr__(self, "action", action)
        object.__setattr__(
            self, "risk_classes", frozenset(RiskClass(risk) for risk in self.risk_classes)
        )


class PolicyEngine(Protocol):
    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        """Return a deterministic decision for a canonical request."""
        ...


def _resource_matches(rule_resource: ResourcePattern, request_resource: ResourcePattern) -> bool:
    if rule_resource.kind is not request_resource.kind:
        return False
    pattern = rule_resource.pattern
    concrete = request_resource.pattern
    if not rule_resource.is_wildcard:
        return pattern == concrete
    if rule_resource.kind is ResourceKind.TOOL:
        return True
    if rule_resource.kind is ResourceKind.PATH:
        if pattern == "/**":
            return True
        prefix = pattern[:-3]
        return concrete.startswith(f"{prefix}/")
    if pattern == "*":
        return True
    suffix = pattern[2:]
    return concrete.endswith(f".{suffix}") and concrete != suffix


def _specificity(rule: PolicyRule) -> tuple[int, int, int]:
    exact = sum(not resource.is_wildcard for resource in rule.resources)
    literal = sum(len(resource.pattern.replace("*", "")) for resource in rule.resources)
    return (exact, literal, int(bool(rule.risk_classes)))


@dataclass(frozen=True, slots=True)
class RulePolicyEngine:
    """Evaluate immutable rules using specificity and deterministic tie breaking."""

    rules: tuple[PolicyRule, ...]
    default_action: PolicyAction = PolicyAction.ALLOW

    def __init__(
        self,
        rules: Sequence[PolicyRule],
        default_action: PolicyAction = PolicyAction.ALLOW,
    ) -> None:
        immutable_rules = tuple(rules)
        rule_ids: set[str] = set()
        for rule in immutable_rules:
            if rule.id in rule_ids:
                raise ValueError(f"duplicate canonical rule id: {rule.id!r}")
            rule_ids.add(rule.id)
        object.__setattr__(self, "rules", immutable_rules)
        action = (
            default_action
            if isinstance(default_action, PolicyAction)
            else PolicyAction(default_action)
        )
        object.__setattr__(self, "default_action", action)

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        if not request.risk_classes:
            return PolicyDecision(
                PolicyAction.DENY,
                request.risk_classes,
                None,
                "unclassified request denied by safety fallback",
            )

        tool = ResourcePattern(ResourceKind.TOOL, request.tool_name)
        concrete_resources = (tool, *request.resources)
        matches: list[tuple[tuple[int, int, int], int, PolicyRule]] = []
        for index, rule in enumerate(self.rules):
            if not rule.enabled:
                continue
            if rule.risk_classes:
                if rule.action is PolicyAction.DENY:
                    if rule.risk_classes.isdisjoint(request.risk_classes):
                        continue
                elif not request.risk_classes.issubset(rule.risk_classes):
                    continue
            if not all(
                any(_resource_matches(rule_resource, concrete) for concrete in concrete_resources)
                for rule_resource in rule.resources
            ):
                continue
            matches.append((_specificity(rule), index, rule))

        if matches:
            best_specificity = max(item[0] for item in matches)
            tied = [item for item in matches if item[0] == best_specificity]
            deny_matches = [item for item in tied if item[2].action is PolicyAction.DENY]
            _, _, winner = (deny_matches or tied)[-1]
            detail = f": {winner.description}" if winner.description else ""
            return PolicyDecision(
                winner.action,
                request.risk_classes,
                winner.id,
                f"matched policy rule '{winner.id}'{detail}",
                best_specificity,
            )

        if request.legacy_requires_approval:
            return PolicyDecision(
                PolicyAction.ASK,
                request.risk_classes,
                None,
                "legacy approval requirement requested human approval",
            )
        side_effecting = request.risk_classes.difference({RiskClass.READ})
        if side_effecting:
            return PolicyDecision(
                PolicyAction.DENY,
                request.risk_classes,
                None,
                "unclassified or unmatched side-effecting request denied by safety fallback",
            )
        return PolicyDecision(
            self.default_action,
            request.risk_classes,
            None,
            f"no policy rule matched; using default action '{self.default_action.value}'",
        )


def _canonical_json_value(value: object, active: set[int]) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("arguments cannot contain NaN or infinity")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError("arguments cannot contain cycles")
        active.add(identity)
        try:
            normalized: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("argument object keys must be strings")
                normalized[key] = _canonical_json_value(item, active)
            return normalized
        finally:
            active.remove(identity)
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise ValueError("arguments cannot contain cycles")
        active.add(identity)
        try:
            return [_canonical_json_value(item, active) for item in value]
        finally:
            active.remove(identity)
    raise TypeError(f"unsupported argument value: {type(value).__name__}")


def canonical_arguments_hash(arguments: object) -> str:
    """Hash canonical JSON structure while preserving exact string and key code points.

    Mapping order is canonicalized; list order remains significant. Non-JSON values, non-finite
    floats, non-string mapping keys, and cyclic containers are rejected.
    """

    normalized = _canonical_json_value(arguments, set())
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def arguments_hash(arguments: object) -> str:
    """Compatibility-friendly short name for :func:`canonical_arguments_hash`."""

    return canonical_arguments_hash(arguments)
