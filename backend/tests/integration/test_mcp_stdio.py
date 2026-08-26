"""Exercise a real official MCP SDK subprocess rather than a mock."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.mcp.client import MCPClientError, StdioMCPClient
from app.mcp.models import ServerProfile

_SCRIPT = Path(__file__).parents[1] / "fixtures" / "mcp_test_server.py"


def _profile(pid_file: Path, **limits: object) -> ServerProfile:
    values: dict[str, object] = {
        "command": sys.executable,
        "args": (str(_SCRIPT), str(pid_file)),
        "cwd": str(_SCRIPT.parent),
    }
    values.update(limits)
    return ServerProfile(**values)  # type: ignore[arg-type]


def _assert_process_gone(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_official_stdio_initialize_list_call_env_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHON_SECRET_CANARY", "must-not-reach-child")
    pid_file = tmp_path / "server.pid"
    client = StdioMCPClient(_profile(pid_file))

    await client.initialize()
    _assert_process_gone(pid_file)

    tools = await client.list_tools()
    assert {tool.name for tool in tools} == {"echo_evidence", "write_note", "env_probe"}
    echo = next(tool for tool in tools if tool.name == "echo_evidence")
    write = next(tool for tool in tools if tool.name == "write_note")
    assert (echo.read_only, echo.destructive, echo.version) == (True, False, "1.0.0")
    assert (write.read_only, write.destructive) == (False, True)
    assert echo.input_schema["required"] == ["evidence"]
    _assert_process_gone(pid_file)

    result = await client.call_tool("echo_evidence", {"evidence": "source:42"})
    assert result.structured_content == {"evidence": "source:42"}
    assert result.is_error is False
    _assert_process_gone(pid_file)

    probe = await client.call_tool("env_probe", {})
    assert probe.structured_content == {"secret_canary_present": False}
    assert "must-not-reach-child" not in repr(probe)
    _assert_process_gone(pid_file)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stdio_timeout_result_cap_and_cleanup(tmp_path: Path) -> None:
    pid_file = tmp_path / "bounded.pid"
    timeout_client = StdioMCPClient(
        _profile(pid_file, connect_timeout_seconds=3.0, call_timeout_seconds=0.05)
    )
    with pytest.raises(MCPClientError) as timeout_error:
        await timeout_client.call_tool("echo_evidence", {"evidence": "late", "delay_seconds": 1.0})
    assert timeout_error.value.code == "timeout"
    _assert_process_gone(pid_file)

    capped_client = StdioMCPClient(_profile(pid_file, max_result_bytes=256))
    with pytest.raises(MCPClientError) as size_error:
        await capped_client.call_tool("echo_evidence", {"evidence": "x", "repeat": 2_000})
    assert size_error.value.code == "result_too_large"
    _assert_process_gone(pid_file)
