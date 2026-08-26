"""Startup policy tests for encrypted live persistent memory."""

from __future__ import annotations

import base64
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.chat import get_tool_registry
from app.runtime.factory import RunContext

VALID_KEY = base64.urlsafe_b64encode(b"1" * 32).decode().rstrip("=")


def _settings(tmp_path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "llm_provider": "mock",
        "debug": True,
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'startup.db'}",
    }
    values.update(overrides)
    return Settings(**values)


def _startup_error(settings: Settings) -> RuntimeError:
    with pytest.raises(RuntimeError) as caught, TestClient(create_app(settings)):
        pass
    return caught.value


def test_encrypted_memory_is_enabled_by_default() -> None:
    assert Settings().memory_encryption_enabled is True


def test_startup_rejects_missing_encryption_key_without_leaking_configuration(tmp_path) -> None:
    error = _startup_error(_settings(tmp_path, encryption_master_key=""))
    message = str(error)
    assert message == "Encrypted memory startup configuration is invalid"
    assert "ARCHON_ENCRYPTION_MASTER_KEY" not in message


@pytest.mark.parametrize(
    "weak_key",
    [
        "too-short",
        "not!base64",
        base64.urlsafe_b64encode(b"x" * 31).decode().rstrip("="),
        base64.urlsafe_b64encode(b"x" * 33).decode().rstrip("="),
        "changeme",
        "default",
        "<replace-with-at-least-32-byte-secret>",
    ],
)
def test_startup_rejects_malformed_wrong_length_and_known_weak_keys(tmp_path, weak_key) -> None:
    error = _startup_error(_settings(tmp_path, encryption_master_key=weak_key))
    assert str(error) == "Encrypted memory startup configuration is invalid"
    assert weak_key not in str(error)


def test_example_template_key_is_rejected(tmp_path) -> None:
    template = Path(__file__).parents[2] / ".env.example"
    line = next(
        line
        for line in template.read_text().splitlines()
        if line.startswith("ARCHON_ENCRYPTION_MASTER_KEY=")
    )
    error = _startup_error(_settings(tmp_path, encryption_master_key=line.partition("=")[2]))
    assert str(error) == "Encrypted memory startup configuration is invalid"


def test_startup_configures_encrypted_memory_with_valid_key(tmp_path) -> None:
    app = create_app(_settings(tmp_path, encryption_master_key=VALID_KEY))
    with TestClient(app):
        assert app.state.scoped_memory is not None


def test_startup_accepts_generated_256_bit_urlsafe_key(tmp_path) -> None:
    app = create_app(_settings(tmp_path, encryption_master_key=secrets.token_urlsafe(32)))
    with TestClient(app):
        assert app.state.scoped_memory is not None


def test_explicit_disabled_mode_hides_memory_api_and_live_tool(tmp_path) -> None:
    settings = _settings(
        tmp_path,
        memory_encryption_enabled=False,
        encryption_master_key="",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/memory/facts").status_code == 404
        registry = get_tool_registry(
            context=RunContext.create(
                user_id="owner",
                conversation_id="conversation",
                correlation_id="correlation",
            ),
            scoped_memory=None,
            conversations=app.state.conversations,
        )
        assert "memory" not in {tool["name"] for tool in registry.list_tools()}
