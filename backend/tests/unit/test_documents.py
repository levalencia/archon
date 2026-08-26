"""Tests for document API endpoints (upload, query, list, delete)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.config import Settings
from app.main import create_app
from app.routes import documents


@pytest.fixture
def client() -> TestClient:
    settings = Settings(llm_provider="mock", debug=True)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        response = c.post(
            "/api/auth/register", json={"username": "document-user", "password": "secret1"}
        )
        c.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield c


SAMPLE_DOC = {
    "title": "Python Programming Guide",
    "content": (
        "Python is a high-level programming language. "
        "It supports object-oriented, functional, and procedural paradigms. "
        "Python is widely used in web development, data science, machine learning, "
        "and artificial intelligence applications."
    ),
    "source": "guide.pdf",
}


class TestDocumentUpload:
    """Document upload tests."""

    @pytest.mark.unit
    def test_upload_document(self, client: TestClient) -> None:
        response = client.post("/api/documents/upload", json=SAMPLE_DOC)
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Python Programming Guide"
        assert data["chunks"] >= 1
        assert len(data["id"]) == 36

    @pytest.mark.unit
    def test_upload_empty_content_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents/upload",
            json={"title": "Empty", "content": ""},
        )
        assert response.status_code == 422


class TestDocumentQuery:
    """RAG query tests."""

    @pytest.mark.unit
    def test_query_after_upload(self, client: TestClient) -> None:
        # Upload first
        client.post("/api/documents/upload", json=SAMPLE_DOC)

        # Query
        response = client.post(
            "/api/documents/query",
            json={"question": "What is Python used for?"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert data["chunks_retrieved"] >= 1
        assert len(data["sources"]) >= 1

    @pytest.mark.unit
    def test_query_empty_store(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents/query",
            json={"question": "Unknown topic", "document_id": "nonexistent-doc-id"},
        )
        assert response.status_code == 404


class TestDocumentList:
    """Document listing tests."""

    @pytest.mark.unit
    def test_list_after_upload(self, client: TestClient) -> None:
        upload_resp = client.post("/api/documents/upload", json=SAMPLE_DOC)
        doc_id = upload_resp.json()["id"]

        response = client.get("/api/documents")
        assert response.status_code == 200
        data = response.json()
        ids = [d["id"] for d in data]
        assert doc_id in ids


class TestDocumentDelete:
    """Document deletion tests."""

    @pytest.mark.unit
    def test_delete_document(self, client: TestClient) -> None:
        upload_resp = client.post("/api/documents/upload", json=SAMPLE_DOC)
        doc_id = upload_resp.json()["id"]

        response = client.delete(f"/api/documents/{doc_id}")
        assert response.status_code == 204


@pytest.mark.unit
def test_postgres_vector_store_log_uses_only_safe_database_url_metadata(monkeypatch) -> None:
    database_url = "postgresql+asyncpg://db-user:db-pass@private-db.internal:5432/archon"
    settings = Settings(
        llm_provider="mock",
        vector_store_backend="postgres",
        database_url=database_url,
    )
    request = Request({"type": "http", "app": create_app(settings=settings)})
    captured: dict[str, object] = {}

    def capture(event: str, **values: object) -> None:
        captured.update(event=event, **values)

    monkeypatch.setattr(documents.logger, "info", capture)
    monkeypatch.setattr(documents, "_vector_store", None)
    store = documents._get_vector_store(request)

    assert captured["event"] == "vector_store_initialized"
    assert captured["backend"] == "postgres"
    assert captured["database_url_length"] == len(database_url)
    assert isinstance(captured["database_url_sha256"], str)
    assert len(captured["database_url_sha256"]) == 12
    rendered = repr(captured)
    for sensitive in (database_url, "db-user", "db-pass", "private-db.internal"):
        assert sensitive not in rendered
    assert "url" not in captured

    # Avoid leaking this test store through module-level state.
    documents._vector_store = None
    assert store is not None
