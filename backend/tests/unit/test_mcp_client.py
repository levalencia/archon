from __future__ import annotations

from types import MappingProxyType

import pytest
from mcp.types import Tool

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
        (Tool(name="bad name", input_schema={"type": "object"}), "invalid_tool_name"),
        (Tool(name="valid", input_schema={"type": "array"}), "invalid_tool_schema"),
        (
            Tool(name="valid", input_schema={"type": "object"}, _meta={"version": 7}),
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
