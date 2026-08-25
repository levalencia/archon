"""Tests for the multi-agent coordinator route."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.multi_agent import router
from app.security.auth import get_current_user


def _build_app(llm_mock: AsyncMock) -> FastAPI:
    """Build a minimal FastAPI app with the multi-agent router + mocked deps."""
    app = FastAPI()
    app.include_router(router)

    # Mock auth
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "test", "username": "tester"}

    # Provide settings with mock LLM
    class _FakeSettings:
        llm_provider = "mock"
        llm_model = "mock-model"
        llm_api_key = ""
        llm_base_url = ""
        llm_fallback_providers = ""

    app.state.settings = _FakeSettings()
    return app


@pytest.mark.asyncio
async def test_multi_agent_endpoint_returns_answer() -> None:
    """POST /api/chat/multi-agent should return answer + agents_used."""
    mock_llm = AsyncMock()
    mock_llm.chat = AsyncMock(return_value="mock response")
    app = _build_app(mock_llm)

    client = TestClient(app)
    resp = client.post("/api/chat/multi-agent", json={"message": "What is AI?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "agents_used" in data
    assert set(data["agents_used"]) == {"planner", "retriever", "validator", "synthesizer"}
    assert data["iterations"] == 4
    assert "token_budget_report" in data


def test_multi_agent_endpoint_rejects_empty_message() -> None:
    """Empty message should return 422."""
    app = _build_app(AsyncMock())
    client = TestClient(app)
    resp = client.post("/api/chat/multi-agent", json={"message": ""})
    assert resp.status_code == 422
