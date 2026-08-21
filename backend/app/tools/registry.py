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
import inspect
from collections.abc import Callable
from typing import Any

import structlog

from app.agents.protocols import AuditLog, PermissionChecker
from app.observability.logging import get_correlation_id

logger = structlog.get_logger()

# Default timeout for tool execution (seconds)
DEFAULT_TOOL_TIMEOUT = 30


class ToolDefinition:
    """A registered tool with its metadata."""

    def __init__(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str = "",
        required_permissions: list[str] | None = None,
        input_schema: dict | None = None,
        timeout: int = DEFAULT_TOOL_TIMEOUT,
    ) -> None:
        self.name = name
        self.handler = handler
        self.description = description
        self.required_permissions = required_permissions or []
        self.input_schema = input_schema or {}
        self.timeout = timeout


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
        input_schema: dict | None = None,
        timeout: int | None = None,
    ) -> None:
        """Register a tool."""
        self._tools[name] = ToolDefinition(
            name=name,
            handler=handler,
            description=description,
            required_permissions=required_permissions,
            input_schema=input_schema,
            timeout=timeout or self._default_timeout,
        )
        logger.info("tool_registered", name=name, description=description)

    async def execute(self, tool_name: str, parameters: dict) -> dict:
        """Execute a tool with permission checks and timeout enforcement."""
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
        required_fields = tool.input_schema.get("required", [])
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
            raise TimeoutError(f"Tool '{tool_name}' timed out after {tool.timeout}s")
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

    def list_tools(self) -> list[dict]:
        """List all registered tools with their schemas."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)
