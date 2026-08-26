"""Integration coverage for the unified persistent conversation repository."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository


@pytest.mark.integration
def test_conversation_lifecycle_and_restart_persistence(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/conversations.db"
    settings = Settings(llm_provider="mock", debug=True, database_url=database_url)
    provider = MockLLM(["persisted answer"])
    app = create_app(settings, model_provider_factory=lambda _settings: provider)
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register", json={"username": "persistent-chat", "password": "secret1"}
        )
        client.headers.update({"Authorization": f"Bearer {registered.json()['access_token']}"})
        created = client.post("/api/conversations", json={"title": "Persistent chat"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        listed = client.get("/api/conversations").json()
        assert listed == [created.json()]

        response = client.post(
            "/api/chat",
            json={"message": "Remember this", "conversation_id": conversation_id},
        )
        assert response.status_code == 200
        expected_messages = [
            {"role": "user", "content": "Remember this"},
            {"role": "assistant", "content": "persisted answer"},
        ]
        assert client.get(f"/api/chat/history/{conversation_id}").json() == {
            "conversation_id": conversation_id,
            "messages": expected_messages,
            "count": 2,
        }
        detail = client.get(f"/api/conversations/{conversation_id}").json()
        assert detail["title"] == "Persistent chat"
        assert detail["messages"] == expected_messages
        assert detail["message_count"] == 2
        assert client.get("/api/conversations").json()[0]["message_count"] == 2

    with TestClient(create_app(settings)) as restarted_client:
        logged_in = restarted_client.post(
            "/api/auth/login", json={"username": "persistent-chat", "password": "secret1"}
        )
        restarted_client.headers.update(
            {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
        )
        detail = restarted_client.get(f"/api/conversations/{conversation_id}").json()
        assert detail["title"] == "Persistent chat"
        assert detail["messages"] == expected_messages
        assert restarted_client.delete(f"/api/conversations/{conversation_id}").status_code == 204
        assert restarted_client.get("/api/conversations").json() == []
        assert restarted_client.get(f"/api/chat/history/{conversation_id}").status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_repository_data_survives_reinstantiation(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/repository.db"
    first = ConversationRepository(database_url, PersistenceRedactor())
    await first.initialize()
    await first.create("conversation-1", "Repository test")
    await first.store("conversation-1", "user", "durable message")
    await first.close()

    second = ConversationRepository(database_url, PersistenceRedactor())
    await second.initialize()
    persisted = await second.get("conversation-1")
    assert persisted is not None
    assert persisted["id"] == "conversation-1"
    assert persisted["title"] == "Repository test"
    assert persisted["messages"] == [{"role": "user", "content": "durable message"}]
    assert persisted["message_count"] == 1
    await second.close()
