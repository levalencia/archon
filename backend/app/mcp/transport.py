"""MCP transport stubs — Stdio and SSE."""

from __future__ import annotations

import json
import sys
from typing import Any


class StdioTransport:
    """Read JSON-RPC messages from stdin, write responses to stdout.

    This is a stub interface — call ``read_request`` / ``write_response``
    in a loop to drive the MCP server over stdio.
    """

    def read_request(self) -> dict[str, Any] | None:
        """Read one JSON-RPC request from stdin. Returns *None* on EOF."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def write_response(self, response: dict[str, Any]) -> None:
        """Write a JSON-RPC response to stdout."""
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


class SSETransport:
    """Expose MCP over HTTP Server-Sent Events.

    This is a stub — concrete implementation would integrate with a
    framework like FastAPI's ``StreamingResponse``.
    """

    def __init__(self, base_path: str = "/api/mcp") -> None:
        self.base_path = base_path

    def format_sse(self, event: str, data: dict[str, Any]) -> str:
        """Format a dict as an SSE frame."""
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"
