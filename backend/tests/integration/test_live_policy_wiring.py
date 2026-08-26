from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.agents.mock_llm import MockLLM
from app.config import Settings
from app.main import create_app
from app.routes.stream import _routed_event
from app.runtime import ModelResponse, ToolCall
from app.runtime.factory import RunContext
from app.security.approvals import AuthorizationRequest
from app.security.policy import RiskClass


@pytest.fixture(autouse=True)
def reset_chat_state(tmp_path, monkeypatch):
    from app.routes import chat

    chat._llm_singleton = None
    chat._tools_singleton = None
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/live.db")
    yield
    chat._llm_singleton = None
    chat._tools_singleton = None


@contextmanager
def client(username: str = "live-user") -> Iterator[TestClient]:
    with TestClient(create_app(Settings(llm_provider="mock", debug=True))) as api:
        token = api.post(
            "/api/auth/register",
            json={"username": username, "password": "valid-password-123"},
        ).json()["access_token"]
        api.headers.update({"Authorization": f"Bearer {token}"})
        yield api


def test_both_chat_routes_use_shared_runtime_factory(monkeypatch) -> None:
    from app.routes import chat, stream
    from app.runtime.factory import create_chat_runtime as real_factory

    calls: list[str] = []

    def spy(**kwargs):
        calls.append(kwargs["context"].conversation_id)
        return real_factory(**kwargs)

    monkeypatch.setattr(chat, "create_chat_runtime", spy)
    monkeypatch.setattr(stream, "create_chat_runtime", spy)
    chat._llm_singleton = MockLLM(["sync", "stream"])
    with client() as api:
        first = api.post("/api/chat", json={"message": "one"})
        second = api.post("/api/chat/stream", json={"message": "two"})
    assert first.status_code == second.status_code == 200
    assert len(calls) == 2
    assert calls[0] != calls[1]


def test_sync_dangerous_call_fails_closed_without_execution() -> None:
    from app.routes import chat

    chat._llm_singleton = MockLLM(
        [ModelResponse(tool_calls=(ToolCall("danger-1", "terminal", {"command": "printf bad"}),))]
    )
    with client() as api:
        response = api.post("/api/chat", json={"message": "run it"})
    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["status"] == "denied"
    assert call["result"]["reason_code"] == "approval_unavailable"


def test_sync_and_sse_safe_read_call_execute_under_policy() -> None:
    from app.routes import chat

    chat._llm_singleton = MockLLM(
        [
            ModelResponse(tool_calls=(ToolCall("safe-sync", "calculator", {"expression": "2+2"}),)),
            ModelResponse("sync answer 4"),
            ModelResponse(tool_calls=(ToolCall("safe-sse", "calculator", {"expression": "3+3"}),)),
            ModelResponse("stream answer 6"),
        ]
    )
    with client() as api:
        sync_response = api.post("/api/chat", json={"message": "two plus two"})
        sse_response = api.post("/api/chat/stream", json={"message": "three plus three"})
    assert sync_response.json()["tool_calls"][0]["status"] == "success"
    assert "event: policy_decided" in sse_response.text
    assert '"id": "safe-sse"' in sse_response.text
    assert "stream answer 6" in sse_response.text


def test_policy_sse_routing_preserves_ids_and_drops_raw_secrets() -> None:
    context = RunContext("owner", "conversation", "run", "correlation")
    payload = _routed_event(
        {
            "id": "call-1",
            "name": "terminal",
            "arguments_hash": "a" * 64,
            "action": "ask",
            "arguments": {"token": "raw-secret"},
            "output": "raw-secret",
        },
        context,
    )
    encoded = json.dumps(payload)
    assert payload["tool_call_id"] == "call-1"
    assert payload["run_id"] == "run"
    assert payload["conversation_id"] == "conversation"
    assert payload["arguments_hash"] == "a" * 64
    assert "raw-secret" not in encoded


def test_approval_endpoint_enforces_owner_and_consumes_decision_once() -> None:
    app = create_app(Settings(llm_provider="mock", debug=True))
    with TestClient(app) as api:
        alice = api.post(
            "/api/auth/register",
            json={"username": "approval-alice", "password": "valid-password-123"},
        ).json()
        bob = api.post(
            "/api/auth/register",
            json={"username": "approval-bob", "password": "valid-password-123"},
        ).json()
        owner_context = RunContext(alice["user_id"], "conversation", "run", "correlation")
        approval = AuthorizationRequest(
            "endpoint-call",
            "terminal",
            "b" * 64,
            frozenset({RiskClass.EXECUTE}),
            "side_effects_require_approval",
        )
        assert api.portal is not None
        outcome = api.portal.start_task_soon(
            app.state.approval_broker.authorizer(owner_context).authorize, approval
        )
        for _ in range(20):
            if api.portal.call(app.state.approval_broker.pending_count) == 1:
                break

        bob_response = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
            json={"approved": True},
        )
        assert bob_response.status_code == 404

        alice_response = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={"approved": True},
        )
        assert alice_response.status_code == 200
        assert outcome.result(timeout=1).approved is True
        repeated = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={"approved": False},
        )
        assert repeated.status_code == 404
