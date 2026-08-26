"""Sprint 3A durable document acceptance tests."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings(path) -> Settings:
    return Settings(
        llm_provider="mock",
        debug=True,
        database_url=f"sqlite+aiosqlite:///{path}",
        rate_limit_requests=1000,
    )


def _auth(client: TestClient, username: str) -> None:
    response = client.post("/api/auth/register", json={"username": username, "password": "secret1"})
    if response.status_code != 200:
        response = client.post(
            "/api/auth/login", json={"username": username, "password": "secret1"}
        )
    client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"


def test_restart_ownership_projects_delete_and_raw_pii(tmp_path) -> None:
    database = tmp_path / "durable.db"
    settings = _settings(database)
    with TestClient(create_app(settings)) as first:
        _auth(first, "owner-a")
        created = first.post(
            "/api/documents/upload",
            json={
                "title": "alice@example.com notes",
                "source": "alice@example.com.pdf",
                "content": "Contact alice@example.com. Durable retrieval content.",
                "project_id": "project-a",
            },
        )
        assert created.status_code == 201
        document_id = created.json()["id"]
        assert first.get("/api/documents", params={"project_id": "project-b"}).json() == []

    # Metadata and vectors survive a new app/process lifetime.
    with TestClient(create_app(settings)) as restarted:
        _auth(restarted, "owner-a")
        listing = restarted.get("/api/documents", params={"project_id": "project-a"})
        assert [item["id"] for item in listing.json()] == [document_id]
        query = restarted.post(
            "/api/documents/query",
            json={
                "question": "What content is durable?",
                "document_id": document_id,
                "project_id": "project-a",
            },
        )
        assert query.status_code == 200
        assert query.json()["chunks_retrieved"] == 1

        with TestClient(create_app(settings)) as other:
            _auth(other, "owner-b")
            assert other.get("/api/documents", params={"project_id": "project-a"}).json() == []
            foreign = other.delete(
                f"/api/documents/{document_id}", params={"project_id": "project-a"}
            )
            assert foreign.status_code == 404

        deleted = restarted.delete(
            f"/api/documents/{document_id}", params={"project_id": "project-a"}
        )
        assert deleted.status_code == 204

    connection = sqlite3.connect(database)
    try:
        raw = " ".join(
            str(value)
            for table in ("documents", "vector_chunks")
            for row in connection.execute(f"SELECT * FROM {table}")  # noqa: S608 - fixed test tables
            for value in row
        )
        assert "alice@example.com" not in raw
        assert connection.execute("SELECT count(*) FROM vector_chunks").fetchone()[0] == 0
    finally:
        connection.close()


def test_readiness_is_honest_about_mock_and_json_backend(tmp_path) -> None:
    with TestClient(create_app(_settings(tmp_path / "ready.db"))) as client:
        ready = client.get("/readyz").json()["dependencies"]
        assert ready["vector_store"] == "sql-json-cosine"
        assert ready["embeddings"]["mock"] is True
        assert ready["embeddings"]["readiness"] == "non-production"
