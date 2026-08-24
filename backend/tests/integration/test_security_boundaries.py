"""Live application security-boundary integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.security.auth import configure_auth, create_jwt


@pytest.fixture
def client() -> TestClient:
    app = create_app(
        Settings(
            llm_provider="mock",
            debug=True,
            secret_key="test-secret",
            admin_usernames=["admin"],
        )
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.integration
def test_health_remains_public_and_has_security_headers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "connect-src 'self' http://localhost:* ws://localhost:*" in csp
    assert "img-src 'self' data: blob: https:" in csp
    assert "frame-ancestors 'self'" in csp
    assert "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com" in csp


@pytest.mark.integration
def test_csrf_double_submit_for_cookie_authenticated_mutation(client: TestClient) -> None:
    client.cookies.set("access_token", "browser-session")
    missing = client.put("/api/admin/settings", json={"skills_top_k": 4})
    assert missing.status_code == 403
    assert missing.json()["detail"] == "CSRF token missing or invalid"

    client.get("/healthz")
    csrf_token = client.cookies["csrf_token"]
    mismatched = client.put(
        "/api/admin/settings", json={"skills_top_k": 4}, headers={"X-CSRF-Token": "wrong"}
    )
    assert mismatched.status_code == 403

    valid = client.put(
        "/api/admin/settings",
        json={"skills_top_k": 4},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert valid.status_code == 401


@pytest.mark.integration
def test_bearer_auth_is_csrf_exempt_and_admin_claim_is_enforced(client: TestClient) -> None:
    client.cookies.set("access_token", "ambient-cookie")
    admin_token = create_jwt("admin-id", "operator", is_admin=True)
    response = client.put(
        "/api/admin/settings",
        json={"skills_top_k": 4},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200

    user_token = create_jwt("user-id", "user")
    forbidden = client.put(
        "/api/admin/settings",
        json={"skills_top_k": 5},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert forbidden.status_code == 403


@pytest.mark.integration
def test_api_key_auth_is_csrf_exempt(client: TestClient) -> None:
    configure_auth(
        "test-secret",
        {"test-admin-key": {"user_id": "api-admin", "name": "admin"}},
    )
    client.cookies.set("access_token", "ambient-cookie")
    response = client.put(
        "/api/admin/settings",
        json={"skills_top_k": 4},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert response.status_code == 200


@pytest.mark.integration
def test_sensitive_routes_reject_unauthenticated_requests(client: TestClient) -> None:
    assert client.get("/api/logs/recent").status_code == 401
    assert client.get("/api/logs/stream").status_code == 401
    assert client.put("/api/admin/settings", json={"skills_top_k": 4}).status_code == 401
    assert client.post("/api/admin/circuit-breakers/test/reset").status_code == 401
