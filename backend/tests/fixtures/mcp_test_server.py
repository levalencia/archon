"""Deterministic official-SDK stdio MCP server for integration tests."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("archon-test-server", version="1.0.0")
_notes: list[str] = []

if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(str(os.getpid()), encoding="ascii")


@server.tool(
    title="Echo evidence",
    description="Returns deterministic evidence.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
    meta={"version": "1.0.0"},
    structured_output=True,
)
def echo_evidence(evidence: str, delay_seconds: float = 0, repeat: int = 1) -> dict[str, str]:
    """Echo evidence, optionally delayed or repeated to exercise client bounds."""
    if delay_seconds:
        time.sleep(delay_seconds)
    return {"evidence": evidence * repeat}


@server.tool(
    title="Write note",
    description="Mutates deterministic in-memory test storage.",
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True),
    meta={"version": "1.0.0"},
    structured_output=True,
)
def write_note(note: str) -> dict[str, object]:
    """Store a note in memory."""
    _notes.append(note)
    return {"stored": note, "count": len(_notes)}


@server.tool(
    title="Environment probe",
    description="Reports only whether the secret canary is present, never its value.",
    annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False),
    meta={"version": "1.0.0"},
    structured_output=True,
)
def env_probe() -> dict[str, bool]:
    """Return only canary presence."""
    return {"secret_canary_present": "ARCHON_SECRET_CANARY" in os.environ}


if __name__ == "__main__":
    server.run("stdio")
