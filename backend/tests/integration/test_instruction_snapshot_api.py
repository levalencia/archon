from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _register(client: TestClient, username: str) -> tuple[dict[str, str], str]:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def test_scan_api_persists_exact_sources_and_requires_admin_approval(tmp_path: Path) -> None:
    database = tmp_path / "api.db"
    workspaces = tmp_path / "workspaces"
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{database}",
        memory_encryption_enabled=False,
        rate_limit_requests=1000,
        admin_usernames=["admin"],
        project_workspace_root=str(workspaces),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        admin, admin_id = _register(client, "admin")
        other, _ = _register(client, "other")
        project = workspaces / admin_id / "project"
        (project / ".archon").mkdir(parents=True)
        (project / "nested" / ".archon").mkdir(parents=True)
        (project / ".archon" / "instructions.md").write_text("root")
        (project / "nested" / ".archon" / "instructions.md").write_text("leaf")

        response = client.post(
            "/api/projects/project/instructions/scan",
            json={"target_path": "nested", "family": "archon"},
            headers=admin,
        )
        assert response.status_code == 200, response.text
        scanned = response.json()
        assert [item["relative_path"] for item in scanned] == [
            ".archon/instructions.md",
            "nested/.archon/instructions.md",
        ]
        assert all(len(item["content_hash"]) == 64 for item in scanned)
        revision_id = scanned[0]["id"]
        assert (
            client.post(
                f"/api/projects/project/instructions/{revision_id}/approve", headers=other
            ).status_code
            == 403
        )
        assert (
            client.get("/api/projects/project/instructions/revisions", headers=other).json() == []
        )
        assert (
            client.post(
                f"/api/projects/project/instructions/{revision_id}/approve", headers=admin
            ).status_code
            == 200
        )

    with TestClient(create_app(settings)) as client:
        login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        resolved = client.get("/api/projects/project/instructions/resolve", headers=headers)
        assert resolved.status_code == 200
        assert [item["relative_path"] for item in resolved.json()["items"]] == [
            ".archon/instructions.md",
            "nested/.archon/instructions.md",
        ]
        assert "root" not in resolved.text and "leaf" not in resolved.text
