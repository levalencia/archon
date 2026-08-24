"""Tests for admin API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    settings = Settings(llm_provider="mock", debug=True)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        response = c.post("/api/auth/register", json={"username": "admin", "password": "secret1"})
        token = response.json()["access_token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


class TestAdminHealth:
    """Admin health endpoint tests."""

    @pytest.mark.unit
    def test_detailed_health(self, client: TestClient) -> None:
        response = client.get("/api/admin/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "services" in data

    @pytest.mark.unit
    def test_health_has_service_status(self, client: TestClient) -> None:
        data = client.get("/api/admin/health").json()
        assert data["services"]["api"] == "up"
        assert data["services"]["audit_logger"] == "up"


class TestAdminAudit:
    """Admin audit endpoints."""

    @pytest.mark.unit
    def test_get_audit_log(self, client: TestClient) -> None:
        response = client.get("/api/admin/audit")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "count" in data

    @pytest.mark.unit
    def test_audit_stats(self, client: TestClient) -> None:
        response = client.get("/api/admin/audit/stats")
        assert response.status_code == 200
        data = response.json()
        assert "action_counts" in data
        assert "total" in data

    @pytest.mark.unit
    def test_audit_search(self, client: TestClient) -> None:
        response = client.get("/api/admin/audit/search")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data

    @pytest.mark.unit
    def test_audit_search_with_filters(self, client: TestClient) -> None:
        response = client.get(
            "/api/admin/audit/search",
            params={"security_level": "warning"},
        )
        assert response.status_code == 200


class TestAdminMetrics:
    """Admin metrics endpoints."""

    @pytest.mark.unit
    def test_get_metrics(self, client: TestClient) -> None:
        response = client.get("/api/admin/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "uptime_seconds" in data
        assert "circuit_breakers" in data

    @pytest.mark.unit
    def test_get_circuit_breakers(self, client: TestClient) -> None:
        response = client.get("/api/admin/circuit-breakers")
        assert response.status_code == 200
