"""Secure tool registry with permission checks, timeout enforcement, and audit logging.

Every tool call goes through:
1. Input validation (does the input match the schema?)
2. Permission check (is this agent allowed to use this tool?)
3. Timeout enforcement (asyncio.wait_for prevents hanging tools)
4. Audit logging (every call logged with correlation ID)

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 3 - Tools (registered, validated, timeout-enforced, audited)
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import structlog

from app.agents.protocols import AuditLog, PermissionChecker
from app.observability.logging import get_correlation_id
from app.runtime.models import ToolCall
from app.runtime.models import ToolDefinition as RuntimeToolDefinition
from app.security.policy import (
    PolicyRequest,
    ResourceKind,
    ResourcePattern,
    RiskClass,
    canonical_tool_name,
)

logger = structlog.get_logger()

# Default timeout for tool execution (seconds)
DEFAULT_TOOL_TIMEOUT = 30

ResourceResolver = Callable[[Mapping[str, Any]], tuple[ResourcePattern, ...]]
_SUPPORTED_PROPERTY_TYPES = frozenset({"string", "integer", "number", "boolean", "object", "array"})


def _value_matches_type(value: Any, declared_type: str) -> bool:
    """Match the deliberately small JSON-schema type subset used by tool definitions."""
    if declared_type == "string":
        return isinstance(value, str)
    if declared_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if declared_type == "number":
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    if declared_type == "boolean":
        return type(value) is bool
    if declared_type == "object":
        return isinstance(value, Mapping)
    if declared_type == "array":
        return isinstance(value, (list, tuple))
    return False  # pragma: no cover - registration rejects unsupported declarations


def _validate_input_schema(schema: Any) -> Mapping[str, Any]:
    """Validate trusted registration metadata for the supported schema subset."""
    if not isinstance(schema, Mapping):
        raise TypeError("invalid input schema: expected a mapping")

    schema_type = schema.get("type")
    if schema_type is not None and schema_type != "object":
        raise ValueError("invalid input schema: root type must be object")
    additional_properties = schema.get("additionalProperties")
    if additional_properties is not None and type(additional_properties) is not bool:
        raise TypeError("invalid input schema: additionalProperties must be boolean")

    required = schema.get("required", ())
    if not isinstance(required, (list, tuple)) or not all(
        isinstance(field, str) for field in required
    ):
        raise TypeError("invalid input schema: required must be an array of field names")
    if len(set(required)) != len(required):
        raise ValueError("invalid input schema: required field names must be unique")

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise TypeError("invalid input schema: properties must be an object")
    if not all(isinstance(field, str) for field in properties):
        raise TypeError("invalid input schema: property names must be strings")
    if properties and any(field not in properties for field in required):
        raise ValueError("invalid input schema: required field is not declared")

    for field, declaration in properties.items():
        if not isinstance(declaration, Mapping):
            raise TypeError(f"invalid input schema for field '{field}': expected an object")
        declared_type = declaration.get("type")
        if declared_type not in _SUPPORTED_PROPERTY_TYPES:
            raise ValueError(f"invalid input schema for field '{field}': unsupported type")
        if "enum" not in declaration:
            continue
        enum = declaration["enum"]
        if not isinstance(enum, (list, tuple)) or not enum:
            raise TypeError(f"invalid input schema for field '{field}': enum must be an array")
        if any(not _value_matches_type(item, declared_type) for item in enum):
            raise ValueError(f"invalid input schema for field '{field}': enum type mismatch")
    return schema


def _deep_freeze(value: Any) -> Any:
    """Copy JSON-like metadata into recursively immutable containers."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    raise TypeError(f"unsupported mutable metadata value: {type(value).__name__}")


def _deep_thaw(value: Any) -> Any:
    """Return detached mutable containers for public metadata views."""
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_deep_thaw(item) for item in value}
    return copy.deepcopy(value)


class PolicyMetadataError(ValueError):
    """Policy metadata is missing or cannot be resolved safely."""


