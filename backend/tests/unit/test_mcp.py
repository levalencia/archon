"""Tests for the MCP protocol, transport stubs, and route."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.protocol import MCPServer
from app.mcp.transport import SSETransport, StdioTransport
from app.routes.mcp import router


# ---- MCPServer unit tests ----


@pytest.fixture
def server() -> MCPServer:
    s = MCPServer()
    s.register_tool("echo", "Echoes input", lambda text="": {"echo": text})
    return s


@pytest.mark.asyncio
async def test_tools_list(server: MCPServer) -> None:
    resp = await server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert resp["id"] == 1
    assert len(resp["result"]["tools"]) == 1
    assert resp["result"]["tools"][0]["name"] == "echo"


@pytest.mark.asyncio
async def test_tools_call(server: MCPServer) -> None:
    resp = await server.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"text": "hello"}},
    })
    assert resp["result"]["content"] == {"echo": "hello"}


@pytest.mark.asyncio
async def test_unknown_tool(server: MCPServer) -> None:
    resp = await server.handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "nope"},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_unknown_method(server: MCPServer) -> None:
    resp = await server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "foo/bar"})
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_invalid_jsonrpc(server: MCPServer) -> None:
    resp = await server.handle_request({"id": 5, "method": "tools/list"})
    assert resp["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_async_handler() -> None:
    server = MCPServer()

    async def async_echo(text: str = "") -> dict:
        return {"echo": text}

    server.register_tool("async_echo", "Async echo", async_echo)
    resp = await server.handle_request({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {"name": "async_echo", "arguments": {"text": "hi"}},
    })
    assert resp["result"]["content"] == {"echo": "hi"}


# ---- Transport stub tests ----


def test_stdio_transport_instantiation() -> None:
    t = StdioTransport()
    assert hasattr(t, "read_request")
    assert hasattr(t, "write_response")


def test_sse_transport_format() -> None:
    t = SSETransport()
    frame = t.format_sse("message", {"ok": True})
    assert "event: message" in frame
    assert "data:" in frame


# ---- Route integration tests ----


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_mcp_tools_list_route() -> None:
    client = TestClient(_build_app())
    resp = client.get("/api/mcp/tools")
    assert resp.status_code == 200
    tools = resp.json()
    names = {t["name"] for t in tools}
    assert {"web_search", "code_sandbox", "image_gen"} == names


def test_mcp_request_tools_list() -> None:
    client = TestClient(_build_app())
    resp = client.post(
        "/api/mcp/request",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data


def test_mcp_request_tools_call() -> None:
    client = TestClient(_build_app())
    resp = client.post(
        "/api/mcp/request",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "web_search", "arguments": {"query": "test"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["content"]["query"] == "test"
