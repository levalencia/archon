"""Focused tests for bounded document ingestion resources."""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'bounds.db'}",
        rate_limit_requests=1000,
        **overrides,
    )
    return TestClient(create_app(settings))


def _authenticate(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register", json={"username": "bounded-user", "password": "SecurePass123!"}
    )
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def test_oversized_upload_is_rejected_before_embedding(tmp_path) -> None:
    with _client(tmp_path, document_max_characters=10) as client:
        _authenticate(client)
        embed_batch = AsyncMock(side_effect=AssertionError("embedding must not run"))
        client.app.state.embedding_service.embed_batch = embed_batch
        response = client.post(
            "/api/documents/upload", json={"title": "large", "content": "x" * 11}
        )
        assert response.status_code == 413
        embed_batch.assert_not_awaited()


def test_owner_project_document_quota_is_enforced_before_embedding(tmp_path) -> None:
    with _client(tmp_path, documents_max_per_owner_project=1) as client:
        _authenticate(client)
        first = client.post("/api/documents/upload", json={"title": "one", "content": "one"})
        assert first.status_code == 201
        embed_batch = AsyncMock(side_effect=AssertionError("embedding must not run"))
        client.app.state.embedding_service.embed_batch = embed_batch
        second = client.post("/api/documents/upload", json={"title": "two", "content": "two"})
        assert second.status_code == 413
        embed_batch.assert_not_awaited()


def test_chunk_limit_is_rejected_before_embedding(tmp_path) -> None:
    with _client(tmp_path, document_max_chunks=1) as client:
        _authenticate(client)
        embed_batch = AsyncMock(side_effect=AssertionError("embedding must not run"))
        client.app.state.embedding_service.embed_batch = embed_batch
        response = client.post(
            "/api/documents/upload",
            json={"title": "many chunks", "content": "sentence. " * 200},
        )
        assert response.status_code == 413
        embed_batch.assert_not_awaited()