def resolve_workspace_path(arguments: Mapping[str, Any]) -> tuple[ResourcePattern, ...]:
    """Resolve a tool ``path`` argument against ``ARCHON_WORKSPACE_ROOT``.

    This supplies a canonical lexical identity to policy evaluation only. Tool execution must
    independently recheck workspace containment immediately before filesystem access because
    symlinks and other filesystem state can change between policy evaluation and use (TOCTOU).
    """

    path = arguments.get("path")
    if not isinstance(path, str):
        raise ValueError("path argument must be a string")
    if os.name != "nt" and "\\" in path:
        raise ValueError("Invalid workspace path")
    # The root is trusted server configuration. It must never be selected by model-controlled
    # tool arguments; registry validation also rejects ``workspace_root`` for all live tools.
    root_value = os.environ.get("ARCHON_WORKSPACE_ROOT", str(Path.cwd()))
    root = Path(root_value).resolve(strict=False)
    requested = Path(path)
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve(strict=False)
    return (ResourcePattern(ResourceKind.PATH, resolved.as_posix()),)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """A registered tool with its metadata."""

    name: str
    handler: Callable[..., Any]
    description: str = ""
    required_permissions: tuple[str, ...] | list[str] | None = None
    input_schema: Mapping[str, Any] | None = None
    timeout: int = DEFAULT_TOOL_TIMEOUT
    requires_approval: bool = False
    risk_classes: frozenset[RiskClass] = dataclass_field(default_factory=frozenset)
    resource_resolver: ResourceResolver | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.risk_classes, frozenset) or not all(
            isinstance(risk, RiskClass) for risk in self.risk_classes
        ):
            raise TypeError("risk_classes must be a frozenset of RiskClass values")
        if self.resource_resolver is not None and not callable(self.resource_resolver):
            raise TypeError("resource_resolver must be callable")
        schema = {} if self.input_schema is None else _validate_input_schema(self.input_schema)
        object.__setattr__(self, "name", canonical_tool_name(self.name))
        object.__setattr__(self, "required_permissions", tuple(self.required_permissions or ()))
        object.__setattr__(self, "input_schema", _deep_freeze(schema))


