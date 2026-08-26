"""Scope-bound MCP tools for the policy-enforced agent runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, cast

from app.mcp.client import StdioMCPClient
from app.mcp.models import MCPCallResult, ServerProfile
from app.mcp.repository import MCPHealth, MCPRepository, MCPServerRecord, MCPToolRecord
from app.security.policy import RiskClass

_NAME_PART = re.compile(r"[^a-z0-9]+")
_SUPPORTED_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array"})
_ROOT_KEYS = frozenset(
    {"type", "properties", "required", "additionalProperties", "title", "description"}
)
_PROPERTY_KEYS = frozenset({"type", "enum", "title", "description", "default"})


class MCPRuntimeError(RuntimeError):
    """A stable failure raised when a persisted runtime binding is no longer safe."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MCPRuntimeClient(Protocol):
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> MCPCallResult: ...


MCPRuntimeClientFactory = Callable[[ServerProfile], MCPRuntimeClient]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _valid_annotation(value: object) -> bool:
    return type(value) is str


def _finite_json(value: object, seen: set[int] | None = None, depth: int = 0) -> bool:
    if depth > 32:
        return False
    if value is None or type(value) in (str, int, bool):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) not in (dict, list):
        return False
    identities = set() if seen is None else seen
    identity = id(value)
    if identity in identities:
        return False
    identities.add(identity)
    try:
        if type(value) is list:
            return all(_finite_json(item, identities, depth + 1) for item in value)
        mapping = cast(dict[object, object], value)
        return all(
            type(key) is str and _finite_json(item, identities, depth + 1)
            for key, item in mapping.items()
        )
    finally:
        identities.remove(identity)


def _matches_type(value: object, declared_type: str) -> bool:
    if not _finite_json(value):
        return False
    if declared_type == "string":
        return type(value) is str
    if declared_type == "integer":
        return type(value) is int
    if declared_type == "number":
        if type(value) is int:
            return True
        return type(value) is float and math.isfinite(value)
    if declared_type == "boolean":
        return type(value) is bool
    if declared_type == "object":
        return type(value) is dict
    if declared_type == "array":
        return type(value) is list
    return False


