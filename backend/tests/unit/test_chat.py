"""Tests for chat API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> TestClient:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}",
    )
    app = create_app(settings=settings)
    with TestClient(app) as c:
        token = c.post(
            "/api/auth/register", json={"username": "chat-user", "password": "secret1"}
        ).json()["access_token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset LLM and tool singletons before each test."""
    from app.routes import chat

    chat._tools_singleton = None
    yield
    chat._tools_singleton = None


class TestChatEndpoint:
    """POST /api/chat tests."""

    @pytest.mark.unit
    def test_basic_chat(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "Hello, Archon!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert data["response"] == MockLLM.DEFAULT_RESPONSE
        assert "conversation_id" in data
        assert "correlation_id" in data
        assert data["iterations"] >= 1
        assert data["run_id"]

    @pytest.mark.unit
    def test_durable_skill_selection_is_visible_in_run_provenance(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "Review this Python code for security and correctness."},
        )
        assert response.status_code == 200
        body = response.json()
        assert any(item["name"] == "archon.code-review" for item in body["skills_used"])
        assert len(body["skills_used"]) <= 3

        provenance = client.get(f"/api/runs/{body['run_id']}/effective-context")
        assert provenance.status_code == 200
        context = provenance.json()
        assert context["skill_revisions"]
        assert all(item["revision"] and item["content_hash"] for item in context["skill_revisions"])
        assert context["context_cost"]["byte_count"] > 0

    @pytest.mark.unit
    def test_chat_with_conversation_id(self, client: TestClient) -> None:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        response = client.post(
            "/api/chat",
            json={"message": "Hi", "conversation_id": conversation_id},
        )
        assert response.status_code == 200
        assert response.json()["conversation_id"] == conversation_id

    @pytest.mark.unit
    def test_empty_message_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": ""},
        )
        assert response.status_code == 422  # Validation error

    @pytest.mark.unit
    def test_missing_message_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={},
        )
        assert response.status_code == 422


class TestChatStreamEndpoint:
    """POST /api/chat/stream SSE tests."""

    @pytest.mark.unit
    def test_stream_returns_sse(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"message": "Stream test"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    @pytest.mark.unit
    def test_stream_has_thinking_event(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"message": "Stream test"},
        )
        text = response.text
        assert "event: thinking" in text

    @pytest.mark.unit
    def test_stream_has_done_event(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"message": "Stream test"},
        )
        text = response.text
        assert "event: done" in text

    @pytest.mark.unit
    def test_stream_has_token_events(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"message": "Stream test"},
        )
        text = response.text
        assert "event: token" in text

    @pytest.mark.unit
    def test_stream_uses_same_durable_skill_selection(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat/stream",
            json={"message": "Review this Python code for security and correctness."},
        )
        assert response.status_code == 200
        assert "event: skill" in response.text
        assert "archon.code-review" in response.text


class TestChatHistory:
    """GET /api/chat/history/{conversation_id} tests."""

    @pytest.mark.unit
    def test_empty_history(self, client: TestClient) -> None:
        response = client.get("/api/chat/history/nonexistent")
        assert response.status_code == 404

    @pytest.mark.unit
    def test_history_after_chat(self, client: TestClient) -> None:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        # Send a message first
        chat_response = client.post(
            "/api/chat",
            json={"message": "Remember this", "conversation_id": conversation_id},
        )
        assert chat_response.status_code == 200

        # Check history
        response = client.get(f"/api/chat/history/{conversation_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2  # user + assistant
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
