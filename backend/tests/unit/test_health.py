"""Unit tests for health check endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Test settings with mock LLM provider."""
    return Settings(
        llm_provider="mock",
        llm_model="test-model",
        debug=True,
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Test client using app factory with test settings."""
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


class TestHealthEndpoints:
    """Health check endpoint tests."""

    @pytest.mark.unit
    def test_liveness_probe(self, client: TestClient) -> None:
        """GET /healthz returns alive status."""
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    @pytest.mark.unit
    def test_readiness_probe(self, client: TestClient) -> None:
        """GET /readyz returns ready status."""
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    @pytest.mark.unit
    def test_app_metadata(self, client: TestClient) -> None:
        """App has correct title and version from settings."""
        assert client.app.title == "Archon"
        assert client.app.version == "0.1.0"
