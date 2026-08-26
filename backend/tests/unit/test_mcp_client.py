from __future__ import annotations

from types import MappingProxyType

import pytest
from mcp.types import ListToolsResult, PaginatedRequestParams, Tool

from app.mcp.client import MCPClientError, StdioMCPClient
from app.mcp.models import ServerProfile


def test_server_profile_is_frozen_strict_and_filters_environment_configuration() -> None:
    with pytest.raises(ValueError, match="invalid_profile_env"):
        ServerProfile(command="python", env={"API_TOKEN": "secret"})
    with pytest.raises(ValueError, match="invalid_profile_args"):
        ServerProfile(command="python", args=["server.py"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid_profile_cwd"):
        ServerProfile(command="python", cwd="relative")
    with pytest.raises(ValueError, match="invalid_connect_timeout"):
        ServerProfile(command="python", connect_timeout_seconds=True)
    with pytest.raises(ValueError, match="invalid_call_timeout"):
        ServerProfile(command="python", call_timeout_seconds=0)
    with pytest.raises(ValueError, match="invalid_result_limit"):
        ServerProfile(command="python", max_result_bytes=0)

    source = {"TZ": "UTC"}
    profile = ServerProfile(command="python", args=("server.py",), env=source)
    source["TZ"] = "changed"
    assert profile.env == {"TZ": "UTC"}
    assert isinstance(profile.env, MappingProxyType)
    with pytest.raises(TypeError):
        profile.env["TZ"] = "Europe/London"  # type: ignore[index]
    with pytest.raises(AttributeError):
        profile.command = "sh"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("tool", "code"),
    [
        (Tool(name="bad name", inputSchema={"type": "object"}), "invalid_tool_name"),
        (Tool(name="valid", inputSchema={"type": "array"}), "invalid_tool_schema"),
        (
            Tool(name="valid", inputSchema={"type": "object"}, _meta={"version": 7}),
            "invalid_tool_version",
        ),
    ],
)
def test_invalid_tool_metadata_is_rejected(tool: Tool, code: str) -> None:
    with pytest.raises(MCPClientError) as error:
        StdioMCPClient._normalize_tool(tool)
    assert error.value.code == code
    assert str(error.value) == code


def test_client_rejects_non_profile_configuration() -> None:
    with pytest.raises(TypeError, match="ServerProfile"):
        StdioMCPClient({"command": "user-controlled"})  # type: ignore[arg-type]


class _PaginatedSession:
    def __init__(self, pages: dict[str | None, ListToolsResult]) -> None:
        self.pages = pages
        self.cursors: list[str | None] = []

    async def list_tools(self, *, params: PaginatedRequestParams) -> ListToolsResult:
        cursor = params.cursor
        self.cursors.append(cursor)
        return self.pages[cursor]


@pytest.mark.asyncio
async def test_list_tools_follows_sdk_cursors_and_aggregates_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _PaginatedSession(
        {
            None: ListToolsResult(
                tools=[Tool(name="first", inputSchema={"type": "object"})], nextCursor="two"
            ),
            "two": ListToolsResult(tools=[Tool(name="second", inputSchema={"type": "object"})]),
        }
    )

    async def fake_with_session(self, operation, operation_timeout):  # type: ignore[no-untyped-def]
        return await operation(session)

    monkeypatch.setattr(StdioMCPClient, "_with_session", fake_with_session)
    tools = await StdioMCPClient(ServerProfile(command="python")).list_tools()
    assert [tool.name for tool in tools] == ["first", "second"]
    assert session.cursors == [None, "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pages", "code"),
    [
        (
            {
                None: ListToolsResult(
                    tools=[Tool(name="same", inputSchema={"type": "object"})],
                    nextCursor="two",
                ),
                "two": ListToolsResult(tools=[Tool(name="same", inputSchema={"type": "object"})]),
            },
            "duplicate_tool_name",
        ),
        (
            {
                None: ListToolsResult(tools=[], nextCursor="loop"),
                "loop": ListToolsResult(tools=[], nextCursor="loop"),
            },
            "invalid_pagination",
        ),
    ],
)
async def test_list_tools_rejects_cross_page_duplicates_and_cursor_loops(
    monkeypatch: pytest.MonkeyPatch,
    pages: dict[str | None, ListToolsResult],
    code: str,
) -> None:
    session = _PaginatedSession(pages)

    async def fake_with_session(self, operation, operation_timeout):  # type: ignore[no-untyped-def]
        return await operation(session)

    monkeypatch.setattr(StdioMCPClient, "_with_session", fake_with_session)
    with pytest.raises(MCPClientError) as error:
        await StdioMCPClient(ServerProfile(command="python")).list_tools()
    assert error.value.code == code
