"""Shared test fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings


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
