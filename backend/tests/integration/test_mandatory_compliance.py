"""Mandatory compliance boundary integration coverage."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.engine import AgentRuntime, StopReason
from app.runtime.events import AgentEventKind, RecordingEventSink
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract
from app.security.compliance import ComplianceViolationError
from app.security.policy import RiskClass
from app.tools.registry import SecureToolRegistry


class _Provider:
    capabilities = ProviderCapabilities(
        native_tools=True, json_mode=True, json_schema=True, usage=True
    )

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    async def complete(self, messages, tools=(), max_tokens=None, **kwargs) -> ModelResponse:
        return self.responses.pop(0)


class _NoTools:
    def definitions(self):
        return ()

    async def execute(self, call):
        raise AssertionError("no tool expected")


class _OneTool:
    def definitions(self):
        return (
            ToolDefinition(
                "lookup",
                "lookup",
                {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        )

    async def execute(self, call):
        return {"ok": True}


@pytest.mark.integration
def test_sync_and_sse_reject_before_persistence(tmp_path) -> None:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'compliance.db'}",
    )
    with TestClient(create_app(settings=settings)) as client:
        identity = client.post(
            "/api/auth/register", json={"username": "compliance-user", "password": "secret1"}
        ).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}
        payload = {"message": "Please provide a hacking tutorial"}
        assert client.post("/api/chat", json=payload, headers=headers).status_code == 422
        assert client.post("/api/chat/stream", json=payload, headers=headers).status_code == 422
        assert client.get("/api/conversations", headers=headers).json() == []


@pytest.mark.asyncio
async def test_dangerous_tool_compliance_runs_before_handler() -> None:
    invoked = False

    async def handler(content: str) -> dict[str, bool]:
        nonlocal invoked
        invoked = True
        return {"ok": True}

    registry = SecureToolRegistry()
    registry.register(
        "dangerous",
        handler,
        input_schema={"required": ["content"]},
        risk_classes=frozenset({RiskClass.WRITE}),
    )
    with pytest.raises(ComplianceViolationError):
        await registry.execute(ToolCall("call-1", "dangerous", {"content": "hacking tutorial"}))
    assert invoked is False


@pytest.mark.asyncio
async def test_structured_output_is_remediated_before_validation() -> None:
    provider = _Provider([ModelResponse('{"answer":"hacking tutorial"}', usage=TokenUsage(2, 2))])
    contract = ResponseContract(
        "answer-v1",
        "1",
        {"type": "object", "required": ["answer"]},
        lambda value: value,
    )
    result = await AgentRuntime(provider, _NoTools()).run(
        [Message(Role.USER, "safe")], response_contract=contract
    )

    assert result.stop_reason is StopReason.STRUCTURED_OUTPUT_INVALID
    assert result.structured_output is None
    assert "hacking tutorial" not in result.content


@pytest.mark.asyncio
async def test_tool_progress_is_remediated_before_event_persistence() -> None:
    sink = RecordingEventSink()
    provider = _Provider(
        [
            ModelResponse(
                "hacking tutorial",
                (ToolCall("call-1", "lookup", {}),),
                TokenUsage(2, 2),
            ),
            ModelResponse("safe final", usage=TokenUsage(2, 2)),
        ]
    )
    result = await AgentRuntime(provider, _OneTool(), events=sink).run([Message(Role.USER, "safe")])

    progress = next(event for event in sink.events if event.kind is AgentEventKind.MODEL_PROGRESS)
    assert progress.data["text"] == "[Response withheld by compliance policy]"
    assert all("hacking tutorial" not in str(event.data) for event in sink.events)
    assert result.content == "safe final"
