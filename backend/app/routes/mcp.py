"""MCP route — exposes Archon tools via JSON-RPC 2.0."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.mcp.protocol import MCPServer

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# Singleton MCP server with built-in tool stubs
# ---------------------------------------------------------------------------

_mcp_server = MCPServer()


def _web_search(query: str = "") -> dict[str, Any]:
    """Stub: web search tool."""
    return {"results": [], "query": query, "note": "stub — not yet implemented"}


def _code_sandbox(code: str = "", language: str = "python") -> dict[str, Any]:
    """Stub: code execution sandbox."""
    return {"output": "", "code": code, "language": language, "note": "stub — not yet implemented"}


def _image_gen(prompt: str = "") -> dict[str, Any]:
    """Stub: image generation tool."""
    return {"url": "", "prompt": prompt, "note": "stub — not yet implemented"}


_mcp_server.register_tool("web_search", "Search the web for information", _web_search)
_mcp_server.register_tool("code_sandbox", "Execute code in a sandboxed environment", _code_sandbox)
_mcp_server.register_tool("image_gen", "Generate images from text prompts", _image_gen)


def get_mcp_server() -> MCPServer:
    """Return the module-level MCP server (useful for testing)."""
    return _mcp_server


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/request")
async def mcp_request(body: dict[str, Any]) -> dict[str, Any]:
    """Handle a JSON-RPC 2.0 request routed to the MCP server."""
    return await _mcp_server.handle_request(body)


@router.get("/tools")
async def mcp_tools() -> list[dict[str, str]]:
    """List all registered MCP tools."""
    return _mcp_server.list_tools()
