from __future__ import annotations

import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
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
from app.tools.registry import SecureToolRegistry


@pytest.fixture(autouse=True)
def reset_chat_state(tmp_path, monkeypatch):
    from app.routes import chat

    chat._tools_singleton = None
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/live.db")
    yield
    chat._tools_singleton = None


@contextmanager
def client(username: str = "live-user", provider=None) -> Iterator[TestClient]:
    settings = Settings(llm_provider="mock", debug=True)
    app = (
        create_app(settings)
        if provider is None
        else create_app(settings, model_provider_factory=lambda _settings: provider)
    )
    with TestClient(app) as api:
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
    provider = MockLLM(["sync", "stream"])
    with client(provider=provider) as api:
        first = api.post("/api/chat", json={"message": "one"})
        second = api.post("/api/chat/stream", json={"message": "two"})
    assert first.status_code == second.status_code == 200
    assert len(calls) == 2
    assert calls[0] != calls[1]


def test_sync_dangerous_call_fails_closed_without_execution() -> None:
    provider = MockLLM(
        [ModelResponse(tool_calls=(ToolCall("danger-1", "terminal", {"command": "printf bad"}),))]
    )
    with client(provider=provider) as api:
        response = api.post("/api/chat", json={"message": "run it"})
    assert response.status_code == 200
    call = response.json()["tool_calls"][0]
    assert call["status"] == "denied"
    assert call["result"]["reason_code"] == "approval_unavailable"


def test_sync_and_sse_safe_read_call_execute_under_policy() -> None:
    provider = MockLLM(
        [
            ModelResponse(tool_calls=(ToolCall("safe-sync", "calculator", {"expression": "2+2"}),)),
            ModelResponse("sync answer 4"),
            ModelResponse(tool_calls=(ToolCall("safe-sse", "calculator", {"expression": "3+3"}),)),
            ModelResponse("stream answer 6"),
        ]
    )
    with client(provider=provider) as api:
        sync_response = api.post("/api/chat", json={"message": "two plus two"})
        sse_response = api.post("/api/chat/stream", json={"message": "three plus three"})
    assert sync_response.json()["tool_calls"][0]["status"] == "success"
    assert "event: policy_decided" in sse_response.text
    assert '"id": "safe-sse"' in sse_response.text
    assert "stream answer 6" in sse_response.text


@pytest.mark.parametrize("approved", [True, False], ids=["approve", "deny"])
def test_live_sse_approval_decision_controls_dangerous_execution(
    approved: bool, monkeypatch
) -> None:
    from app.routes import chat

    monkeypatch.setattr(
        RunContext,
        "create",
        classmethod(
            lambda cls, *, user_id, conversation_id, correlation_id: cls(
                user_id,
                conversation_id,
                "00000000-0000-4000-8000-000000000001",
                correlation_id,
            )
        ),
    )

    executions: list[str] = []

    async def dangerous_tool(command: str) -> dict:
        executions.append(command)
        return {"ok": True, "secret": "must-not-reach-sse"}

    tools = SecureToolRegistry()
    tools.register(
        name="dangerous_test_tool",
        handler=dangerous_tool,
        input_schema={
            "required": ["command"],
            "properties": {"command": {"type": "string"}},
        },
        requires_approval=True,
        risk_classes=frozenset({RiskClass.EXECUTE}),
    )
    chat._tools_singleton = tools
    responses: list[str | ModelResponse] = [
        ModelResponse(
            tool_calls=(ToolCall("live-danger", "dangerous_test_tool", {"command": "once"}),)
        )
    ]
    if approved:
        responses.append(ModelResponse("approved result"))
    provider = MockLLM(responses)

    with client(f"live-{'approve' if approved else 'deny'}", provider) as api:
        with ThreadPoolExecutor(max_workers=1) as pool:
            stream = pool.submit(api.post, "/api/chat/stream", json={"message": "run it"})
            assert api.portal is not None
            for _ in range(100):
                if api.portal.call(api.app.state.approval_broker.pending_count) == 1:
                    break
                time.sleep(0.01)
            else:
                pytest.fail("live stream did not register its pending approval")

            decision = api.post(
                "/api/chat/approve/live-danger",
                json={
                    "approved": approved,
                    "run_id": "00000000-0000-4000-8000-000000000001",
                },
            )
            response = stream.result(timeout=5)

        assert decision.status_code == 200
        assert response.status_code == 200
        event_names = [
            line.removeprefix("event: ")
            for line in response.text.splitlines()
            if line.startswith("event: ")
        ]
        expected_events = ["approval_required", "approval_decided"]
        expected_events.append("tool_call" if approved else "tool_denied")
        expected_events.append("done")
        positions = [event_names.index(event) for event in expected_events]
        assert positions == sorted(positions)
        assert f'"approved": {str(approved).lower()}' in response.text
        assert '"run_id": "00000000-0000-4000-8000-000000000001"' in response.text
        assert "must-not-reach-sse" not in response.text
        if approved:
            assert executions == ["once"]
        else:
            assert executions == []
        assert api.portal.call(api.app.state.approval_broker.pending_count) == 0


