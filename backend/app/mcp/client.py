"""Bounded official-SDK stdio MCP client."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Generic, Protocol, TypeVar, cast
from urllib.parse import urlsplit

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import PaginatedRequestParams, Tool

from app.mcp.models import (
    MCPCallResult,
    MCPServerProfile,
    RemoteServerProfile,
    ServerProfile,
    ToolDescriptor,
)

_T = TypeVar("_T")
_ProfileT = TypeVar("_ProfileT", ServerProfile, RemoteServerProfile)
_BASE_ENV_KEYS = ("PATH", "HOME", "LANG", "TMPDIR")
_MAX_SCHEMA_BYTES = 64_000
_MAX_TOOL_NAME_BYTES = 128
_MAX_DISCOVERY_PAGES = 100
_MAX_DISCOVERY_TOOLS = 10_000
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


class _BaseMCPClient(Generic[_ProfileT]):
    """Shared bounded MCP discovery and call normalization."""

    def __init__(self, profile: _ProfileT) -> None:
        self._profile: _ProfileT = profile

    async def _with_session(
        self,
        operation: Callable[[ClientSession], Awaitable[_T]],
        operation_timeout: float,
    ) -> _T:
        raise NotImplementedError

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
            tools: list[ToolDescriptor] = []
            names: set[str] = set()
            seen_cursors: set[str] = set()
            cursor: str | None = None
            total_bytes = 0
            for _page in range(_MAX_DISCOVERY_PAGES):
                response = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
                total_bytes += len(
                    _json_bytes(
                        response.model_dump(mode="json", by_alias=True), "invalid_tool_schema"
                    )
                )
                if total_bytes > self._profile.max_result_bytes:
                    raise MCPClientError("result_too_large")
                for raw_tool in response.tools:
                    tool = self._normalize_tool(raw_tool)
                    if tool.name in names:
                        raise MCPClientError("duplicate_tool_name")
                    names.add(tool.name)
                    tools.append(tool)
                    if len(tools) > _MAX_DISCOVERY_TOOLS:
                        raise MCPClientError("result_too_large")
                # MCP 2.1's runtime model exposes snake_case while its bundled typing metadata
                # still declares the wire alias. Keep the SDK boundary localized here.
                next_cursor = cast(Any, response).next_cursor
                if next_cursor is None:
                    return tuple(tools)
                if type(next_cursor) is not str or not next_cursor or next_cursor in seen_cursors:
                    raise MCPClientError("invalid_pagination")
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            raise MCPClientError("result_too_large")

        return await self._with_session(operation, self._profile.discovery_timeout_seconds)

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


class StdioMCPClient(_BaseMCPClient[ServerProfile]):
    """Runs only the executable and arguments in an injected ``ServerProfile``."""

    def __init__(self, profile: ServerProfile) -> None:
        if not isinstance(profile, ServerProfile):
            raise TypeError("profile must be a ServerProfile")
        super().__init__(profile)

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


class CredentialProvider(Protocol):
    """Resolves a deployment-owned reference immediately before an HTTP connection."""

    def resolve(self, credential_ref: str) -> Mapping[str, str]: ...


class _NoCredentials:
    def resolve(self, credential_ref: str) -> Mapping[str, str]:
        raise MCPClientError("credentials_unavailable")


_FORBIDDEN_CREDENTIAL_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "mcp-session-id",
        "mcp-protocol-version",
    }
)


class RemoteMCPClient(_BaseMCPClient[RemoteServerProfile]):
    """Bounded official-SDK client for one governed Streamable HTTP profile."""

    def __init__(
        self,
        profile: RemoteServerProfile,
        *,
        credential_provider: CredentialProvider | None = None,
        http_client_factory: Callable[..., Any] = httpx2.AsyncClient,
    ) -> None:
        if not isinstance(profile, RemoteServerProfile):
            raise TypeError("profile must be a RemoteServerProfile")
        self._profile = profile
        self._credential_provider = credential_provider or _NoCredentials()
        self._http_client_factory = http_client_factory
        parsed = urlsplit(profile.url)
        self._origin = (parsed.scheme, parsed.hostname, parsed.port)

    def _credential_headers(self) -> dict[str, str]:
        if self._profile.credential_ref is None:
            return {}
        try:
            raw = self._credential_provider.resolve(self._profile.credential_ref)
            if not isinstance(raw, Mapping):
                raise TypeError
            headers = dict(raw)
        except MCPClientError:
            raise
        except Exception:
            raise MCPClientError("credentials_unavailable") from None
        if any(
            type(key) is not str
            or type(value) is not str
            or not key
            or key.lower() in _FORBIDDEN_CREDENTIAL_HEADERS
            or any(character in key or character in value for character in "\r\n\x00")
            for key, value in headers.items()
        ):
            raise MCPClientError("invalid_credentials")
        return headers

    async def _guard_origin(self, request: Any) -> None:
        url = request.url
        origin = (url.scheme, url.host, url.port)
        if origin != self._origin:
            raise MCPClientError("unsafe_redirect")

    def _build_http_client(self) -> Any:
        """Build a non-proxying, non-redirecting client; raw headers remain ephemeral."""

        return self._http_client_factory(
            headers=self._credential_headers(),
            timeout=httpx2.Timeout(
                self._profile.response_timeout_seconds,
                connect=self._profile.connect_timeout_seconds,
            ),
            follow_redirects=False,
            trust_env=False,
            event_hooks={"request": [self._guard_origin]},
        )

    async def _with_session(
        self,
        operation: Callable[[ClientSession], Awaitable[_T]],
        operation_timeout: float,
    ) -> _T:
        try:
            async with asyncio.timeout(
                self._profile.connect_timeout_seconds
                + operation_timeout
                + self._profile.response_timeout_seconds
            ):
                async with self._build_http_client() as http_client:
                    async with streamable_http_client(
                        self._profile.url,
                        http_client=http_client,
                        terminate_on_close=True,
                    ) as streams:
                        read_stream, write_stream = streams[0], streams[1]
                        async with ClientSession(read_stream, write_stream) as session:
                            async with asyncio.timeout(self._profile.connect_timeout_seconds):
                                await session.initialize()
                            async with asyncio.timeout(operation_timeout):
                                return await operation(session)
        except MCPClientError:
            raise
        except (Exception, BaseExceptionGroup) as exc:
            if _contains_timeout(exc):
                raise MCPClientError("timeout") from None
            client_error = _find_client_error(exc)
            if client_error is not None:
                raise MCPClientError(client_error.code) from None
            raise MCPClientError("transport_error") from None

    async def health_check(self) -> bool:
        """Probe availability with bounded reconnect and exponential backoff."""

        for attempt in range(self._profile.reconnect_attempts + 1):
            try:
                await self.initialize()
                return True
            except MCPClientError as error:
                if error.code not in {"timeout", "transport_error"}:
                    return False
                if attempt == self._profile.reconnect_attempts:
                    return False
                await asyncio.sleep(self._profile.reconnect_backoff_seconds * (2**attempt))
        return False


def create_mcp_client(
    profile: MCPServerProfile,
    *,
    credential_provider: CredentialProvider | None = None,
) -> StdioMCPClient | RemoteMCPClient:
    """Common transport factory while preserving existing stdio profiles."""

    if isinstance(profile, ServerProfile):
        return StdioMCPClient(profile)
    if isinstance(profile, RemoteServerProfile):
        return RemoteMCPClient(profile, credential_provider=credential_provider)
    raise TypeError("profile must be an MCP server profile")
