"""Live per-user/per-peer rate limiting and protected task/MCP route tests."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(tmp_path, **overrides: Any) -> Settings:
    return Settings(
        llm_provider="mock",
        debug=True,
        memory_encryption_enabled=False,
        database_url=f"sqlite+aiosqlite:///{tmp_path / f'{uuid.uuid4().hex}.db'}",
        rate_limit_requests=20,
        rate_limit_window=60,
        **overrides,
    )


def _set_peer(client: TestClient, host: str) -> None:
    client._transport.client = (host, 50000)  # type: ignore[attr-defined]


def _register(client: TestClient, username: str) -> str:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return str(response.json()["access_token"])


@pytest.mark.integration
def test_chat_enforces_user_cap_across_different_ips(tmp_path) -> None:
    app = create_app(_settings(tmp_path, rate_limit_chat_requests=1))
    with TestClient(app, client=("192.0.2.10", 50000)) as client:
        token = _register(client, "same-user")
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/api/chat", json={"message": "one"}, headers=headers).status_code == 200

        _set_peer(client, "192.0.2.11")
        limited = client.post("/api/chat", json={"message": "two"}, headers=headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"


@pytest.mark.integration
def test_chat_enforces_ip_cap_across_different_users_and_ignores_xff(tmp_path) -> None:
    app = create_app(_settings(tmp_path, rate_limit_chat_requests=1))
    with TestClient(app, client=("198.51.100.20", 50000)) as client:
        first = _register(client, "first-user")
        second = _register(client, "second-user")
        first_headers = {
            "Authorization": f"Bearer {first}",
            "X-Forwarded-For": "203.0.113.1",
        }
        second_headers = {
            "Authorization": f"Bearer {second}",
            "X-Forwarded-For": "203.0.113.2",
        }
        assert (
            client.post("/api/chat", json={"message": "one"}, headers=first_headers).status_code
            == 200
        )
        limited = client.post("/api/chat", json={"message": "two"}, headers=second_headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"

        # The second user's quota was consumed before the shared-IP rejection.
        _set_peer(client, "198.51.100.21")
        assert (
            client.post("/api/chat", json={"message": "three"}, headers=second_headers).status_code
            == 429
        )


@pytest.mark.integration
def test_login_and_register_use_indistinguishable_ip_action_limits(tmp_path) -> None:
    app = create_app(_settings(tmp_path, rate_limit_auth_requests=1))
    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        token = _register(client, "auth-user")
        register_limited = client.post(
            "/api/auth/register",
            json={"username": "another-user", "password": "secret1"},
            headers={"X-Forwarded-For": "198.51.100.99"},
        )
        assert register_limited.status_code == 429

        first_login = client.post(
            "/api/auth/login", json={"username": "missing", "password": "wrong-pass"}
        )
        assert first_login.status_code == 200
        login_limited = client.post(
            "/api/auth/login", json={"username": "auth-user", "password": "secret1"}
        )
        assert login_limited.status_code == 429
        assert login_limited.json() == register_limited.json()
        assert login_limited.headers["Retry-After"] == "60"
        assert token


@pytest.mark.integration
def test_task_and_mcp_require_auth_and_are_limited_per_action(tmp_path) -> None:
    app = create_app(_settings(tmp_path, rate_limit_task_requests=1, rate_limit_mcp_requests=1))
    with TestClient(app, client=("192.0.2.30", 50000)) as client:
        assert client.get("/api/tasks").status_code == 401
        assert client.post("/api/tasks/submit", json={"description": "x"}).status_code == 401
        assert client.get("/api/mcp/tools").status_code == 401
        assert (
            client.post(
                "/api/mcp/request",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            ).status_code
            == 401
        )

        token = _register(client, "route-user")
        client.headers.update({"Authorization": f"Bearer {token}"})

        submitted = client.post("/api/tasks/submit", json={"description": "allowed"})
        assert submitted.status_code == 200
        task_limited = client.post("/api/tasks/submit", json={"description": "blocked"})
        assert task_limited.status_code == 429
        assert "Retry-After" in task_limited.headers
        assert client.get("/api/tasks").status_code == 200

        assert client.get("/api/mcp/tools").status_code == 200
        mcp_limited = client.get("/api/mcp/tools")
        assert mcp_limited.status_code == 429
        assert "Retry-After" in mcp_limited.headers
        assert (
            client.post(
                "/api/mcp/request",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            ).status_code
            == 200
        )

        # Health probes are deliberately outside all rate-limit buckets.
        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200
