"""Tests for document API endpoints (upload, query, list, delete)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes import documents


@pytest.fixture
def client(tmp_path) -> TestClient:
    documents._vector_store = documents.VectorStore()
    documents._document_registry.clear()
    settings = Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'documents.db'}",
    )
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c
    documents._document_registry.clear()


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
        assert data["answer"] == "I am a mock LLM."
        assert data["chunks_retrieved"] >= 1
        assert len(data["sources"]) >= 1

    @pytest.mark.unit
    def test_query_empty_store(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents/query",
            json={"question": "Unknown topic", "document_id": "nonexistent-doc-id"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chunks_retrieved"] == 0


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
