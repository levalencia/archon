from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from app.mcp.inventory import MCPInventoryService
from app.mcp.models import MCPCallResult, RemoteServerProfile, ToolDescriptor
from app.mcp.repository import MCPHealth, MCPRepository
from app.mcp.runtime import MCPRuntimeToolProvider
from app.services.db_store import DatabaseStore, MCPToolRow


class _HTTPClient:
    async def list_tools(self) -> tuple[ToolDescriptor, ...]:
        return (
            ToolDescriptor(
                "lookup",
                None,
                "Lookup",
                {"type": "object", "properties": {}},
                True,
                False,
                "1",
            ),
        )

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> MCPCallResult:
        return MCPCallResult(({"type": "text", "text": name},), dict(arguments), False)


@pytest.mark.asyncio
async def test_http_transport_is_persisted_without_profile_secrets_and_reports_health(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'http.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    secret_ref = "vault://deployment/remote-token"
    endpoint = "https://mcp.example.test/rpc"
    profile = RemoteServerProfile(url=endpoint, credential_ref=secret_ref)
    assert secret_ref not in repr(profile)
    service = MCPInventoryService(
        repository, profiles={"remote": profile}, client_factory=lambda _: _HTTPClient()
    )
    server = await service.create_server(
        owner_id="alice",
        project_id="one",
        name="remote",
        profile_id="remote",
        enabled=True,
    )
    assert server.transport == "streamable_http"
    tools = await service.discover(owner_id="alice", project_id="one", server_id=server.id)
    assert len(tools) == 1 and not tools[0].enabled
    persisted = await repository.get(owner_id="alice", project_id="one", server_id=server.id)
    assert persisted is not None and persisted.health is MCPHealth.HEALTHY
    database_bytes = (tmp_path / "http.db").read_bytes()
    assert endpoint.encode() not in database_bytes
    assert secret_ref.encode() not in database_bytes
    await store.close()


@pytest.mark.asyncio
async def test_provider_materializes_only_enabled_schemas(tmp_path: Path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'lazy.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    profile = RemoteServerProfile(url="https://mcp.example.test/rpc")
    service = MCPInventoryService(
        repository, profiles={"remote": profile}, client_factory=lambda _: _HTTPClient()
    )
    server = await service.create_server(
        owner_id="alice", project_id="one", name="remote", profile_id="remote", enabled=True
    )
    tools = await service.discover(owner_id="alice", project_id="one", server_id=server.id)
    # Deliberately corrupt a disabled schema. Provider selection must not deserialize it.
    async with store.session_factory() as session:
        await session.execute(
            update(MCPToolRow)
            .where(MCPToolRow.id == tools[0].id)
            .values(input_schema_json="not-json")
        )
        await session.commit()
    provider = MCPRuntimeToolProvider(
        repository, profiles={"remote": profile}, client_factory=lambda _: _HTTPClient()
    )
    assert await provider.for_scope("alice", "one") == ()
    await store.close()
