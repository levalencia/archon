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

    chat._llm_singleton = None
    chat._tools_singleton = None
    chat._db_store = None
    monkeypatch.setenv("ARCHON_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield
    chat._llm_singleton = None
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


def test_ab_test_returns_two_variants():
    with admin_client() as api:
        resp = api.post(
            "/api/security/ab-test",
            json={"question": "What is Python?", "models": ["model-a", "model-b"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["question"] == "What is Python?"
        assert len(data["variants"]) == 2
        names = [v["name"] for v in data["variants"]]
        assert "model-a" in names
        assert "model-b" in names
        for v in data["variants"]:
            assert v["samples"] == 1
            assert "avg_score" in v


def test_ab_test_single_model_duplicated():
    """When only one model is provided, it should still work (same model both sides)."""
    with admin_client() as api:
        resp = api.post(
            "/api/security/ab-test",
            json={"question": "Hello?", "models": ["only-model", "only-model"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["variants"]) == 2


def test_ab_test_custom_prompts():
    with admin_client() as api:
        resp = api.post(
            "/api/security/ab-test",
            json={
                "question": "Explain AI",
                "models": ["gpt-4", "claude"],
                "system_prompt_a": "Be concise.",
                "system_prompt_b": "Be verbose.",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["test_name"].startswith("ab-")


# ---------------------------------------------------------------------------
# TASK 2: Eval harness endpoint tests
# ---------------------------------------------------------------------------


def test_harness_batch_returns_results():
    with admin_client() as api:
        resp = api.post(
            "/api/security/harness",
            json={
                "test_cases": [
                    {"question": "What is 2+2?", "expected_contains": ["answer"]},
                    {"question": "Explain gravity", "context": "physics"},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["passed"] + data["failed"] == 2
        assert 0.0 <= data["pass_rate"] <= 1.0
        assert len(data["results"]) == 2
        for r in data["results"]:
            assert "case_id" in r
            assert "score" in r


def test_harness_with_expected_answer():
    with admin_client() as api:
        resp = api.post(
            "/api/security/harness",
            json={
                "test_cases": [
                    {
                        "question": "Capital of France?",
                        "expected_answer": "Paris",
                        "expected_contains": ["Paris"],
                    },
                ],
                "quality_threshold": 0.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1


def test_harness_empty_cases():
    with admin_client() as api:
        resp = api.post(
            "/api/security/harness",
            json={"test_cases": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pass_rate"] == 0.0


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
