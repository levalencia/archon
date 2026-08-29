"""Tests for conversation CRUD endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository


@pytest.fixture
def client() -> TestClient:
    settings = Settings(llm_provider="mock", debug=True)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        token = c.post(
            "/api/auth/register", json={"username": "conversation-user", "password": "secret1"}
        ).json()["access_token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture(autouse=True)
async def isolated_database(tmp_path, monkeypatch):
    """Use an isolated persistent database for each test."""
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'conversations.db'}"
    monkeypatch.setenv("ARCHON_DATABASE_URL", database_url)
    yield database_url


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
        assert response.status_code == 404

    @pytest.mark.unit
    def test_conversation_message_history_list_delete_flow(self, client: TestClient) -> None:
        created = client.post("/api/conversations", json={"title": "Persistent Chat"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        message = client.post(
            "/api/chat",
            json={"message": "Remember this", "conversation_id": conversation_id},
        )
        assert message.status_code == 200

        history = client.get(f"/api/chat/history/{conversation_id}")
        assert history.status_code == 200
        assert history.json()["messages"] == [
            {"role": "user", "content": "Remember this"},
            {"role": "assistant", "content": MockLLM.DEFAULT_RESPONSE},
        ]

        conversations = client.get("/api/conversations")
        assert conversations.status_code == 200
        persisted = next(item for item in conversations.json() if item["id"] == conversation_id)
        assert persisted["title"] == "Persistent Chat"
        assert persisted["message_count"] == 2

        detail = client.get(f"/api/conversations/{conversation_id}")
        assert detail.json()["messages"] == history.json()["messages"]
        assert detail.json()["message_count"] == 2

        assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
        assert all(
            item["id"] != conversation_id for item in client.get("/api/conversations").json()
        )
        assert client.get(f"/api/chat/history/{conversation_id}").status_code == 404

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_data_survives_fresh_database_store(self, isolated_database: str) -> None:
        first = ConversationRepository(isolated_database, PersistenceRedactor())
        await first.initialize()
        await first.create("persistent-id", "Survives Restart")
        await first.store("persistent-id", "user", "still here")
        await first.close()

        fresh = ConversationRepository(isolated_database, PersistenceRedactor())
        await fresh.initialize()
        try:
            conversation = await fresh.get("persistent-id")
            assert conversation is not None
            assert conversation["title"] == "Survives Restart"
            assert conversation["message_count"] == 1
            assert await fresh.retrieve("persistent-id") == [
                {"role": "user", "content": "still here"}
            ]
        finally:
            await fresh.close()