def test_web_search_sources_are_projected_without_result_content() -> None:
    from app.routes import chat

    async def search_tool(query: str) -> dict:
        assert query == "safe projection"
        return {
            "results": [
                {
                    "title": "Safe title",
                    "url": "https://example.test/safe",
                    "snippet": "private snippet",
                    "content": "private full content",
                },
                {"title": "Second title", "url": "https://example.test/second"},
            ],
            "query": query,
        }

    tools = SecureToolRegistry()
    tools.register(
        name="web_search",
        handler=search_tool,
        input_schema={
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        risk_classes=frozenset({RiskClass.READ}),
    )
    chat._tools_singleton = tools
    provider = MockLLM(
        [
            ModelResponse(
                tool_calls=(ToolCall("search-1", "web_search", {"query": "safe projection"}),)
            ),
            ModelResponse("search complete"),
        ]
    )

    with client("source-user", provider) as api:
        response = api.post("/api/chat/stream", json={"message": "search"})

    assert response.status_code == 200
    source_marker = "event: sources\ndata: "
    assert source_marker in response.text
    sources = json.loads(response.text.split(source_marker, 1)[1].split("\n\n", 1)[0])
    assert sources == [
        {"title": "Safe title", "url": "https://example.test/safe"},
        {"title": "Second title", "url": "https://example.test/second"},
    ]
    assert "private snippet" not in response.text
    assert "private full content" not in response.text
    assert response.text.index("event: sources") < response.text.index("event: done")


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
        owner_context = RunContext(
            alice["user_id"],
            "conversation",
            "00000000-0000-4000-8000-000000000002",
            "correlation",
        )
        approval = AuthorizationRequest(
            "endpoint-call",
            "terminal",
            "b" * 64,
            frozenset({RiskClass.EXECUTE}),
            "side_effects_require_approval",
        )
        assert api.portal is not None
        authorizer = app.state.approval_broker.authorizer(owner_context)
        api.portal.call(authorizer.prepare, approval)
        outcome = api.portal.start_task_soon(authorizer.authorize, approval)
        for _ in range(20):
            if api.portal.call(app.state.approval_broker.pending_count) == 1:
                break

        bob_response = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
            json={
                "approved": True,
                "run_id": "00000000-0000-4000-8000-000000000002",
            },
        )
        assert bob_response.status_code == 404

        wrong_run = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={
                "approved": True,
                "run_id": "00000000-0000-4000-8000-000000000003",
            },
        )
        assert wrong_run.status_code == 404

        alice_response = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={
                "approved": True,
                "run_id": "00000000-0000-4000-8000-000000000002",
            },
        )
        assert alice_response.status_code == 200
        assert outcome.result(timeout=1).approved is True
        repeated = api.post(
            "/api/chat/approve/endpoint-call",
            headers={"Authorization": f"Bearer {alice['access_token']}"},
            json={
                "approved": False,
                "run_id": "00000000-0000-4000-8000-000000000002",
            },
        )
        assert repeated.status_code == 404


def test_pending_receipt_can_be_decided_after_app_restart(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/restart-approval.db"
    settings = Settings(llm_provider="mock", debug=True, database_url=database_url)
    run_id = "00000000-0000-4000-8000-000000000004"
    owner = RunContext("placeholder", "conversation", run_id, "correlation")
    approval = AuthorizationRequest(
        "restart-call",
        "terminal",
        "c" * 64,
        frozenset({RiskClass.EXECUTE}),
        "side_effects_require_approval",
    )

    with TestClient(create_app(settings)) as first:
        auth = first.post(
            "/api/auth/register",
            json={"username": "restart-owner", "password": "valid-...-123"},
        ).json()
        owner = RunContext(auth["user_id"], "conversation", run_id, "correlation")
        assert first.portal is not None
        first.portal.call(first.app.state.approval_broker.authorizer(owner).prepare, approval)

    with TestClient(create_app(settings)) as restarted:
        decision = restarted.post(
            "/api/chat/approve/restart-call",
            headers={"Authorization": f"Bearer {auth['access_token']}"},
            json={"approved": True, "run_id": run_id},
        )
        assert decision.status_code == 200
        assert restarted.portal is not None
        outcome = restarted.portal.call(
            restarted.app.state.approval_broker.authorizer(owner).authorize, approval
        )
        assert outcome.approved is True
        assert outcome.reason_code == "user_approved"


def test_concurrent_approval_endpoints_have_one_winner(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/concurrent-endpoint.db"
    settings = Settings(llm_provider="mock", debug=True, database_url=database_url)
    with TestClient(create_app(settings)) as api:
        auth = api.post(
            "/api/auth/register",
            json={"username": "race-owner", "password": "valid-...-123"},
        ).json()
        run_id = "00000000-0000-4000-8000-000000000005"
        owner = RunContext(auth["user_id"], "conversation", run_id, "correlation")
        approval = AuthorizationRequest(
            "race-call",
            "terminal",
            "d" * 64,
            frozenset({RiskClass.EXECUTE}),
            "side_effects_require_approval",
        )
        assert api.portal is not None
        api.portal.call(api.app.state.approval_broker.authorizer(owner).prepare, approval)

        def decide(approved: bool) -> int:
            return api.post(
                "/api/chat/approve/race-call",
                headers={"Authorization": f"Bearer {auth['access_token']}"},
                json={"approved": approved, "run_id": run_id},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(decide, (True, False)))
        assert sorted(statuses) == [200, 404]
