"""Tests for middleware: correlation ID injection."""

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
        yield c


class TestCorrelationIdMiddleware:
    """Correlation ID middleware tests."""

    @pytest.mark.unit
    def test_auto_generates_correlation_id(self, client: TestClient) -> None:
        """Requests without X-Correlation-ID get one auto-generated."""
        response = client.get("/healthz")
        assert "X-Correlation-ID" in response.headers
        cid = response.headers["X-Correlation-ID"]
        assert len(cid) == 36  # UUID format

    @pytest.mark.unit
    def test_uses_client_provided_id(self, client: TestClient) -> None:
        """Requests with X-Correlation-ID use the provided value."""
        response = client.get(
            "/healthz",
            headers={"X-Correlation-ID": "my-custom-id-123"},
        )
        assert response.headers["X-Correlation-ID"] == "my-custom-id-123"

    @pytest.mark.unit
    def test_different_requests_get_different_ids(self, client: TestClient) -> None:
        """Each request gets a unique correlation ID."""
        r1 = client.get("/healthz")
        r2 = client.get("/healthz")
        assert r1.headers["X-Correlation-ID"] != r2.headers["X-Correlation-ID"]
