"""Unit tests for health check endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

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
                "rate_limiter": {"backend": "memory", "status": "up"},
                "telemetry": {"backend": "disabled", "status": "disabled"},
                "model_provider_circuit": "closed",
                "vector_store": "sql-json-cosine",
                "evidence_verifier": "disabled",
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
                "rate_limiter": {"backend": "memory", "status": "up"},
                "telemetry": {"backend": "disabled", "status": "disabled"},
                "model_provider_circuit": "closed",
                "vector_store": "sql-json-cosine",
                "evidence_verifier": "disabled",
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
    def test_readiness_probe_reports_rate_limiter_failure(self, client: TestClient) -> None:
        async def unavailable() -> None:
            raise RuntimeError("redis unavailable")

        client.app.state.rate_limiter.check_health = unavailable
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["dependencies"]["rate_limiter"] == {
            "backend": "memory",
            "status": "down",
        }

    @pytest.mark.unit
    def test_readiness_reports_only_active_otel_as_up(self, client: TestClient) -> None:
        class Exporter:
            is_active = True

        client.app.state.otel_exporter = Exporter()
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["dependencies"]["telemetry"] == {
            "backend": "otlp-grpc",
            "status": "up",
        }

    @pytest.mark.unit
    def test_readiness_reports_configured_but_inactive_otel_as_down(
        self, client: TestClient
    ) -> None:
        class Exporter:
            is_active = False

        client.app.state.otel_exporter = Exporter()
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["dependencies"]["telemetry"] == {
            "backend": "otlp-grpc",
            "status": "down",
        }

    @pytest.mark.unit
    def test_app_metadata(self, client: TestClient) -> None:
        """App has correct title and version from settings."""
        assert client.app.title == "Archon"
        assert client.app.version == "0.1.0"


def test_verifier_settings_are_disabled_and_bounded_by_default() -> None:
    assert Settings().verifier_enabled is False
    with pytest.raises(ValidationError):
        Settings(verifier_model="bad model")
    with pytest.raises(ValidationError):
        Settings(verifier_input_tokens=32_769)
    with pytest.raises(ValidationError):
        Settings(verifier_output_tokens=8_193)
    with pytest.raises(ValidationError):
        Settings(verifier_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(verifier_retries=2)


def test_enabled_verifier_is_app_scoped_and_readiness_is_safe(tmp_path) -> None:
    settings_a = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'a.db'}", verifier_enabled=True
    )
    settings_b = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'b.db'}", verifier_enabled=True
    )
    app_a = create_app(settings_a)
    app_b = create_app(settings_b)
    with TestClient(app_a) as client_a, TestClient(app_b) as _client_b:
        assert app_a.state.evidence_verifier is not app_b.state.evidence_verifier
        assert app_a.state.evidence_verifier._provider is app_a.state.model_provider
        assert app_b.state.evidence_verifier._provider is app_b.state.model_provider
        ready = client_a.get("/readyz").json()
        assert ready["dependencies"]["evidence_verifier"] == "enabled"
        assert "model" not in str(ready["dependencies"]["evidence_verifier"])
