"""End-to-end authentication and conversation ownership boundaries."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'ownership.db'}",
        secret_key="ownership-test-secret",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.security
def test_conversation_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/conversations").status_code == 401
    assert client.post("/api/conversations", json={}).status_code == 401
    assert client.get("/api/conversations/unknown").status_code == 401
    assert client.delete("/api/conversations/unknown").status_code == 401
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 401
    assert client.post("/api/chat/stream", json={"message": "hello"}).status_code == 401
    assert client.get("/api/chat/history/unknown").status_code == 401


@pytest.mark.security
def test_cross_user_conversation_ids_are_indistinguishable_from_missing(client: TestClient) -> None:
    alice = register(client, "alice")
    bob = register(client, "bob")
    created = client.post("/api/conversations", headers=alice, json={"title": "Alice only"})
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    assert client.get("/api/conversations", headers=bob).json() == []
    assert client.get(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404
    assert client.get(f"/api/chat/history/{conversation_id}", headers=bob).status_code == 404
    assert (
        client.post(
            "/api/chat",
            headers=bob,
            json={"message": "steal", "conversation_id": conversation_id},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/chat/stream",
            headers=bob,
            json={"message": "steal", "conversation_id": conversation_id},
        ).status_code
        == 404
    )
    assert client.delete(f"/api/conversations/{conversation_id}", headers=bob).status_code == 404
    assert client.get(f"/api/conversations/{conversation_id}", headers=alice).status_code == 200


@pytest.mark.security
def test_authenticated_chat_persists_only_for_owner(client: TestClient) -> None:
    owner = register(client, "owner")
    other = register(client, "other")
    response = client.post("/api/chat", headers=owner, json={"message": "private message"})
    assert response.status_code == 200
    conversation_id = response.json()["conversation_id"]

    history = client.get(f"/api/chat/history/{conversation_id}", headers=owner)
    assert history.status_code == 200
    assert [item["role"] for item in history.json()["messages"]] == ["user", "assistant"]
    assert client.get(f"/api/chat/history/{conversation_id}", headers=other).status_code == 404
