"""Safe public inventory contract for deployment-owned MCP profiles."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mcp.models import ServerProfile


def test_profiles_are_authenticated_and_never_expose_process_configuration(tmp_path: Path) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'profiles.db'}",
        memory_encryption_enabled=False,
        rate_limit_requests=100,
    )
    secret_command = "/private/deployment/mcp-server"
    profile = ServerProfile(
        command=secret_command,
        args=("--token-file", "/private/token"),
        env={"LANG": "en_US.UTF-8"},
    )
    app = create_app(settings=settings, mcp_profiles={"official-docs": profile})

    with TestClient(app) as client:
        assert client.get("/api/mcp/profiles").status_code == 401
        registered = client.post(
            "/api/auth/register", json={"username": "profile-user", "password": "secret1"}
        )
        token = registered.json()["access_token"]
        response = client.get(
            "/api/mcp/profiles", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json() == [{"id": "official-docs", "display_name": "Official Docs"}]
    serialized = response.text
    assert secret_command not in serialized
    assert "command" not in serialized
    assert "args" not in serialized
    assert "env" not in serialized
