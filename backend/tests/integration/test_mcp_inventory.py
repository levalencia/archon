"""Durable MCP configuration/inventory behavior and real discovery."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.mcp.inventory import MCPInventoryError, MCPInventoryService
from app.mcp.models import ServerProfile, ToolDescriptor
from app.mcp.repository import MCPHealth, MCPRepository
from app.mcp.runtime import MCPRuntimeToolProvider
from app.services.db_store import DatabaseStore, MCPToolRow

_SCRIPT = Path(__file__).parents[1] / "fixtures" / "mcp_test_server.py"


async def _repository(path: Path) -> tuple[DatabaseStore, MCPRepository]:
    store = DatabaseStore(f"sqlite+aiosqlite:///{path}")
    await store.initialize()
    return store, MCPRepository(store.session_factory)


@pytest.mark.asyncio
async def test_scope_restart_refresh_selection_and_cascade(tmp_path: Path) -> None:
    database = tmp_path / "inventory.db"
    store, repository = await _repository(database)
    server = await repository.create(
        owner_id="alice", project_id="one", name="local", profile_id="profile"
    )
    assert await repository.get(owner_id="mallory", project_id="one", server_id=server.id) is None
    original = ToolDescriptor(
        "item", None, None, {"type": "object", "properties": {}}, True, False, "1"
    )
    tools = await repository.replace_inventory(
        owner_id="alice", project_id="one", server_id=server.id, tools=(original,)
    )
    await repository.set_tool_enabled(
        owner_id="alice", project_id="one", server_id=server.id, tool_id=tools[0].id, enabled=True
    )
    await store.close()

    store, repository = await _repository(database)
    assert (await repository.list_tools(owner_id="alice", project_id="one", server_id=server.id))[
        0
    ].enabled
    same = await repository.replace_inventory(
        owner_id="alice", project_id="one", server_id=server.id, tools=(original,)
    )
    assert same[0].enabled
    changed = ToolDescriptor(
        "item", None, None, {"type": "object", "required": ["value"]}, True, False, "2"
    )
    refreshed = await repository.replace_inventory(
        owner_id="alice", project_id="one", server_id=server.id, tools=(changed,)
    )
    assert not refreshed[0].enabled
    assert await repository.delete(owner_id="alice", project_id="one", server_id=server.id)
    async with store.session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(MCPToolRow))).scalar_one()
        assert count == 0
    await store.close()


@pytest.mark.asyncio
async def test_profile_change_atomically_invalidates_inventory_and_same_profile_does_not(
    tmp_path: Path,
) -> None:
    store, repository = await _repository(tmp_path / "profile-change.db")
    server = await repository.create(
        owner_id="alice", project_id="one", name="local", profile_id="old"
    )
    descriptor = ToolDescriptor(
        "item", None, None, {"type": "object", "properties": {}}, True, False, "1"
    )
    tools = await repository.replace_inventory(
        owner_id="alice", project_id="one", server_id=server.id, tools=(descriptor,)
    )
    await repository.set_tool_enabled(
        owner_id="alice", project_id="one", server_id=server.id, tool_id=tools[0].id, enabled=True
    )
    await repository.update_health(
        owner_id="alice",
        project_id="one",
        server_id=server.id,
        health=MCPHealth.ERROR,
        error_code="transport_error",
    )

    await repository.update(
        owner_id="alice", project_id="one", server_id=server.id, profile_id="old"
    )
    assert (
        len(await repository.list_tools(owner_id="alice", project_id="one", server_id=server.id))
        == 1
    )

    changed = await repository.update(
        owner_id="alice", project_id="one", server_id=server.id, profile_id="new"
    )
    assert changed is not None
    assert changed.health is MCPHealth.UNKNOWN
    assert changed.last_error_code is None
    assert changed.last_seen is None
    assert (
        await repository.list_tools(owner_id="alice", project_id="one", server_id=server.id) == ()
    )

    rediscovered = await repository.replace_inventory(
        owner_id="alice",
        project_id="one",
        server_id=server.id,
        tools=(descriptor,),
        expected_profile_id="new",
    )
    assert not rediscovered[0].enabled
    with pytest.raises(LookupError, match="profile changed"):
        await repository.replace_inventory(
            owner_id="alice",
            project_id="one",
            server_id=server.id,
            tools=(descriptor,),
            expected_profile_id="old",
        )
    await store.close()


@pytest.mark.asyncio
async def test_profile_update_wins_against_in_flight_discovery(tmp_path: Path) -> None:
    store, repository = await _repository(tmp_path / "profile-race.db")
    old_profile = ServerProfile(command="old")
    new_profile = ServerProfile(command="new")
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingClient:
        async def list_tools(self) -> tuple[ToolDescriptor, ...]:
            entered.set()
            await release.wait()
            return (ToolDescriptor("stale", None, None, {"type": "object"}, True, False, None),)

    service = MCPInventoryService(
        repository,
        client_factory=lambda _profile: BlockingClient(),
        profiles={"old": old_profile, "new": new_profile},
    )
    server = await service.create_server(
        owner_id="alice", project_id="one", name="racy", profile_id="old"
    )
    discovery = asyncio.create_task(
        service.discover(owner_id="alice", project_id="one", server_id=server.id)
    )
    await entered.wait()
    await service.update_server(
        owner_id="alice", project_id="one", server_id=server.id, profile_id="new"
    )
    release.set()
    with pytest.raises(MCPInventoryError, match="discovery_failed"):
        await discovery

    current = await repository.get(owner_id="alice", project_id="one", server_id=server.id)
    assert current is not None and current.health is MCPHealth.UNKNOWN
    assert (
        await repository.list_tools(owner_id="alice", project_id="one", server_id=server.id) == ()
    )
    provider = MCPRuntimeToolProvider(repository, profiles={"old": old_profile, "new": new_profile})
    assert await provider.for_scope("alice", "one") == ()
    await store.close()


@pytest.mark.asyncio
async def test_unknown_profile_and_failure_do_not_persist_raw_secret(tmp_path: Path) -> None:
    store, repository = await _repository(tmp_path / "safe.db")
    service = MCPInventoryService(repository, profiles={})
    with pytest.raises(MCPInventoryError, match="unknown_profile"):
        await service.create_server(
            owner_id="alice", project_id="one", name="bad", profile_id="secret-command"
        )

    profile = ServerProfile(command="not-a-real-executable-secret-123")
    service = MCPInventoryService(repository, profiles={"safe": profile})
    server = await service.create_server(
        owner_id="alice", project_id="one", name="safe", profile_id="safe"
    )
    with pytest.raises(MCPInventoryError) as error:
        await service.discover(owner_id="alice", project_id="one", server_id=server.id)
    assert error.value.code == "transport_error"
    persisted = await repository.get(owner_id="alice", project_id="one", server_id=server.id)
    assert persisted is not None
    assert persisted.health is MCPHealth.ERROR
    assert persisted.last_error_code == "transport_error"
    assert "not-a-real-executable-secret-123" not in repr(persisted)
    await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_official_stdio_discovery_persists_three_tools(tmp_path: Path) -> None:
    store, repository = await _repository(tmp_path / "real.db")
    profile = ServerProfile(
        command=sys.executable,
        args=(str(_SCRIPT), str(tmp_path / "pid")),
        cwd=str(_SCRIPT.parent),
    )
    service = MCPInventoryService(repository, profiles={"official-test": profile})
    server = await service.create_server(
        owner_id="alice", project_id="one", name="official", profile_id="official-test"
    )
    tools = await service.discover(owner_id="alice", project_id="one", server_id=server.id)
    assert {tool.name for tool in tools} == {"echo_evidence", "write_note", "env_probe"}
    assert all(not tool.enabled for tool in tools)
    persisted = await repository.get(owner_id="alice", project_id="one", server_id=server.id)
    assert persisted is not None and persisted.health is MCPHealth.HEALTHY
    assert persisted.last_seen is not None
    await store.close()
