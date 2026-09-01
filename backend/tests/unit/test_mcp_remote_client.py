from __future__ import annotations

import json
from collections.abc import Mapping

import httpx2
import pytest

from app.mcp.client import MCPClientError, RemoteMCPClient, StdioMCPClient, create_mcp_client
from app.mcp.config import MCPProfileConfigError, load_mcp_profiles
from app.mcp.models import RemoteServerProfile, ServerProfile


def test_profile_loader_is_governed_and_profiles_are_disabled_by_default() -> None:
    raw = """{
      "local": {"transport": "stdio", "command": "python", "args": ["server.py"]},
      "remote": {"transport": "streamable_http", "enabled": true,
                 "url": "https://mcp.example.test/rpc", "credential_ref": "vault:mcp"}
    }"""
    profiles = load_mcp_profiles(raw)
    assert set(profiles) == {"remote"}
    assert isinstance(profiles["remote"], RemoteServerProfile)
    assert profiles["remote"].credential_ref == "vault:mcp"


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":{"transport":"streamable_http","enabled":true,"url":"https://x.test","headers":{"Authorization":"secret"}}}',
        '{"x":{"transport":"stdio","enabled":true,"command":"python","env":{"TOKEN":"secret"}}}',
        '{"bad id":{"transport":"stdio","enabled":true,"command":"python"}}',
    ],
)
def test_profile_loader_rejects_ungoverned_or_secret_bearing_configuration(raw: str) -> None:
    with pytest.raises(MCPProfileConfigError):
        load_mcp_profiles(raw)


def test_remote_profile_requires_https_unless_loopback_is_explicitly_allowed() -> None:
    with pytest.raises(ValueError, match="insecure_remote_url"):
        RemoteServerProfile(url="http://mcp.example.test/rpc")
    with pytest.raises(ValueError, match="insecure_remote_url"):
        RemoteServerProfile(url="http://127.0.0.1:8765/rpc")
    profile = RemoteServerProfile(url="http://127.0.0.1:8765/rpc", allow_insecure_loopback=True)
    assert profile.url == "http://127.0.0.1:8765/rpc"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@mcp.example.test/rpc",
        "https://mcp.example.test/rpc#fragment",
        "https://mcp.example.test/rpc?token=secret",
    ],
)
def test_remote_profile_rejects_ambiguous_or_secret_bearing_urls(url: str) -> None:
    with pytest.raises(ValueError):
        RemoteServerProfile(url=url, allow_insecure_loopback=True)


class _Credentials:
    def __init__(self) -> None:
        self.refs: list[str] = []

    def resolve(self, credential_ref: str) -> Mapping[str, str]:
        self.refs.append(credential_ref)
        return {"Authorization": "Bearer raw-secret"}


def test_remote_client_resolves_credentials_only_at_client_creation() -> None:
    credentials = _Credentials()
    captured: dict[str, object] = {}

    class FakeHTTPClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    profile = RemoteServerProfile(url="https://mcp.example.test/rpc", credential_ref="vault:mcp")
    client = RemoteMCPClient(
        profile, credential_provider=credentials, http_client_factory=FakeHTTPClient
    )
    assert credentials.refs == []
    built = client._build_http_client()
    assert isinstance(built, FakeHTTPClient)
    assert credentials.refs == ["vault:mcp"]
    assert captured["headers"] == {"Authorization": "Bearer raw-secret"}
    assert captured["follow_redirects"] is False
    assert captured["trust_env"] is False
    assert "raw-secret" not in repr(client)
    assert "raw-secret" not in repr(profile)


def test_remote_client_rejects_credential_headers_that_can_change_origin_or_protocol() -> None:
    class BadCredentials:
        def resolve(self, credential_ref: str) -> Mapping[str, str]:
            return {"Host": "evil.test"}

    client = RemoteMCPClient(
        RemoteServerProfile(url="https://mcp.example.test/rpc", credential_ref="vault:x"),
        credential_provider=BadCredentials(),
        http_client_factory=lambda **kwargs: kwargs,
    )
    with pytest.raises(MCPClientError) as error:
        client._build_http_client()
    assert error.value.code == "invalid_credentials"


def test_common_factory_preserves_stdio_compatibility_and_supports_remote() -> None:
    assert isinstance(create_mcp_client(ServerProfile(command="python")), StdioMCPClient)
    assert isinstance(
        create_mcp_client(RemoteServerProfile(url="https://mcp.example.test/rpc")),
        RemoteMCPClient,
    )


@pytest.mark.asyncio
async def test_health_check_has_bounded_exponential_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RemoteMCPClient(
        RemoteServerProfile(
            url="https://mcp.example.test/rpc",
            reconnect_attempts=2,
            reconnect_backoff_seconds=0.01,
        )
    )
    calls = 0
    delays: list[float] = []

    async def fake_initialize() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise MCPClientError("transport_error")

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(client, "initialize", fake_initialize)
    monkeypatch.setattr("app.mcp.client.asyncio.sleep", fake_sleep)
    assert await client.health_check() is True
    assert calls == 3
    assert delays == [0.01, 0.02]


@pytest.mark.asyncio
async def test_health_check_does_not_retry_non_transport_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RemoteMCPClient(RemoteServerProfile(url="https://mcp.example.test/rpc"))

    async def fake_initialize() -> None:
        raise MCPClientError("invalid_tool_schema")

    monkeypatch.setattr(client, "initialize", fake_initialize)
    assert await client.health_check() is False


@pytest.mark.asyncio
async def test_remote_client_discovers_tools_through_official_sdk_and_mock_transport() -> None:
    requests: list[str] = []

    async def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        requests.append(method)
        if method == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "serverInfo": {"name": "deterministic", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo safely",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        else:
            return httpx2.Response(202)
        return httpx2.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": result},
            headers={"content-type": "application/json"},
        )

    def client_factory(**kwargs: object) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler), **kwargs)

    client = RemoteMCPClient(
        RemoteServerProfile(url="https://mcp.example.test/rpc"),
        http_client_factory=client_factory,
    )
    tools = await client.list_tools()
    assert [tool.name for tool in tools] == ["echo"]
    assert requests == ["initialize", "notifications/initialized", "tools/list"]
