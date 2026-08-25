"""Secure tool registry with permission checks, timeout enforcement, and audit logging.

Every tool call goes through:
1. Permission check (is this agent allowed to use this tool?)
2. Input validation (does the input match the schema?)
3. Timeout enforcement (asyncio.wait_for prevents hanging tools)
4. Audit logging (every call logged with correlation ID)

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 3 - Tools (registered, validated, timeout-enforced, audited)
"""

from __future__ import annotations

import asyncio
import copy
import inspect
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
    workspace_root = arguments.get("workspace_root")
    if workspace_root is not None and not isinstance(workspace_root, (str, os.PathLike)):
        raise ValueError("workspace_root argument must be a path")
    root_value = (
        workspace_root
        if workspace_root is not None
        else os.environ.get("ARCHON_WORKSPACE_ROOT", str(Path.cwd()))
    )
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
        object.__setattr__(self, "name", canonical_tool_name(self.name))
        object.__setattr__(self, "required_permissions", tuple(self.required_permissions or ()))
        object.__setattr__(self, "input_schema", _deep_freeze(self.input_schema or {}))


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

        # 2. Permission check
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

        # 3. Input validation
        schema = cast(Mapping[str, Any], tool.input_schema)
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in parameters:
                error_msg = f"Missing required parameter: {field}"
                raise ValueError(error_msg)

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

        resources: tuple[ResourcePattern, ...] = ()
        if tool.resource_resolver is not None:
            try:
                resolved = tool.resource_resolver(_deep_freeze(call.arguments))
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
