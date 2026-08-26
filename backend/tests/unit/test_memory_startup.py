"""Startup policy tests for encrypted live persistent memory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes.chat import get_tool_registry
from app.runtime.factory import RunContext

VALID_KEY = "configured-memory-key-at-least-32-bytes"


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


def test_startup_rejects_key_shorter_than_32_utf8_bytes(tmp_path) -> None:
    weak_key = "too-short"
    error = _startup_error(_settings(tmp_path, encryption_master_key=weak_key))
    assert str(error) == "Encrypted memory startup configuration is invalid"
    assert weak_key not in str(error)


def test_startup_configures_encrypted_memory_with_valid_key(tmp_path) -> None:
    app = create_app(_settings(tmp_path, encryption_master_key=VALID_KEY))
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
