"""MCP (Model Context Protocol) server — JSON-RPC 2.0 stub.

Implements the core MCPServer that can register tools and dispatch
``tools/list`` and ``tools/call`` JSON-RPC methods.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class MCPServer:
    """Minimal MCP-compatible JSON-RPC 2.0 server."""

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        handler: Callable[..., Any],
    ) -> None:
        """Register a tool that can be invoked via ``tools/call``."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "handler": handler,
        }

    def list_tools(self) -> list[dict[str, str]]:
        """Return metadata for every registered tool."""
        return [{"name": t["name"], "description": t["description"]} for t in self._tools.values()]

    async def handle_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a JSON-RPC 2.0 request and return a response dict."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if request.get("jsonrpc") != "2.0":
            return self._error(req_id, -32600, "Invalid Request: missing jsonrpc 2.0")

        if method == "tools/list":
            return self._result(req_id, {"tools": self.list_tools()})

        if method == "tools/call":
            return await self._call_tool(req_id, params)

        return self._error(req_id, -32601, f"Method not found: {method}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_tool(self, req_id: Any, params: dict) -> dict:
        name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(name)
        if tool is None:
            return self._error(req_id, -32602, f"Unknown tool: {name}")

        try:
            result = tool["handler"](**arguments)
            # Support both sync and async handlers
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:  # noqa: BLE001
            return self._error(req_id, -32000, f"Tool execution error: {exc}")

        return self._result(req_id, {"content": result})

    @staticmethod
    def _result(req_id: Any, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
