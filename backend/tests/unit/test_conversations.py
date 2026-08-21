"""Tests for conversation CRUD endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(llm_provider="mock", debug=True)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


class TestConversationCRUD:
    """Conversation management tests."""

    @pytest.mark.unit
    def test_create_conversation(self, client: TestClient) -> None:
        response = client.post(
            "/api/conversations",
            json={"title": "Test Chat"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Chat"
        assert len(data["id"]) == 36  # UUID
        assert data["message_count"] == 0

    @pytest.mark.unit
    def test_create_default_title(self, client: TestClient) -> None:
        response = client.post("/api/conversations", json={})
        assert response.status_code == 201
        assert response.json()["title"] == "New Conversation"

    @pytest.mark.unit
    def test_list_conversations(self, client: TestClient) -> None:
        r1 = client.post("/api/conversations", json={"title": "Chat 1"})
        r2 = client.post("/api/conversations", json={"title": "Chat 2"})
        id1 = r1.json()["id"]
        id2 = r2.json()["id"]

        response = client.get("/api/conversations")
        assert response.status_code == 200
        data = response.json()
        ids = [c["id"] for c in data]
        assert id1 in ids
        assert id2 in ids

    @pytest.mark.unit
    def test_get_conversation_detail(self, client: TestClient) -> None:
        create_resp = client.post("/api/conversations", json={"title": "Detail Test"})
        conv_id = create_resp.json()["id"]

        response = client.get(f"/api/conversations/{conv_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == conv_id
        assert data["title"] == "Detail Test"
        assert data["messages"] == []

    @pytest.mark.unit
    def test_delete_conversation(self, client: TestClient) -> None:
        create_resp = client.post("/api/conversations", json={"title": "To Delete"})
        conv_id = create_resp.json()["id"]

        response = client.delete(f"/api/conversations/{conv_id}")
        assert response.status_code == 204

    @pytest.mark.unit
    def test_get_nonexistent_conversation(self, client: TestClient) -> None:
        response = client.get("/api/conversations/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["message_count"] == 0
