"""Tests for A/B testing, eval harness, and encrypted memory wiring."""

from __future__ import annotations

import asyncio
import base64
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
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield
    chat._tools_singleton = None
    chat._db_store = None


@contextmanager
def admin_client() -> Iterator[TestClient]:
    with TestClient(create_app(Settings(llm_provider="mock", debug=True))) as api:
        token = api.post(
            "/api/auth/register",
            json={"username": "admin", "password": "secret1"},
        ).json()["access_token"]
        api.headers.update({"Authorization": f"Bearer {token}"})
        yield api


# ---------------------------------------------------------------------------
# TASK 1: A/B testing endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("ab-test", {"question": "What is Python?", "models": ["model-a", "model-b"]}),
        ("ab-test", {"question": "Hello?", "models": ["only-model", "only-model"]}),
        (
            "ab-test",
            {
                "question": "Explain AI",
                "models": ["gpt-4", "claude"],
                "system_prompt_a": "Be concise.",
                "system_prompt_b": "Be verbose.",
            },
        ),
        (
            "harness",
            {
                "test_cases": [
                    {"question": "What is 2+2?", "expected_contains": ["answer"]},
                    {"question": "Explain gravity", "context": "physics"},
                ]
            },
        ),
        (
            "harness",
            {
                "test_cases": [
                    {
                        "question": "Capital of France?",
                        "expected_answer": "Paris",
                        "expected_contains": ["Paris"],
                    }
                ],
                "quality_threshold": 0.0,
            },
        ),
        ("harness", {"test_cases": []}),
    ],
)
def test_fabricated_live_evaluation_routes_are_retired(endpoint: str, payload: dict) -> None:
    with admin_client() as api:
        response = api.post(f"/api/security/{endpoint}", json=payload)
        assert response.status_code == 410
        body = response.json()
        assert "/api/evals/runs" in body["detail"]
        assert "variants" not in body
        assert "results" not in body


# ---------------------------------------------------------------------------
# TASK 3: Encrypted memory tests
# ---------------------------------------------------------------------------


def test_encrypted_memory_store_and_retrieve():
    """EncryptedMemoryStore can store and retrieve messages."""
    from app.memory.encrypted_memory import EncryptedMemoryStore

    store = EncryptedMemoryStore(base64.urlsafe_b64encode(b"7" * 32).decode().rstrip("="))
    loop = asyncio.new_event_loop()

    loop.run_until_complete(store.store("conv-1", "user", "Hello world"))
    loop.run_until_complete(store.store("conv-1", "assistant", "Hi there"))

    messages = loop.run_until_complete(store.retrieve("conv-1"))
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello world"
    assert messages[1]["role"] == "assistant"

    loop.close()


def test_encrypted_memory_per_conversation_isolation():
    """Different conversations have isolated encrypted storage."""
    from app.memory.encrypted_memory import EncryptedMemoryStore

    store = EncryptedMemoryStore(base64.urlsafe_b64encode(b"8" * 32).decode().rstrip("="))
    loop = asyncio.new_event_loop()

    loop.run_until_complete(store.store("conv-a", "user", "Secret A"))
    loop.run_until_complete(store.store("conv-b", "user", "Secret B"))

    msgs_a = loop.run_until_complete(store.retrieve("conv-a"))
    msgs_b = loop.run_until_complete(store.retrieve("conv-b"))

    assert len(msgs_a) == 1
    assert msgs_a[0]["content"] == "Secret A"
    assert len(msgs_b) == 1
    assert msgs_b[0]["content"] == "Secret B"

    # Delete one conversation
    deleted = loop.run_until_complete(store.delete_conversation("conv-a"))
    assert deleted is True
    msgs_a = loop.run_until_complete(store.retrieve("conv-a"))
    assert len(msgs_a) == 0

    loop.close()


def test_encrypted_memory_fallback_on_bad_config(tmp_path, monkeypatch):
    """get_persistent_memory falls back gracefully if encryption config is bad."""
    from app.memory import persistent

    # Reset singleton
    persistent._persistent_memory = None
    monkeypatch.setenv("ARCHON_MEMORY_ENCRYPTION_ENABLED", "true")
    monkeypatch.setenv("ARCHON_ENCRYPTION_MASTER_KEY", "")  # empty key → skip

    try:
        mem = persistent.get_persistent_memory()
        # Should still return a valid PersistentMemory (no crash)
        assert mem is not None
        assert isinstance(mem, persistent.PersistentMemory)
    finally:
        persistent._persistent_memory = None
