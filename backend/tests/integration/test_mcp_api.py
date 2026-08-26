"""End-to-end authenticated HTTP tests for governed MCP inventory administration."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mcp.models import ServerProfile

_SCRIPT = Path(__file__).parents[1] / "fixtures" / "mcp_test_server.py"


def _settings(database: Path, *, rate_limit: int = 100) -> Settings:
    return Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{database}",
        memory_encryption_enabled=False,
        rate_limit_requests=rate_limit,
    )


def _profile(tmp_path: Path) -> ServerProfile:
    return ServerProfile(
        command=sys.executable,
        args=(str(_SCRIPT), str(tmp_path / "mcp.pid")),
        cwd=str(_SCRIPT.parent),
    )


def _register(client: TestClient, username: str) -> str:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return str(response.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_crud_discovery_enablement_restart_scope_and_no_profile_secrets(tmp_path: Path) -> None:
    database = tmp_path / "api.db"
    settings = _settings(database)
    profile = _profile(tmp_path)
    app = create_app(settings=settings, mcp_profiles={"official-test": profile})

    with TestClient(app) as client:
        alice = _register(client, "mcp-alice")
        bob = _register(client, "mcp-bob")

        unknown = client.post(
            "/api/mcp/servers",
            headers=_auth(alice),
            json={
                "project_id": "project-a",
                "name": "bad",
                "profile_id": "missing",
                "enabled": True,
            },
        )
        assert unknown.status_code == 422
        assert unknown.json()["detail"]["code"] == "unknown_profile"

        created = client.post(
            "/api/mcp/servers",
            headers=_auth(alice),
            json={
                "project_id": "project-a",
                "name": "local test",
                "profile_id": "official-test",
                "enabled": True,
            },
        )
        assert created.status_code == 201
        server = created.json()
        server_id = server["id"]
        serialized = created.text
        assert server["health"] == "unknown"
        assert profile.command not in serialized
        assert str(_SCRIPT) not in serialized
        assert "args" not in server and "env" not in server

        listed = client.get(
            "/api/mcp/servers", headers=_auth(alice), params={"project_id": "project-a"}
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [server_id]

        for headers, project in ((_auth(bob), "project-a"), (_auth(alice), "project-b")):
            hidden = client.get(
                f"/api/mcp/servers/{server_id}", headers=headers, params={"project_id": project}
            )
            assert hidden.status_code == 404

        discovered = client.post(
            f"/api/mcp/servers/{server_id}/discover",
            headers=_auth(alice),
            params={"project_id": "project-a"},
        )
        assert discovered.status_code == 200, discovered.text
        tools = discovered.json()
        assert {tool["name"] for tool in tools} == {
            "echo_evidence",
            "write_note",
            "env_probe",
        }
        assert all(tool["enabled"] is False for tool in tools)

        enabled = client.patch(
            f"/api/mcp/servers/{server_id}/tools/echo_evidence",
            headers=_auth(alice),
            params={"project_id": "project-a"},
            json={"enabled": True},
        )
        assert enabled.status_code == 200
        assert enabled.json()["enabled"] is True

        rejected_extra = client.patch(
            f"/api/mcp/servers/{server_id}",
            headers=_auth(alice),
            params={"project_id": "project-a"},
            json={"enabled": False, "command": "malicious"},
        )
        assert rejected_extra.status_code == 422

    # A fresh application/service instance must expose the persisted selection.
    restarted = create_app(settings=settings, mcp_profiles={"official-test": profile})
    with TestClient(restarted) as client:
        login = client.post(
            "/api/auth/login", json={"username": "mcp-alice", "password": "secret1"}
        )
        assert login.status_code == 200
        headers = _auth(str(login.json()["access_token"]))
        tools = client.get(
            f"/api/mcp/servers/{server_id}/tools",
            headers=headers,
            params={"project_id": "project-a"},
        )
        assert tools.status_code == 200
        by_name = {item["name"]: item for item in tools.json()}
        assert by_name["echo_evidence"]["enabled"] is True
        deleted = client.delete(
            f"/api/mcp/servers/{server_id}",
            headers=headers,
            params={"project_id": "project-a"},
        )
        assert deleted.status_code == 204


def test_mcp_routes_require_authentication_and_apply_rate_limits(tmp_path: Path) -> None:
    app = create_app(
        settings=_settings(tmp_path / "limited.db", rate_limit=1),
        mcp_profiles={"official-test": _profile(tmp_path)},
    )
    with TestClient(app) as client:
        assert client.get("/api/mcp/servers", params={"project_id": "p"}).status_code == 401
        token = _register(client, "mcp-rate")
        first = client.get("/api/mcp/servers", headers=_auth(token), params={"project_id": "p"})
        second = client.get("/api/mcp/servers", headers=_auth(token), params={"project_id": "p"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["detail"]["error"] == "rate_limit_exceeded"
