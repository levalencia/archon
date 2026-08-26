"""Tests for eval harness wiring (POST /evaluate, GET /evaluators) and cost tracking."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def reset_chat_state(tmp_path, monkeypatch):
    from app.routes import chat

    chat._tools_singleton = None
    chat._db_store = None
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/eval.db")
    yield
    chat._tools_singleton = None
    chat._db_store = None


@contextmanager
def admin_client(provider=None) -> Iterator[TestClient]:
    settings = Settings(llm_provider="mock", debug=True)
    app = (
        create_app(settings)
        if provider is None
        else create_app(settings, model_provider_factory=lambda _settings: provider)
    )
    with TestClient(app) as api:
        token = api.post(
            "/api/auth/register",
            json={"username": "admin", "password": "secret1"},
        ).json()["access_token"]
        api.headers.update({"Authorization": f"Bearer {token}"})
        yield api


# ---------- TASK 1: eval harness endpoints ----------


def test_evaluate_endpoint_returns_scores():
    with admin_client() as api:
        resp = api.post(
            "/api/security/evaluate",
            json={
                "response": (
                    "Python is a programming language used for data science and web development."
                ),
                "context": (
                    "Python is a popular programming language widely used in data science, "
                    "web development, and automation."
                ),
                "question": "What is Python used for?",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "scores" in data
        names = [s["name"] for s in data["scores"]]
        assert "faithfulness" in names
        assert "relevance" in names
        # Both should have non-zero scores given the overlap
        for s in data["scores"]:
            assert 0.0 <= s["score"] <= 1.0
            assert isinstance(s["reason"], str)


def test_evaluate_empty_inputs():
    with admin_client() as api:
        resp = api.post(
            "/api/security/evaluate",
            json={"response": "", "context": "", "question": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Empty inputs → 0 scores
        for s in data["scores"]:
            assert s["score"] == 0.0


def test_evaluators_endpoint_lists_names():
    with admin_client() as api:
        resp = api.get("/api/security/evaluators")
        assert resp.status_code == 200
        data = resp.json()
        assert "evaluators" in data
        assert "faithfulness" in data["evaluators"]
        assert "relevance" in data["evaluators"]


# ---------- TASK 2: cost tracking ----------


def test_cost_tracker_record():
    from app.observability.cost_tracker import CostTracker

    tracker = CostTracker()
    info = tracker.record(
        conversation_id="conv-1",
        user_id="user-1",
        model="gpt-4o",
        input_tokens=500,
        output_tokens=500,
    )
    assert "cost_usd" in info
    assert info["cost_usd"] > 0
    assert info["tokens"] == 1000


def test_cost_tracker_defaults_for_unknown_model():
    from app.observability.cost_tracker import COST_PER_1K, CostTracker

    tracker = CostTracker()
    info = tracker.record(
        conversation_id="conv-2",
        user_id="user-2",
        model="unknown-model-xyz",
        input_tokens=1000,
        output_tokens=0,
    )
    expected = (1000 / 1000) * COST_PER_1K["default"][0]  # input rate for unknown model
    assert abs(info["cost_usd"] - expected) < 1e-8


def test_stream_done_event_includes_cost_usd():
    """Verify the done SSE event payload includes cost_usd field."""
    from app.agents.mock_llm import MockLLM

    provider = MockLLM(["hello world"])
    with admin_client(provider) as api:
        conv = api.post("/api/conversations", json={}).json()["id"]
        resp = api.post(
            "/api/chat/stream",
            json={"message": "hi", "conversation_id": conv},
        )
        assert resp.status_code == 200
        text = resp.text
        # Parse the done event
        marker = "event: done\ndata: "
        assert marker in text, "No done event found in SSE stream"
        payload_str = text.split(marker, 1)[1].split("\n\n", 1)[0]
        payload = json.loads(payload_str)
        assert "cost_usd" in payload
        assert isinstance(payload["cost_usd"], (int, float))
        assert payload["cost_usd"] >= 0
