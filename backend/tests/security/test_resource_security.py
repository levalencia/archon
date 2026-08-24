"""Authorization, ownership, and inert artifact rendering tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.artifacts import get_artifact_store
from app.services.artifacts import Artifact


def headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(llm_provider="mock", debug=True))
    with TestClient(app) as api:
        yield api


@pytest.mark.security
def test_sensitive_route_auth_and_roles(client: TestClient) -> None:
    for path in ("/api/documents", "/api/artifacts", "/api/images/missing.png", "/api/skills"):
        assert client.get(path).status_code == 401

    user = headers(client, "user")
    assert client.get("/api/skills", headers=user).status_code == 200
    assert (
        client.post(
            "/api/skills",
            headers=user,
            json={"name": "x", "description": "x", "content": "x"},
        ).status_code
        == 403
    )
    assert client.get("/api/admin/health", headers=user).status_code == 403
    assert client.post("/api/security/red-team", headers=user).status_code == 403
    assert (
        client.post("/api/security/pii-scan", headers=user, json={"text": "safe"}).status_code
        == 403
    )
    assert client.get("/api/admin/health", headers=headers(client, "admin")).status_code == 200


@pytest.mark.security
def test_documents_are_owner_scoped(client: TestClient) -> None:
    owner = headers(client, "owner")
    other = headers(client, "other")
    created = client.post(
        "/api/documents/upload",
        headers=owner,
        json={"title": "private", "content": "private document content", "source": "test"},
    )
    assert created.status_code == 201
    document_id = created.json()["id"]
    other_documents = client.get("/api/documents", headers=other).json()
    assert document_id not in {item["id"] for item in other_documents}
    assert (
        client.post(
            "/api/documents/query",
            headers=other,
            json={"question": "private?", "document_id": document_id},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/documents/{document_id}", headers=other).status_code == 404
    assert client.delete(f"/api/documents/{document_id}", headers=owner).status_code == 204


@pytest.mark.security
def test_artifacts_are_owner_scoped_and_render_inert(client: TestClient) -> None:
    store = get_artifact_store()
    artifact = Artifact(
        id="dangerous-artifact",
        user_id="owner",
        title="<img src=x onerror=alert(1)>",
        artifact_type="html",
        content=(
            '<script>alert(1)</script><img src=x onerror="alert(2)">'
            '<a href="javascript:alert(3)">click</a>'
        ),
    )
    store._artifacts[artifact.id] = artifact

    other = headers(client, "other-artifact-user")
    for suffix in ("", "/render"):
        assert client.get(f"/api/artifacts/{artifact.id}{suffix}", headers=other).status_code == 404
    assert (
        client.put(
            f"/api/artifacts/{artifact.id}", headers=other, json={"content": "stolen"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/artifacts/{artifact.id}", headers=other).status_code == 404

    owner = headers(client, "owner")
    artifact.user_id = client.get("/api/auth/me", headers=owner).json()["user_id"]
    response = client.get(f"/api/artifacts/{artifact.id}/render", headers=owner)
    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("sandbox; default-src 'none'")
    assert "<script>" not in response.text
    assert "<img " not in response.text
    assert '<a href="javascript:' not in response.text
    assert "&lt;script&gt;" in response.text
    assert "onerror=&quot;" in response.text
    assert "javascript:alert(3)&quot;" in response.text
