"""Strict immutable models at the MCP subprocess trust boundary."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

# Profiles are deployment-owned allowlist entries. Only deliberately non-secret,
# non-loader environment settings may be added to the filtered child environment.
SAFE_PROFILE_ENV_KEYS = frozenset({"LANG", "LC_ALL", "TZ", "MCP_TEST_MODE"})


@dataclass(frozen=True, slots=True)
class ServerProfile:
    """A fixed, injected stdio server profile; never construct this from user input."""

    command: str
    args: tuple[str, ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    connect_timeout_seconds: float = 10.0
    discovery_timeout_seconds: float = 30.0
    call_timeout_seconds: float = 30.0
    max_result_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if type(self.command) is not str or not self.command or "\x00" in self.command:
            raise ValueError("invalid_profile_command")
        if type(self.args) is not tuple or any(
            type(arg) is not str or not arg or "\x00" in arg for arg in self.args
        ):
            raise ValueError("invalid_profile_args")
        if self.cwd is not None and (
            type(self.cwd) is not str or not self.cwd.startswith("/") or "\x00" in self.cwd
        ):
            raise ValueError("invalid_profile_cwd")
        for value, code in (
            (self.connect_timeout_seconds, "invalid_connect_timeout"),
            (self.discovery_timeout_seconds, "invalid_discovery_timeout"),
            (self.call_timeout_seconds, "invalid_call_timeout"),
        ):
            if type(value) not in (int, float) or not 0 < value <= 120:
                raise ValueError(code)
        if type(self.max_result_bytes) is not int or not 1 <= self.max_result_bytes <= 10_000_000:
            raise ValueError("invalid_result_limit")
        if not isinstance(self.env, Mapping):
            raise ValueError("invalid_profile_env")
        copied = dict(self.env)
        if any(
            type(key) is not str
            or type(value) is not str
            or key not in SAFE_PROFILE_ENV_KEYS
            or not key
            or "\x00" in key
            or "\x00" in value
            for key, value in copied.items()
        ):
            raise ValueError("invalid_profile_env")
        object.__setattr__(self, "env", MappingProxyType(copied))


@dataclass(frozen=True, slots=True)
class RemoteServerProfile:
    """Deployment-owned Streamable HTTP endpoint without inline credentials."""

    url: str
    credential_ref: str | None = field(default=None, repr=False)
    allow_insecure_loopback: bool = False
    connect_timeout_seconds: float = 10.0
    discovery_timeout_seconds: float = 30.0
    call_timeout_seconds: float = 30.0
    response_timeout_seconds: float = 30.0
    max_result_bytes: int = 1_000_000
    reconnect_attempts: int = 2
    reconnect_backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        if type(self.url) is not str or not self.url or "\x00" in self.url:
            raise ValueError("invalid_remote_url")
        try:
            parsed = urlsplit(self.url)
            port = parsed.port
        except ValueError:
            raise ValueError("invalid_remote_url") from None
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/")
            or port == 0
        ):
            raise ValueError("invalid_remote_url")
        hostname = parsed.hostname.rstrip(".").lower()
        loopback = hostname == "localhost"
        with suppress(ValueError):
            loopback = loopback or ipaddress.ip_address(hostname).is_loopback
        if parsed.scheme != "https" and not (loopback and self.allow_insecure_loopback is True):
            raise ValueError("insecure_remote_url")
        if self.credential_ref is not None and (
            type(self.credential_ref) is not str
            or not self.credential_ref
            or len(self.credential_ref) > 256
            or any(character in self.credential_ref for character in "\r\n\x00")
        ):
            raise ValueError("invalid_credential_ref")
        for value, code in (
            (self.connect_timeout_seconds, "invalid_connect_timeout"),
            (self.discovery_timeout_seconds, "invalid_discovery_timeout"),
            (self.call_timeout_seconds, "invalid_call_timeout"),
            (self.response_timeout_seconds, "invalid_response_timeout"),
        ):
            if type(value) not in (int, float) or not 0 < value <= 120:
                raise ValueError(code)
        if type(self.max_result_bytes) is not int or not 1 <= self.max_result_bytes <= 10_000_000:
            raise ValueError("invalid_result_limit")
        if type(self.reconnect_attempts) is not int or not 0 <= self.reconnect_attempts <= 3:
            raise ValueError("invalid_reconnect_attempts")
        if (
            type(self.reconnect_backoff_seconds) not in (int, float)
            or not 0 < self.reconnect_backoff_seconds <= 5
        ):
            raise ValueError("invalid_reconnect_backoff")


MCPServerProfile = ServerProfile | RemoteServerProfile


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Normalized, conservative tool metadata returned to policy code."""

    name: str
    title: str | None
    description: str | None
    input_schema: Mapping[str, Any]
    read_only: bool
    destructive: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class MCPCallResult:
    """A validated and size-bounded MCP tool result."""

    content: tuple[Mapping[str, Any], ...]
    structured_content: Mapping[str, Any] | None
    is_error: bool


def profile_transport(profile: MCPServerProfile) -> str:
    """Return the only persisted connection fact for a deployment-owned profile."""
    return "streamable_http" if isinstance(profile, RemoteServerProfile) else "stdio"
