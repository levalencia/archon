"""Tests for document API endpoints (upload, query, list, delete)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.routes import documents
from app.services.documents import _scope_advisory_lock_key


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


def test_postgres_scope_lock_key_is_nul_free_and_collision_safe() -> None:
    first = _scope_advisory_lock_key("owner:project", "scope")
    second = _scope_advisory_lock_key("owner", "project:scope")
    assert "\0" not in first
    assert first != second
    assert _scope_advisory_lock_key("owner", "project") == '["owner","project"]'


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
def test_document_services_are_app_scoped() -> None:
    settings = Settings(llm_provider="mock")
    app_a = create_app(settings=settings)
    app_b = create_app(settings=settings)
    assert app_a is not app_b
    for name in ("_document_registry", "_vector_store", "_embedding_service"):
        assert not hasattr(documents, name)
