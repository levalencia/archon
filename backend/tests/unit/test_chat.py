"""Tests for chat API endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app


class SlowFirstMockLLM(MockLLM):
    def __init__(self) -> None:
        super().__init__()
        self._slept = False

    async def complete(self, *args, **kwargs):
        if not self._slept:
            self._slept = True
            await asyncio.sleep(2)
        return await super().complete(*args, **kwargs)


def _bind_code_review(client: TestClient) -> None:
    item = next(
        row for row in client.get("/api/skills/catalog").json() if row["name"] == "code-review"
    )
    response = client.put(
        f"/api/skills/projects/default/{item['id']}",
        json={
            "revision_id": item["revision_id"],
            "revision_owner_id": item["revision_owner_id"],
            "enabled": True,
            "pinned": True,
        },
    )
    assert response.status_code == 200


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
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


@pytest.fixture
def hybrid_client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'hybrid-chat.db'}",
        verifier_enabled=False,
        hybrid_orchestration_enabled=True,
        delegation_signing_key="test-delegation-key-that-is-long-enough",
    )
    app = create_app(settings=settings)
    with TestClient(app) as c:
        token = c.post(
            "/api/auth/register",
            json={"username": "hybrid-user", "password": "secret1"},
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
        assert data["requested_mode"] == "auto"
        assert data["resolved_mode"] == "single"
        assert data["stop_reason"] == "completed"
        assert data["orchestration_degraded"] is False
        assert data["execution_degraded"] is False
        assert data["agents_used"] == []

    @pytest.mark.unit
    def test_forced_team_uses_fixed_and_dynamic_children(self, hybrid_client: TestClient) -> None:
        response = hybrid_client.post(
            "/api/chat",
            json={
                "message": "Compare the architecture and verify the evidence",
                "execution_mode": "team",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["requested_mode"] == "team"
        assert data["resolved_mode"] == "team"
        assert data["stop_reason"] == "completed"
        assert data["execution_degraded"] is False
        assert [child["kind"] for child in data["agents_used"]] == ["fixed", "dynamic"]
        assert all(child["status"] == "completed" for child in data["agents_used"])
        children = hybrid_client.get(f"/api/runs/{data['run_id']}/children")
        assert children.status_code == 200
        assert len(children.json()["items"]) == 2
        assert all(item["parent_run_id"] == data["run_id"] for item in children.json()["items"])
        events = hybrid_client.get(f"/api/runs/{data['run_id']}/events")
        assert events.status_code == 200
        kinds = [item["kind"] for item in events.json()["items"]]
        assert kinds.count("orchestration_routed") == 1
        assert kinds.count("delegation_requested") == 2
        assert kinds.count("delegation_completed") == 2
        wrapped_provider = cast(Any, hybrid_client.app).state.model_provider
        provider = cast(MockLLM, getattr(wrapped_provider, "delegate", wrapped_provider))
        assert len(provider.call_history) == 3
        assert provider.call_history[-1]["tools"] == ()

    @pytest.mark.unit
    def test_team_timeout_cancels_the_child_run_and_degrades_parent(
        self, hybrid_client: TestClient
    ) -> None:
        app = cast(Any, hybrid_client.app)
        app.state.settings.hybrid_orchestration_total_deadline_seconds = 1.0
        app.state.settings.hybrid_orchestration_child_deadline_seconds = 1.0
        app.state.model_provider = SlowFirstMockLLM()

        response = hybrid_client.post(
            "/api/chat",
            json={"message": "Compare and verify this architecture", "execution_mode": "team"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["orchestration_degraded"] is True
        assert data["agents_used"][0]["status"] == "timed_out"
        children = hybrid_client.get(f"/api/runs/{data['run_id']}/children").json()["items"]
        assert children[0]["status"] == "cancelled"

    @pytest.mark.unit
    def test_durable_skill_selection_is_visible_in_run_provenance(self, client: TestClient) -> None:
        _bind_code_review(client)
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
        assert '"stop_reason": "completed"' in text
        assert '"execution_degraded": false' in text

    @pytest.mark.unit
    def test_team_stream_exposes_routing_and_child_status(self, hybrid_client: TestClient) -> None:
        response = hybrid_client.post(
            "/api/chat/stream",
            json={
                "message": "Research and compare the architecture",
                "execution_mode": "team",
            },
        )

        assert response.status_code == 200
        assert "event: orchestration" in response.text
        assert '"resolved_mode": "team"' in response.text
        assert response.text.count("event: agent_status") == 4
        assert '"children_used": 2' in response.text

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
        _bind_code_review(client)
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
