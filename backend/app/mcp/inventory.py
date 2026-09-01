"""Discovery orchestration for allowlisted MCP stdio profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

from app.mcp.client import MCPClientError, create_mcp_client
from app.mcp.models import MCPServerProfile, RemoteServerProfile, ServerProfile, ToolDescriptor
from app.mcp.repository import MCPHealth, MCPRepository, MCPServerRecord, MCPToolRecord

_STABLE_CLIENT_ERRORS = frozenset(
    {
        "timeout",
        "transport_error",
        "invalid_tool_name",
        "invalid_tool_schema",
        "invalid_tool_version",
        "invalid_tool_metadata",
        "duplicate_tool_name",
        "invalid_pagination",
        "result_too_large",
    }
)


class MCPClient(Protocol):
    """Small injected discovery boundary implemented by the real stdio client."""

    async def list_tools(self) -> tuple[ToolDescriptor, ...]: ...


MCPClientFactory = Callable[[MCPServerProfile], MCPClient]


class MCPInventoryError(RuntimeError):
    """Non-sensitive, stable inventory operation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MCPInventoryService:
    """Resolves only deployment-owned profiles and persists normalized discovery."""

    def __init__(
        self,
        repository: MCPRepository,
        client_factory: MCPClientFactory = create_mcp_client,
        profiles: Mapping[str, MCPServerProfile] | None = None,
    ) -> None:
        copied = dict(profiles or {})
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, (ServerProfile, RemoteServerProfile))
            for key, value in copied.items()
        ):
            raise ValueError("invalid MCP profile allowlist")
        self._repository = repository
        self._client_factory = client_factory
        self._profiles: Mapping[str, MCPServerProfile] = MappingProxyType(copied)

    async def create_server(
        self,
        *,
        owner_id: str,
        project_id: str,
        name: str,
        profile_id: str,
        enabled: bool = True,
    ) -> MCPServerRecord:
        if profile_id not in self._profiles:
            raise MCPInventoryError("unknown_profile")
        return await self._repository.create(
            owner_id=owner_id,
            project_id=project_id,
            name=name,
            profile_id=profile_id,
            enabled=enabled,
        )

    async def update_server(
        self,
        *,
        owner_id: str,
        project_id: str,
        server_id: str,
        name: str | None = None,
        profile_id: str | None = None,
        enabled: bool | None = None,
    ) -> MCPServerRecord | None:
        if profile_id is not None and profile_id not in self._profiles:
            raise MCPInventoryError("unknown_profile")
        return await self._repository.update(
            owner_id=owner_id,
            project_id=project_id,
            server_id=server_id,
            name=name,
            profile_id=profile_id,
            enabled=enabled,
        )

    async def discover(
        self, *, owner_id: str, project_id: str, server_id: str
    ) -> tuple[MCPToolRecord, ...]:
        server = await self._repository.get(
            owner_id=owner_id, project_id=project_id, server_id=server_id
        )
        if server is None:
            raise MCPInventoryError("server_not_found")
        if not server.enabled:
            await self._repository.update_health(
                owner_id=owner_id,
                project_id=project_id,
                server_id=server_id,
                health=MCPHealth.DISABLED,
            )
            raise MCPInventoryError("server_disabled")
        profile = self._profiles.get(server.profile_id)
        if profile is None:
            await self._fail(owner_id, project_id, server_id, "unknown_profile", server.profile_id)
            raise MCPInventoryError("unknown_profile")
        try:
            client = self._client_factory(profile)
            descriptors = await client.list_tools()
            tools = await self._repository.replace_inventory(
                owner_id=owner_id,
                project_id=project_id,
                server_id=server_id,
                tools=descriptors,
                expected_profile_id=server.profile_id,
            )
        except MCPClientError as error:
            code = error.code if error.code in _STABLE_CLIENT_ERRORS else "discovery_failed"
            await self._fail(owner_id, project_id, server_id, code, server.profile_id)
            raise MCPInventoryError(code) from None
        except (Exception, BaseExceptionGroup):
            await self._fail(owner_id, project_id, server_id, "discovery_failed", server.profile_id)
            raise MCPInventoryError("discovery_failed") from None
        seen = datetime.now(tz=UTC)
        health_updated = await self._repository.update_health(
            owner_id=owner_id,
            project_id=project_id,
            server_id=server_id,
            health=MCPHealth.HEALTHY,
            last_seen=seen,
            now=seen,
            expected_profile_id=server.profile_id,
        )
        if not health_updated:
            raise MCPInventoryError("discovery_failed")
        return tuple(tools)

    async def _fail(
        self,
        owner_id: str,
        project_id: str,
        server_id: str,
        error_code: str,
        expected_profile_id: str,
    ) -> None:
        await self._repository.update_health(
            owner_id=owner_id,
            project_id=project_id,
            server_id=server_id,
            health=MCPHealth.ERROR,
            error_code=error_code,
            expected_profile_id=expected_profile_id,
        )
