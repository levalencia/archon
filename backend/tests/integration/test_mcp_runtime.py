"""MCP inventory bindings execute only through runtime policy and approval."""

from __future__ import annotations

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update

from app.agents.mock_llm import MockLLM
from app.mcp.inventory import MCPInventoryService
from app.mcp.models import MCPCallResult, ServerProfile, ToolDescriptor
from app.mcp.repository import MCPHealth, MCPRepository
from app.mcp.runtime import MCPRuntimeError, MCPRuntimeToolProvider, normalize_input_schema
from app.routes.chat import get_tool_registry
from app.runtime import (
    AgentEventKind,
    AgentRuntime,
    AuthorizationOutcome,
    Message,
    ModelResponse,
    RecordingEventSink,
    Role,
    StopReason,
    ToolCall,
)
from app.security.default_policy import default_policy_engine
from app.security.policy import RiskClass
from app.services.db_store import DatabaseStore, MCPToolRow

_SCRIPT = Path(__file__).parents[1] / "fixtures" / "mcp_test_server.py"


@pytest.mark.parametrize(
    "schema",
    [
        None,
        [],
        {"type": ["object", "null"]},
        {"type": "object", "additionalProperties": {}},
        {"type": "object", "properties": []},
        {"type": "object", "required": {}},
        {"type": "object", "required": [None]},
        {"type": "object", "title": []},
        {"type": "object", "properties": {"x": {"type": []}}},
        {"type": "object", "properties": {"x": {"type": "string", "enum": {}}}},
        {"type": "object", "properties": {"x": {"type": "integer", "enum": [True]}}},
        {"type": "object", "properties": {"x": {"type": "number", "enum": [float("inf")]}}},
        {"type": "object", "properties": {"x": {"type": "boolean", "default": 0}}},
        {"type": "object", "properties": {"x": {"type": "string", "title": {}}}},
    ],
)
def test_untrusted_schema_values_always_raise_stable_runtime_error(schema: object) -> None:
    with pytest.raises(MCPRuntimeError) as error:
        normalize_input_schema(schema)
    assert error.value.code == "unsupported_tool_schema"


def test_huge_json_integer_enum_and_default_do_not_overflow() -> None:
    huge = 10**1000
    schema = {
        "type": "object",
        "properties": {
            "value": {"type": "number", "enum": [huge], "default": huge},
        },
        "required": ["value"],
    }
    normalized = normalize_input_schema(schema)
    assert normalized["properties"]["value"]["enum"] == [huge]
    assert "default" not in normalized["properties"]["value"]


async def _real_provider(
    tmp_path: Path,
) -> tuple[DatabaseStore, MCPRepository, MCPRuntimeToolProvider]:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    profile = ServerProfile(
        command=sys.executable,
        args=(str(_SCRIPT), str(tmp_path / "pid")),
        cwd=str(_SCRIPT.parent),
    )
    inventory = MCPInventoryService(repository, profiles={"official-test": profile})
    server = await inventory.create_server(
        owner_id="alice",
        project_id="one",
        name="Official Server",
        profile_id="official-test",
        enabled=True,
    )
    tools = await inventory.discover(owner_id="alice", project_id="one", server_id=server.id)
    echo = next(tool for tool in tools if tool.name == "echo_evidence")
    await repository.set_tool_enabled(
        owner_id="alice",
        project_id="one",
        server_id=server.id,
        tool_id=echo.id,
        enabled=True,
    )
    return (
        store,
        repository,
        MCPRuntimeToolProvider(repository, profiles={"official-test": profile}),
    )


