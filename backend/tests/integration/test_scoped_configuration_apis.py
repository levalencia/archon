from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mcp.config import MCPProfileConfigError


def _settings(path: Path, **values: object) -> Settings:
    return Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{path}",
        memory_encryption_enabled=False,
        rate_limit_requests=1000,
        **values,
    )


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "StrongPass123!"}
    )
    assert response.status_code in {200, 201}
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_instruction_and_capability_apis_are_scoped_and_restart_safe(tmp_path: Path) -> None:
    database = tmp_path / "scoped.db"
    settings = _settings(database, admin_usernames=["admin"])
    app = create_app(settings)
    with TestClient(app) as client:
        admin = _register(client, "admin")
        other = _register(client, "other")
        created = client.post(
            "/api/projects/shared/instructions",
            json={"content": "Only reviewed operations."},
            headers=admin,
        )
        assert created.status_code == 201
        item = created.json()
        assert set(item) == {
            "id",
            "relative_path",
            "scope_path",
            "revision",
            "content_hash",
            "trust_state",
            "byte_count",
            "content",
        }
        approved = client.post(
            f"/api/projects/shared/instructions/{item['id']}/approve", headers=admin
        )
        assert approved.status_code == 200
        assert approved.json()["trust_state"] == "approved"
        chat = client.post(
            "/api/chat",
            json={"message": "Review this project.", "project_id": "shared"},
            headers=admin,
        )
        assert chat.status_code == 200
        effective_context = client.get(
            f"/api/runs/{chat.json()['run_id']}/effective-context", headers=admin
        )
        assert effective_context.status_code == 200
        instruction_ref = effective_context.json()["instruction_revisions"][0]
        assert instruction_ref["source_path"] == ".archon/instructions.md"
        assert instruction_ref["scope_path"] == "."
        assert instruction_ref["order"] == 0
        assert instruction_ref["content_hash"] == approved.json()["content_hash"]
        assert client.get("/api/projects/shared/instructions/revisions", headers=other).json() == []

        found = client.post(
            "/api/capabilities/search", json={"query": "code-review"}, headers=admin
        )
        assert found.status_code == 200
        capability = found.json()[0]
        assert set(capability) == {
            "id",
            "name",
            "description",
            "kind",
            "source",
            "version",
            "trust_state",
            "enabled",
            "pinned",
            "risk_classes",
        }
        pinned = client.put(
            f"/api/capabilities/projects/shared/{capability['id']}",
            json={"enabled": True, "pinned": True},
            headers=admin,
        )
        assert pinned.status_code == 200

    restarted = create_app(settings)
    with TestClient(restarted) as client:
        login = client.post(
            "/api/auth/login", json={"username": "admin", "password": "StrongPass123!"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        resolved = client.get("/api/projects/shared/instructions/resolve", headers=headers)
        assert resolved.status_code == 200
        assert resolved.json()["items"][0]["content_hash"] == item["content_hash"]
        effective = client.post(
            "/api/capabilities/projects/shared/effective",
            json={"intent": "unrelated", "context_budget": 100000},
            headers=headers,
        )
        assert effective.status_code == 200
        assert effective.json()["summary"]["pinned"] == 1


def test_bundled_skill_catalog_binding_is_revision_pinned_and_restart_safe(
    tmp_path: Path,
) -> None:
    database = tmp_path / "skills-catalog.db"
    settings = _settings(database, admin_usernames=["admin"])
    app = create_app(settings)
    with TestClient(app) as client:
        admin = _register(client, "admin")
        catalog_response = client.get("/api/skills/catalog?project_id=project-a", headers=admin)
        assert catalog_response.status_code == 200
        catalog = catalog_response.json()
        assert len(catalog) >= 10
        review = next(item for item in catalog if item["name"] == "code-review")
        assert review["revision_id"]
        assert review["revision_owner_id"] == "archon"

        bound = client.put(
            f"/api/skills/projects/project-a/{review['id']}",
            json={
                "revision_id": review["revision_id"],
                "revision_owner_id": review["revision_owner_id"],
                "enabled": True,
                "pinned": True,
            },
            headers=admin,
        )
        assert bound.status_code == 200
        assert bound.json()["enabled"] is True
        assert bound.json()["revision_id"] == review["revision_id"]

    restarted = create_app(settings)
    with TestClient(restarted) as client:
        login = client.post(
            "/api/auth/login", json={"username": "admin", "password": "StrongPass123!"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        effective = client.get("/api/skills/projects/project-a/effective", headers=headers)
        assert effective.status_code == 200
        assert [item["name"] for item in effective.json()["items"]] == ["code-review"]


def test_mcp_profiles_bootstrap_strictly_and_hide_configuration(tmp_path: Path) -> None:
    raw = json.dumps(
        {
            "disabled": {"transport": "stdio", "command": "/secret/off"},
            "remote": {
                "transport": "streamable_http",
                "enabled": True,
                "url": "https://mcp.example.test/service",
                "credential_ref": "vault:prod",
            },
        }
    )
    app = create_app(_settings(tmp_path / "mcp.db", mcp_profiles_json=raw))
    with TestClient(app) as client:
        headers = _register(client, "mcp-user")
        response = client.get("/api/mcp/profiles", headers=headers)
        assert response.json() == [{"id": "remote", "display_name": "Remote"}]
        assert "mcp.example" not in response.text
        assert "vault" not in response.text
    with pytest.raises(MCPProfileConfigError):
        create_app(
            _settings(
                tmp_path / "bad.db",
                mcp_profiles_json='{"x":{"enabled":true,"command":"x","secret":"bad"}}',
            )
        )
