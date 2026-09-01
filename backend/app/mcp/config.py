"""Strict deployment-owned MCP profile loader.

Profiles are opt-in: entries without ``enabled: true`` never reach a client factory.
Inline HTTP headers and arbitrary subprocess environment variables are deliberately unsupported.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from app.mcp.models import MCPServerProfile, RemoteServerProfile, ServerProfile

_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_COMMON = {"transport", "enabled"}
_STDIO = {
    "command",
    "args",
    "cwd",
    "env",
    "connect_timeout_seconds",
    "discovery_timeout_seconds",
    "call_timeout_seconds",
    "max_result_bytes",
}
_HTTP = {
    "url",
    "credential_ref",
    "allow_insecure_loopback",
    "connect_timeout_seconds",
    "discovery_timeout_seconds",
    "call_timeout_seconds",
    "response_timeout_seconds",
    "max_result_bytes",
    "reconnect_attempts",
    "reconnect_backoff_seconds",
}


class MCPProfileConfigError(ValueError):
    """Stable error for malformed deployment profile configuration."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MCPProfileConfigError("duplicate_profile_key")
        result[key] = value
    return result


def load_mcp_profiles(raw: str | None) -> Mapping[str, MCPServerProfile]:
    """Load enabled profiles from strict JSON; disabled is the default."""

    if raw is None or not raw.strip():
        return MappingProxyType({})
    try:
        document = json.loads(raw, object_pairs_hook=_object)
    except (json.JSONDecodeError, MCPProfileConfigError):
        raise MCPProfileConfigError("invalid_mcp_profiles") from None
    if type(document) is not dict:
        raise MCPProfileConfigError("invalid_mcp_profiles")
    loaded: dict[str, MCPServerProfile] = {}
    try:
        for profile_id, value in document.items():
            if type(profile_id) is not str or not _PROFILE_ID.fullmatch(profile_id):
                raise MCPProfileConfigError("invalid_profile_id")
            if type(value) is not dict:
                raise MCPProfileConfigError("invalid_profile")
            transport = value.get("transport", "stdio")
            allowed = _COMMON | (_STDIO if transport == "stdio" else _HTTP)
            if transport not in {"stdio", "streamable_http"} or set(value) - allowed:
                raise MCPProfileConfigError("invalid_profile")
            enabled = value.get("enabled", False)
            if type(enabled) is not bool:
                raise MCPProfileConfigError("invalid_profile")
            values = {key: item for key, item in value.items() if key not in _COMMON}
            if "args" in values:
                if type(values["args"]) is not list:
                    raise MCPProfileConfigError("invalid_profile")
                values["args"] = tuple(values["args"])
            profile: MCPServerProfile
            if transport == "stdio":
                profile = ServerProfile(**values)
            else:
                profile = RemoteServerProfile(**values)
            if enabled:
                loaded[profile_id] = profile
    except (TypeError, ValueError) as error:
        if isinstance(error, MCPProfileConfigError):
            raise
        raise MCPProfileConfigError("invalid_profile") from None
    return MappingProxyType(loaded)