def normalize_input_schema(schema: object) -> dict[str, Any]:
    """Reduce untrusted JSON Schema to the registry's enforceable, closed subset.

    Every operation is preceded by an exact container/type check so malformed JSON-like values
    always produce the stable schema error rather than escaping as ``TypeError``.
    """
    if type(schema) is not dict:
        raise MCPRuntimeError("unsupported_tool_schema")
    schema_dict = schema
    if schema_dict.get("type") != "object":
        raise MCPRuntimeError("unsupported_tool_schema")
    if any(type(key) is not str for key in schema_dict):
        raise MCPRuntimeError("unsupported_tool_schema")
    if any(key not in _ROOT_KEYS for key in schema_dict):
        raise MCPRuntimeError("unsupported_tool_schema")
    if "additionalProperties" in schema_dict and schema_dict["additionalProperties"] is not False:
        raise MCPRuntimeError("unsupported_tool_schema")
    for annotation in ("title", "description"):
        if annotation in schema_dict and not _valid_annotation(schema_dict[annotation]):
            raise MCPRuntimeError("unsupported_tool_schema")

    properties = schema_dict.get("properties", {})
    required = schema_dict.get("required", [])
    if type(properties) is not dict or type(required) is not list:
        raise MCPRuntimeError("unsupported_tool_schema")
    if (
        any(type(name) is not str for name in properties)
        or any(type(name) is not str for name in required)
        or len(set(required)) != len(required)
        or any(name not in properties for name in required)
    ):
        raise MCPRuntimeError("unsupported_tool_schema")

    normalized_properties: dict[str, dict[str, Any]] = {}
    for name, raw in properties.items():
        if type(raw) is not dict or any(type(key) is not str for key in raw):
            raise MCPRuntimeError("unsupported_tool_schema")
        if any(key not in _PROPERTY_KEYS for key in raw):
            raise MCPRuntimeError("unsupported_tool_schema")
        declared_type = raw.get("type")
        if type(declared_type) is not str or declared_type not in _SUPPORTED_TYPES:
            raise MCPRuntimeError("unsupported_tool_schema")
        for annotation in ("title", "description"):
            if annotation in raw and not _valid_annotation(raw[annotation]):
                raise MCPRuntimeError("unsupported_tool_schema")
        normalized: dict[str, Any] = {"type": declared_type}
        if "enum" in raw:
            enum = raw["enum"]
            if (
                type(enum) is not list
                or not enum
                or not all(_matches_type(item, declared_type) for item in enum)
            ):
                raise MCPRuntimeError("unsupported_tool_schema")
            normalized["enum"] = copy.deepcopy(enum)
        if "default" in raw and not _matches_type(raw["default"], declared_type):
            raise MCPRuntimeError("unsupported_tool_schema")
        normalized_properties[name] = normalized
    return {
        "type": "object",
        "properties": normalized_properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _name_part(value: str) -> str:
    part = _NAME_PART.sub("_", value.lower()).strip("_")
    return part or "unnamed"


def _base_name(server: MCPServerRecord, tool: MCPToolRecord) -> str:
    return f"mcp_{_name_part(server.name)}_{_name_part(tool.name)}"


def _schema_hash(schema: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        schema, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class MCPBoundToolSpec:
    """Immutable metadata and closure for one owner/project-scoped MCP tool."""

    name: str
    handler: Callable[..., Any]
    description: str
    input_schema: Mapping[str, Any]
    timeout: int
    risk_classes: frozenset[RiskClass]
    requires_approval: bool = True
    resource_identity: str = ""
    _frozen_schema: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        frozen = _freeze(self.input_schema)
        object.__setattr__(self, "input_schema", frozen)
        object.__setattr__(self, "_frozen_schema", frozen)
        object.__setattr__(self, "resource_identity", self.name)


@dataclass(frozen=True, slots=True)
class _Binding:
    owner_id: str
    project_id: str
    server_id: str
    server_name: str
    profile_id: str
    tool_id: str
    remote_name: str
    schema_hash: str
    read_only: bool
    destructive: bool


class MCPRuntimeToolProvider:
    """Build and execute immutable MCP bindings from enabled, healthy inventory only."""

    def __init__(
        self,
        repository: MCPRepository,
        *,
        profiles: Mapping[str, ServerProfile],
        client_factory: MCPRuntimeClientFactory = StdioMCPClient,
    ) -> None:
        copied = dict(profiles)
        if any(
            type(key) is not str or not key or not isinstance(value, ServerProfile)
            for key, value in copied.items()
        ):
            raise ValueError("invalid MCP profile allowlist")
        self._repository = repository
        self._profiles: Mapping[str, ServerProfile] = MappingProxyType(copied)
        self._client_factory = client_factory

    async def for_scope(self, owner_id: str, project_id: str) -> tuple[MCPBoundToolSpec, ...]:
        candidates: list[tuple[MCPServerRecord, MCPToolRecord, dict[str, Any]]] = []
        for server in await self._repository.list(owner_id=owner_id, project_id=project_id):
            if (
                not server.enabled
                or server.health is not MCPHealth.HEALTHY
                or server.profile_id not in self._profiles
            ):
                continue
            for tool in await self._repository.list_tools(
                owner_id=owner_id, project_id=project_id, server_id=server.id
            ):
                if not tool.enabled:
                    continue
                try:
                    schema = normalize_input_schema(tool.input_schema)
                except MCPRuntimeError:
                    # A selected schema that cannot be enforced must not remain selected.
                    await self._repository.set_tool_enabled(
                        owner_id=owner_id,
                        project_id=project_id,
                        server_id=server.id,
                        tool_id=tool.id,
                        enabled=False,
                    )
                    continue
                candidates.append((server, tool, schema))

        bases = [_base_name(server, tool) for server, tool, _schema in candidates]
        collisions = {name for name in bases if bases.count(name) > 1}
        specs: list[MCPBoundToolSpec] = []
        for server, tool, schema in candidates:
            name = _base_name(server, tool)
            if name in collisions:
                digest = hashlib.sha256(f"{server.id}:{tool.id}".encode()).hexdigest()[:12]
                name = f"{name}_{digest}"
            binding = _Binding(
                owner_id=owner_id,
                project_id=project_id,
                server_id=server.id,
                server_name=server.name,
                profile_id=server.profile_id,
                tool_id=tool.id,
                remote_name=tool.name,
                schema_hash=_schema_hash(tool.input_schema),
                read_only=tool.read_only,
                destructive=tool.destructive,
            )

            async def invoke(_binding: _Binding = binding, **arguments: Any) -> dict[str, Any]:
                return await self._call(_binding, arguments)

            risks = {RiskClass.NETWORK}
            if tool.read_only:
                risks.add(RiskClass.READ)
            else:
                risks.update({RiskClass.WRITE, RiskClass.EXTERNAL_SIDE_EFFECT})
            if tool.destructive:
                risks.update({RiskClass.WRITE, RiskClass.EXTERNAL_SIDE_EFFECT})
            specs.append(
                MCPBoundToolSpec(
                    name=name,
                    handler=invoke,
                    description=tool.description or tool.title or f"MCP tool {tool.name}",
                    input_schema=schema,
                    timeout=max(
                        1,
                        math.ceil(
                            self._profiles[server.profile_id].connect_timeout_seconds
                            + self._profiles[server.profile_id].call_timeout_seconds
                        ),
                    ),
                    risk_classes=frozenset(risks),
                )
            )
        return tuple(specs)

    async def _call(self, binding: _Binding, arguments: Mapping[str, Any]) -> dict[str, Any]:
        server = await self._repository.get(
            owner_id=binding.owner_id,
            project_id=binding.project_id,
            server_id=binding.server_id,
        )
        if (
            server is None
            or not server.enabled
            or server.health is not MCPHealth.HEALTHY
            or server.name != binding.server_name
            or server.profile_id != binding.profile_id
        ):
            raise MCPRuntimeError("mcp_binding_changed")
        profile = self._profiles.get(server.profile_id)
        if profile is None:
            raise MCPRuntimeError("mcp_binding_changed")
        tools = await self._repository.list_tools(
            owner_id=binding.owner_id,
            project_id=binding.project_id,
            server_id=binding.server_id,
        )
        tool = next((item for item in tools if item.id == binding.tool_id), None)
        if (
            tool is None
            or not tool.enabled
            or tool.name != binding.remote_name
            or _schema_hash(tool.input_schema) != binding.schema_hash
            or tool.read_only is not binding.read_only
            or tool.destructive is not binding.destructive
        ):
            raise MCPRuntimeError("mcp_binding_changed")
        # Re-normalize persisted data immediately before transport use. This catches unsupported
        # schema drift even if a repository implementation returns unusual mapping containers.
        normalize_input_schema(tool.input_schema)
        result = await self._client_factory(profile).call_tool(tool.name, arguments)
        return {
            "content": [dict(item) for item in result.content],
            "structured_content": (
                None if result.structured_content is None else dict(result.structured_content)
            ),
            "is_error": result.is_error,
        }
