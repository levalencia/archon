"""Bounded official-SDK stdio MCP client."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar, cast

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool

from app.mcp.models import MCPCallResult, ServerProfile, ToolDescriptor

_T = TypeVar("_T")
_BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR")
_MAX_SCHEMA_BYTES = 64_000
_MAX_TOOL_NAME_BYTES = 128
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")


class MCPClientError(RuntimeError):
    """A stable, deliberately non-sensitive MCP client failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _json_bytes(value: object, error_code: str) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise MCPClientError(error_code) from None


def _child_environment(extra: Mapping[str, str]) -> dict[str, str]:
    environment = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    environment.update(extra)
    return environment


def _contains_timeout(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, BaseExceptionGroup):
        return any(_contains_timeout(item) for item in error.exceptions)
    return False


def _find_client_error(error: BaseException) -> MCPClientError | None:
    if isinstance(error, MCPClientError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for item in error.exceptions:
            found = _find_client_error(item)
            if found is not None:
                return found
    return None


class StdioMCPClient:
    """Runs only the executable and arguments in an injected ``ServerProfile``."""

    def __init__(self, profile: ServerProfile) -> None:
        if not isinstance(profile, ServerProfile):
            raise TypeError("profile must be a ServerProfile")
        self._profile = profile

    async def _with_session(
        self,
        operation: Callable[[ClientSession], Awaitable[_T]],
        operation_timeout: float,
    ) -> _T:
        parameters = StdioServerParameters(
            command=self._profile.command,
            args=list(self._profile.args),
            cwd=self._profile.cwd,
            env=_child_environment(self._profile.env),
        )
        try:
            async with asyncio.timeout(self._profile.connect_timeout_seconds + operation_timeout):
                async with stdio_client(parameters) as (read_stream, write_stream):
                    async with ClientSession(read_stream, write_stream) as session:
                        async with asyncio.timeout(self._profile.connect_timeout_seconds):
                            await session.initialize()
                        async with asyncio.timeout(operation_timeout):
                            return await operation(session)
        except MCPClientError:
            raise
        except (Exception, BaseExceptionGroup) as exc:
            # SDK/provider details can contain commands, paths, arguments, or response data.
            if _contains_timeout(exc):
                raise MCPClientError("timeout") from None
            client_error = _find_client_error(exc)
            if client_error is not None:
                raise MCPClientError(client_error.code) from None
            raise MCPClientError("transport_error") from None

    async def initialize(self) -> None:
        """Start, initialize, and cleanly close the configured server."""

        async def initialized(_session: ClientSession) -> None:
            return None

        await self._with_session(initialized, self._profile.connect_timeout_seconds)

    @staticmethod
    def _normalize_tool(tool: Tool) -> ToolDescriptor:
        name = tool.name
        if (
            type(name) is not str
            or not _TOOL_NAME.fullmatch(name)
            or len(name.encode("utf-8")) > _MAX_TOOL_NAME_BYTES
        ):
            raise MCPClientError("invalid_tool_name")
        schema = tool.input_schema
        if type(schema) is not dict or schema.get("type") != "object":
            raise MCPClientError("invalid_tool_schema")
        if len(_json_bytes(schema, "invalid_tool_schema")) > _MAX_SCHEMA_BYTES:
            raise MCPClientError("invalid_tool_schema")
        annotations = tool.annotations
        meta = tool.meta or {}
        version = meta.get("version")
        if version is not None and (type(version) is not str or len(version) > 100):
            raise MCPClientError("invalid_tool_version")
        title = tool.title
        description = tool.description
        if title is not None and (type(title) is not str or len(title) > 500):
            raise MCPClientError("invalid_tool_metadata")
        if description is not None and (type(description) is not str or len(description) > 10_000):
            raise MCPClientError("invalid_tool_metadata")
        return ToolDescriptor(
            name=name,
            title=title,
            description=description,
            input_schema=schema,
            # Missing hints must be interpreted conservatively.
            read_only=bool(annotations and annotations.read_only_hint is True),
            destructive=not bool(annotations and annotations.destructive_hint is False),
            version=version,
        )

    async def list_tools(self) -> tuple[ToolDescriptor, ...]:
        async def operation(session: ClientSession) -> tuple[ToolDescriptor, ...]:
            response = await session.list_tools()
            tools = tuple(self._normalize_tool(tool) for tool in response.tools)
            if len({tool.name for tool in tools}) != len(tools):
                raise MCPClientError("duplicate_tool_name")
            return tools

        return await self._with_session(operation, self._profile.call_timeout_seconds)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> MCPCallResult:
        if (
            type(name) is not str
            or not _TOOL_NAME.fullmatch(name)
            or len(name.encode("utf-8")) > _MAX_TOOL_NAME_BYTES
            or not isinstance(arguments, Mapping)
        ):
            raise MCPClientError("invalid_call")
        arguments_dict = dict(arguments)
        _json_bytes(arguments_dict, "invalid_call")

        async def operation(session: ClientSession) -> MCPCallResult:
            response = await session.call_tool(name, arguments_dict)
            payload = response.model_dump(mode="json", by_alias=True)
            if len(_json_bytes(payload, "invalid_result")) > self._profile.max_result_bytes:
                raise MCPClientError("result_too_large")
            content_values: list[Mapping[str, Any]] = []
            for item in response.content:
                dumped = item.model_dump(mode="json", by_alias=True)
                if type(dumped) is not dict:
                    raise MCPClientError("invalid_result")
                content_values.append(dumped)
            structured = response.structured_content
            if structured is not None and type(structured) is not dict:
                raise MCPClientError("invalid_result")
            return MCPCallResult(
                content=tuple(content_values),
                structured_content=cast(dict[str, Any] | None, structured),
                is_error=bool(response.is_error),
            )

        return await self._with_session(operation, self._profile.call_timeout_seconds)