class _Approver:
    async def authorize(self, request: Any) -> AuthorizationOutcome:
        return AuthorizationOutcome(
            True,
            request.tool_call_id,
            request.tool_name,
            request.arguments_hash,
            "user_approved",
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_enabled_tool_is_governed_and_executes_only_after_approval(
    tmp_path: Path,
) -> None:
    store, _repository, provider = await _real_provider(tmp_path)
    specs = await provider.for_scope("alice", "one")
    assert [spec.name for spec in specs] == ["mcp_official_server_echo_evidence"]
    spec = specs[0]
    assert spec.requires_approval
    assert spec.risk_classes == frozenset({RiskClass.NETWORK, RiskClass.READ})
    assert spec.input_schema["additionalProperties"] is False
    registry = get_tool_registry(bound_tools=specs)
    call = ToolCall("mcp-call", spec.name, {"evidence": "verified", "repeat": 2})

    denied_sink = RecordingEventSink()
    denied = await AgentRuntime(
        MockLLM([ModelResponse(tool_calls=(call,))]),
        registry,
        policy_engine=default_policy_engine(),
        events=denied_sink,
    ).run([Message(Role.USER, "echo")])
    assert denied.stop_reason is StopReason.APPROVAL_UNAVAILABLE
    assert AgentEventKind.TOOL_CALL_COMPLETED not in [event.kind for event in denied_sink.events]

    approved_sink = RecordingEventSink()
    approved = await AgentRuntime(
        MockLLM([ModelResponse(tool_calls=(call,)), ModelResponse("done")]),
        registry,
        policy_engine=default_policy_engine(),
        authorizer=_Approver(),
        events=approved_sink,
    ).run([Message(Role.USER, "echo")])
    assert approved.stop_reason is StopReason.COMPLETED
    assert approved.tool_calls[0]["result"]["structured_content"] == {
        "evidence": "verifiedverified"
    }
    kinds = [event.kind for event in approved_sink.events]
    assert AgentEventKind.POLICY_DECIDED in kinds
    assert AgentEventKind.APPROVAL_REQUIRED in kinds
    assert AgentEventKind.APPROVAL_DECIDED in kinds
    assert AgentEventKind.TOOL_CALL_COMPLETED in kinds
    await store.close()


class _CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> MCPCallResult:
        self.calls += 1
        return MCPCallResult(({"type": "text", "text": name},), dict(arguments), False)


@pytest.mark.asyncio
async def test_scope_filter_risks_disable_toctou_and_schema_rejection(tmp_path: Path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'bindings.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    profile = ServerProfile(command=sys.executable)
    client = _CountingClient()
    provider = MCPRuntimeToolProvider(
        repository, profiles={"safe": profile}, client_factory=lambda _profile: client
    )
    server = await repository.create(
        owner_id="alice", project_id="one", name="same/name", profile_id="safe", enabled=True
    )
    descriptors = (
        ToolDescriptor(
            "write-note",
            None,
            "write",
            {"type": "object", "properties": {"note": {"type": "string"}}},
            False,
            True,
            "1",
        ),
        ToolDescriptor(
            "bad-schema",
            None,
            None,
            {
                "type": "object",
                "properties": {"value": {"type": "string", "pattern": "secret"}},
            },
            True,
            False,
            "1",
        ),
    )
    tools = await repository.replace_inventory(
        owner_id="alice", project_id="one", server_id=server.id, tools=descriptors
    )
    for tool in tools:
        await repository.set_tool_enabled(
            owner_id="alice", project_id="one", server_id=server.id, tool_id=tool.id, enabled=True
        )
    await repository.update_health(
        owner_id="alice", project_id="one", server_id=server.id, health=MCPHealth.HEALTHY
    )

    specs = await provider.for_scope("alice", "one")
    assert [spec.name for spec in specs] == ["mcp_same_name_write_note"]
    assert specs[0].risk_classes == frozenset(
        {RiskClass.NETWORK, RiskClass.WRITE, RiskClass.EXTERNAL_SIDE_EFFECT}
    )
    persisted = await repository.list_tools(owner_id="alice", project_id="one", server_id=server.id)
    assert not next(tool for tool in persisted if tool.name == "bad-schema").enabled
    assert await provider.for_scope("mallory", "one") == ()
    assert await provider.for_scope("alice", "other") == ()

    await repository.update(owner_id="alice", project_id="one", server_id=server.id, enabled=False)
    registry = get_tool_registry(bound_tools=specs)
    with pytest.raises(MCPRuntimeError, match="mcp_binding_changed"):
        await registry.execute(specs[0].name, {"note": "blocked"})
    assert client.calls == 0
    assert await provider.for_scope("alice", "one") == ()
    await store.close()


@pytest.mark.asyncio
async def test_metadata_first_selection_never_parses_irrelevant_invalid_schema(
    tmp_path: Path,
) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'lazy-schema.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    profile = ServerProfile(command=sys.executable)
    provider = MCPRuntimeToolProvider(repository, profiles={"safe": profile})
    server = await repository.create(
        owner_id="alice", project_id="one", name="utilities", profile_id="safe", enabled=True
    )
    tools = await repository.replace_inventory(
        owner_id="alice",
        project_id="one",
        server_id=server.id,
        tools=(
            ToolDescriptor(
                "weather_forecast",
                "Weather",
                "Get a weather forecast",
                {"type": "object", "properties": {"city": {"type": "string"}}},
                True,
                False,
                "1",
            ),
            ToolDescriptor(
                "delete_database",
                "Delete database",
                "Permanently delete a database",
                {"type": "object", "properties": {"name": {"type": "string"}}},
                False,
                True,
                "1",
            ),
        ),
    )
    for tool in tools:
        await repository.set_tool_enabled(
            owner_id="alice", project_id="one", server_id=server.id, tool_id=tool.id, enabled=True
        )
    bad = next(tool for tool in tools if tool.name == "delete_database")
    async with store.session_factory() as session:
        await session.execute(
            update(MCPToolRow).where(MCPToolRow.id == bad.id).values(input_schema_json="{broken")
        )
        await session.commit()
    await repository.update_health(
        owner_id="alice", project_id="one", server_id=server.id, health=MCPHealth.HEALTHY
    )

    selected = await provider.for_scope(
        "alice", "one", intent="weather forecast", max_schema_count=2
    )
    streamed = await provider.for_scope(
        "alice", "one", intent="weather forecast", max_schema_count=2
    )
    assert [item.name for item in selected] == ["mcp_utilities_weather_forecast"]
    assert [(item.name, dict(item.input_schema)) for item in streamed] == [
        (item.name, dict(item.input_schema)) for item in selected
    ]
    bad_capability_id = f"mcp.{server.id}.{bad.id}"
    denied = await provider.for_scope(
        "alice",
        "one",
        intent="delete database",
        disabled_capability_ids=frozenset({bad_capability_id}),
        max_schema_count=2,
    )
    assert denied == ()
    assert all(
        definition.name != "mcp_utilities_delete_database"
        for definition in get_tool_registry(bound_tools=denied).definitions()
    )
    async with store.session_factory() as session:
        assert await session.scalar(select(MCPToolRow.enabled).where(MCPToolRow.id == bad.id))

    assert (
        await provider.for_scope("alice", "one", intent="delete database", max_schema_count=2) == ()
    )
    async with store.session_factory() as session:
        assert not await session.scalar(select(MCPToolRow.enabled).where(MCPToolRow.id == bad.id))
    await store.close()


@pytest.mark.asyncio
async def test_schema_budget_counts_serialized_schema_bytes(tmp_path: Path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'schema-budget.db'}")
    await store.initialize()
    repository = MCPRepository(store.session_factory)
    profile = ServerProfile(command=sys.executable)
    provider = MCPRuntimeToolProvider(repository, profiles={"safe": profile})
    server = await repository.create(
        owner_id="alice", project_id="one", name="large", profile_id="safe", enabled=True
    )
    tools = await repository.replace_inventory(
        owner_id="alice",
        project_id="one",
        server_id=server.id,
        tools=(
            ToolDescriptor(
                "search_large",
                "Search large",
                "Search a large catalog",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "enum": ["x" * 4096]},
                    },
                },
                True,
                False,
                "1",
            ),
        ),
    )
    await repository.set_tool_enabled(
        owner_id="alice", project_id="one", server_id=server.id, tool_id=tools[0].id, enabled=True
    )
    await repository.update_health(
        owner_id="alice", project_id="one", server_id=server.id, health=MCPHealth.HEALTHY
    )

    excluded = await provider.for_scope(
        "alice", "one", intent="search large", schema_context_budget=1024
    )
    admitted = await provider.for_scope(
        "alice", "one", intent="search large", schema_context_budget=8192
    )

    assert excluded == ()
    assert [item.name for item in admitted] == ["mcp_large_search_large"]
    await store.close()
