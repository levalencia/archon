"""Tests for chat API endpoints."""

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


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset LLM and tool singletons before each test."""
    from app.routes import chat

    chat._llm_singleton = None
    chat._tools_singleton = None
    yield
    chat._llm_singleton = None
    chat._tools_singleton = None


class TestChatEndpoint:
    """POST /api/chat tests."""

    @pytest.mark.unit
    @pytest.mark.skip(reason="needs mock LLM")
    def test_basic_chat(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "Hello, Archon!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "conversation_id" in data
        assert "correlation_id" in data
        assert data["iterations"] >= 1

    @pytest.mark.unit
    @pytest.mark.skip(reason="needs mock LLM")
    def test_chat_with_conversation_id(self, client: TestClient) -> None:
        response = client.post(
            "/api/chat",
            json={"message": "Hi", "conversation_id": "conv-123"},
        )
        assert response.status_code == 200
        assert response.json()["conversation_id"] == "conv-123"

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


@pytest.mark.skip(reason="Stream endpoint moved to stream.py")
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


class TestChatHistory:
    """GET /api/chat/history/{conversation_id} tests."""

    @pytest.mark.unit
    def test_empty_history(self, client: TestClient) -> None:
        response = client.get("/api/chat/history/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["messages"] == []
        assert data["count"] == 0

    @pytest.mark.unit
    @pytest.mark.skip(reason="needs mock LLM")
    def test_history_after_chat(self, client: TestClient) -> None:
        # Send a message first
        client.post(
            "/api/chat",
            json={"message": "Remember this", "conversation_id": "conv-hist"},
        )

        # Check history
        response = client.get("/api/chat/history/conv-hist")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2  # user + assistant
        assert data["messages"][0]["role"] == "user"
        assert data["messages"][1]["role"] == "assistant"
