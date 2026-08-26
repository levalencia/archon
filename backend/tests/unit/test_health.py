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
        database_url="sqlite+aiosqlite:///:memory:",
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
        assert response.json()["status"] == "alive"
        assert "llm_model" in response.json()

    @pytest.mark.unit
    def test_readiness_probe(self, client: TestClient) -> None:
        """GET /readyz returns ready status."""
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "dependencies": {
                "conversation_repository": "up",
                "model_provider_circuit": "closed",
                "vector_store": "sql-json-cosine",
                "embeddings": {
                    "provider": "mock",
                    "model": "text-embedding-3-small",
                    "dimensions": 256,
                    "mock": True,
                    "readiness": "non-production",
                },
            },
        }

    @pytest.mark.unit
    def test_readiness_probe_reports_repository_failure(self, client: TestClient) -> None:
        async def unavailable() -> None:
            raise RuntimeError("database unavailable")

        client.app.state.conversations.check_health = unavailable
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {
            "status": "degraded",
            "dependencies": {
                "conversation_repository": "down",
                "model_provider_circuit": "closed",
                "vector_store": "sql-json-cosine",
                "embeddings": {
                    "provider": "mock",
                    "model": "text-embedding-3-small",
                    "dimensions": 256,
                    "mock": True,
                    "readiness": "non-production",
                },
            },
        }

    @pytest.mark.unit
    def test_app_metadata(self, client: TestClient) -> None:
        """App has correct title and version from settings."""
        assert client.app.title == "Archon"
        assert client.app.version == "0.1.0"
