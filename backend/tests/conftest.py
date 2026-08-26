"""Shared test fixtures."""

from __future__ import annotations

import os

import pytest

from app.config import Settings

TEST_MEMORY_ENCRYPTION_KEY = "test-memory-encryption-key-32-bytes-minimum"
os.environ["ARCHON_ENCRYPTION_MASTER_KEY"] = TEST_MEMORY_ENCRYPTION_KEY


@pytest.fixture(autouse=True)
def isolated_test_database(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test process-local and independent of developer database settings."""
    monkeypatch.setenv(
        "ARCHON_DATABASE_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'archon-test.db'}",
    )


@pytest.fixture
def test_settings() -> Settings:
    """Base test settings. Override per test as needed."""
    return Settings(
        llm_provider="mock",
        llm_model="test-model",
        debug=True,
        database_url="sqlite+aiosqlite:///test.db",
        redis_url="redis://localhost:6379/1",
        secret_key="test-secret-key",
    )