class SecureToolRegistry:
    """Tool executor with permission gating, timeout enforcement, and audit.

    Satisfies the ToolExecutor Protocol.
    """

    def __init__(
        self,
        permissions: PermissionChecker | None = None,
        audit: AuditLog | None = None,
        default_timeout: int = DEFAULT_TOOL_TIMEOUT,
    ) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._permissions = permissions
        self._audit = audit
        self._default_timeout = default_timeout

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str = "",
        required_permissions: list[str] | None = None,
        input_schema: dict[str, Any] | None = None,
        timeout: int | None = None,
        requires_approval: bool = False,
        risk_classes: frozenset[RiskClass] = frozenset(),
        resource_resolver: ResourceResolver | None = None,
    ) -> None:
        """Register a tool."""
        canonical_name = canonical_tool_name(name)
        if canonical_name in self._tools:
            raise ValueError(f"tool already registered: {canonical_name}")
        self._tools[canonical_name] = ToolDefinition(
            name=canonical_name,
            handler=handler,
            description=description,
            required_permissions=required_permissions,
            input_schema=input_schema,
            timeout=timeout or self._default_timeout,
            requires_approval=requires_approval,
            risk_classes=risk_classes,
            resource_resolver=resource_resolver,
        )
        logger.info("tool_registered", name=canonical_name, description=description)

    @staticmethod
    def _validate_arguments(tool: ToolDefinition, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Return detached arguments after applying the tool's declared field policy.

        Required names remain declarations when a compact schema omits ``properties``. Unknown
        fields fail closed unless the schema deliberately opts into ``additionalProperties``.
        Error messages never include caller-controlled names or values.
        """
        schema = cast(Mapping[str, Any], tool.input_schema)
        required_fields = schema.get("required", ())
        # Schema shape is trusted registration metadata; normalize only its field declarations.
        allowed_fields = set(required_fields)
        properties = schema.get("properties")
        if isinstance(properties, Mapping):
            allowed_fields.update(properties)

        for field in required_fields:
            if field not in arguments:
                raise ValueError(f"Missing required parameter: {field}")
        if schema.get("additionalProperties") is not True and any(
            field not in allowed_fields for field in arguments
        ):
            raise ValueError("Unexpected parameter(s) supplied")

        if isinstance(properties, Mapping):
            for field, declaration in properties.items():
                if field not in arguments:
                    continue
                value = arguments[field]
                declared_type = declaration["type"]
                if not _value_matches_type(value, declared_type):
                    raise ValueError(f"Invalid parameter: {field}")
                enum = declaration.get("enum")
                if enum is not None and not any(
                    type(value) is type(option) and value == option for option in enum
                ):
                    raise ValueError(f"Invalid parameter: {field}")

        return copy.deepcopy(dict(arguments))

    async def execute(
        self, call: ToolCall | str, parameters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute a typed call (or legacy name/parameters) through all security gates."""
        if isinstance(call, ToolCall):
            tool_name = canonical_tool_name(call.name)
            parameters = dict(call.arguments)
        else:
            tool_name = canonical_tool_name(call)
            parameters = parameters or {}
        correlation_id = get_correlation_id()

        # 1. Tool exists?
        if tool_name not in self._tools:
            error_msg = f"Unknown tool: {tool_name}"
            logger.warning("tool_not_found", tool=tool_name, correlation_id=correlation_id)
            raise ValueError(error_msg)

        tool = self._tools[tool_name]

        # 2. Input validation. This must precede every permission or execution hook.
        parameters = self._validate_arguments(tool, parameters)

        # 3. Permission check
        if self._permissions and tool.required_permissions:
            for perm in tool.required_permissions:
                allowed = await self._permissions.check(
                    agent_id="archon",
                    resource=tool_name,
                    action=perm,
                    **parameters,
                )
                if not allowed:
                    if self._audit:
                        await self._audit.log(
                            agent_id="archon",
                            action="permission_denied",
                            resource=tool_name,
                            parameters=parameters,
                            result="denied",
                            correlation_id=correlation_id,
                            security_level="warning",
                        )
                    error_msg = f"Permission denied for {perm} on {tool_name}"
                    raise PermissionError(error_msg)

        # 4. Execute with timeout
        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await asyncio.wait_for(
                    tool.handler(**parameters),
                    timeout=tool.timeout,
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None, lambda: tool.handler(**parameters)
                    ),
                    timeout=tool.timeout,
                )
        except TimeoutError:
            logger.error(
                "tool_timeout",
                tool=tool_name,
                timeout=tool.timeout,
                correlation_id=correlation_id,
            )
            if self._audit:
                await self._audit.log(
                    agent_id="archon",
                    action="tool_timeout",
                    resource=tool_name,
                    parameters=parameters,
                    result="timeout",
                    correlation_id=correlation_id,
                    security_level="error",
                )
            raise TimeoutError(f"Tool '{tool_name}' timed out after {tool.timeout}s") from None
        except Exception as e:
            logger.error(
                "tool_error",
                tool=tool_name,
                error=str(e),
                correlation_id=correlation_id,
            )
            raise

        # 5. Audit success
        if self._audit:
            await self._audit.log(
                agent_id="archon",
                action="tool_executed",
                resource=tool_name,
                parameters=parameters,
                result="success",
                correlation_id=correlation_id,
            )

        logger.info(
            "tool_executed",
            tool=tool_name,
            correlation_id=correlation_id,
        )

        if isinstance(result, dict):
            return result
        return {"result": result}

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools with their schemas."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": _deep_thaw(tool.input_schema),
                "risk_classes": sorted(risk.value for risk in tool.risk_classes),
                "requires_approval": tool.requires_approval,
            }
            for tool in self._tools.values()
        ]

    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        """Return provider-neutral schemas for native provider tool calling."""
        definitions = []
        for tool in self._tools.values():
            schema = _deep_thaw(tool.input_schema)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            definitions.append(RuntimeToolDefinition(tool.name, tool.description, schema))
        return tuple(definitions)

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(canonical_tool_name(name))

    def policy_request(self, call: ToolCall) -> PolicyRequest:
        """Build fail-closed policy input from a typed provider tool call."""
        tool_name = canonical_tool_name(call.name)
        tool = self._tools.get(tool_name)
        if tool is None:
            raise PolicyMetadataError(f"Unknown tool: {tool_name}")
        if not tool.risk_classes:
            raise PolicyMetadataError(f"Tool '{tool_name}' has no risk classification")

        parameters = self._validate_arguments(tool, call.arguments)
        resources: tuple[ResourcePattern, ...] = ()
        if tool.resource_resolver is not None:
            try:
                resolved = tool.resource_resolver(_deep_freeze(parameters))
                if not isinstance(resolved, tuple) or not all(
                    isinstance(resource, ResourcePattern) for resource in resolved
                ):
                    raise TypeError(
                        "resolver must return a tuple containing only ResourcePattern values"
                    )
                if any(resource.kind is ResourceKind.TOOL for resource in resolved):
                    raise ValueError(
                        "resolver cannot return TOOL resources; tool_name is the sole tool identity"
                    )
                resources = resolved
            except Exception as error:
                raise PolicyMetadataError(
                    f"resource resolver failed for tool '{tool_name}'"
                ) from error

        try:
            return PolicyRequest(
                tool_name=tool_name,
                resources=resources,
                risk_classes=tool.risk_classes,
                legacy_requires_approval=tool.requires_approval,
            )
        except (TypeError, ValueError) as error:
            raise PolicyMetadataError(
                f"invalid policy metadata for tool '{tool_name}': {error}"
            ) from error

    def tool_requires_approval(self, name: str) -> bool:
        """Check if a tool requires human approval before execution."""
        tool = self._tools.get(canonical_tool_name(name))
        if tool is None:
            return False
        return tool.requires_approval
