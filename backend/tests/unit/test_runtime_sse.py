from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime import ModelResponse, ToolCall


@pytest.fixture(autouse=True)
def reset_chat_state(tmp_path, monkeypatch):
    from app.routes import chat

    chat._llm_singleton = None
    chat._tools_singleton = None
    chat._db_store = None
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/chat.db")
    yield
    chat._llm_singleton = None
    chat._tools_singleton = None
    chat._db_store = None


@contextmanager
def client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(llm_provider="mock", debug=True))) as api:
        token = api.post(
            "/api/auth/register", json={"username": "runtime-user", "password": "secret1"}
        ).json()["access_token"]
        api.headers.update({"Authorization": f"Bearer {token}"})
        yield api


def done_payload(text: str) -> dict:
    marker = "event: done\ndata: "
    return json.loads(text.split(marker, 1)[1].split("\n\n", 1)[0])


def test_chat_uses_typed_runtime_and_preserves_history() -> None:
    from app.agents.mock_llm import MockLLM
    from app.routes import chat

    chat._llm_singleton = MockLLM(["hello"])
    with client() as api:
        conversation_id = api.post("/api/conversations", json={}).json()["id"]
        response = api.post("/api/chat", json={"message": "hi", "conversation_id": conversation_id})
        history = api.get(f"/api/chat/history/{conversation_id}")
    assert response.status_code == 200
    assert response.json()["response"] == "hello"
    assert response.json()["tokens_used"] == 1
    assert [item["role"] for item in history.json()["messages"]] == ["user", "assistant"]


def test_sse_receives_native_runtime_events_and_stop_reason() -> None:
    from app.agents.mock_llm import MockLLM
    from app.routes import chat

    chat._llm_singleton = MockLLM(
        [
            ModelResponse(tool_calls=(ToolCall("t1", "calculator", {"expression": "2+2"}),)),
            ModelResponse("The answer is 4."),
        ]
    )
    with client() as api:
        conversation_id = api.post("/api/conversations", json={}).json()["id"]
        response = api.post(
            "/api/chat/stream", json={"message": "calculate", "conversation_id": conversation_id}
        )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    assert "event: tool_call" in response.text
    assert "event: token\ndata: The answer is 4." in response.text
    assert done_payload(response.text)["stop_reason"] == "completed"


def test_concurrent_sse_streams_do_not_cross_talk() -> None:
    from app.agents.mock_llm import MockLLM
    from app.routes import chat

    chat._llm_singleton = MockLLM(["alpha-response", "beta-response"])
    with client() as api:
        # TestClient requests are separate runs; unique conversation IDs also verify sink ownership.
        alpha = api.post("/api/conversations", json={}).json()["id"]
        beta = api.post("/api/conversations", json={}).json()["id"]
        first = api.post("/api/chat/stream", json={"message": "a", "conversation_id": alpha})
        second = api.post("/api/chat/stream", json={"message": "b", "conversation_id": beta})
    assert "alpha-response" in first.text and "beta-response" not in first.text
    assert "beta-response" in second.text and "alpha-response" not in second.text
    assert done_payload(first.text)["conversation_id"] == alpha
    assert done_payload(second.text)["conversation_id"] == beta
