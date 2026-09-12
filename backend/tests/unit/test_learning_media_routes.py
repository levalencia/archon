"""Authenticated catalog and signed byte-range delivery for learning media."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _library(root: Path) -> None:
    target = root / "published" / "request-lifecycle" / "audio-overview"
    target.mkdir(parents=True)
    audio = target / "lesson.mp3"
    audio.write_bytes(b"0123456789")
    content = target / "audio-script.json"
    content.write_text(
        json.dumps({"segments": [{"chapter": "Start", "text": "Hello"}]}),
        encoding="utf-8",
    )
    catalog = {
        "schema": "cogentrex.learning-library",
        "version": 1,
        "generated_at": "2026-09-04T12:00:00Z",
        "source_commit": "a" * 40,
        "packs": [
            {
                "id": "request-lifecycle",
                "title": "Request Lifecycle",
                "purpose": "Follow a governed request end to end.",
                "artifacts": [
                    {
                        "id": "audio-overview",
                        "type": "audio",
                        "title": "Request Lifecycle Audio Overview",
                        "status": "published",
                        "language": "en",
                        "file": "published/request-lifecycle/audio-overview/lesson.mp3",
                        "media_type": "audio/mpeg",
                        "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                        "content_file": (
                            "published/request-lifecycle/audio-overview/audio-script.json"
                        ),
                        "content_sha256": hashlib.sha256(content.read_bytes()).hexdigest(),
                        "source_commit": "a" * 40,
                        "limitations": ["Derived learning material, not canonical evidence."],
                    }
                ],
            }
        ],
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/register", json={"username": "learner", "password": "secret1"}
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def media_client(tmp_path: Path) -> Iterator[TestClient]:
    root = tmp_path / "library"
    root.mkdir()
    _library(root)
    app = create_app(
        Settings(
            llm_provider="mock",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'media.db'}",
            secret_key="test-learning-media-secret",
            learning_media_enabled=True,
            learning_media_library_root=str(root),
            learning_media_signed_url_ttl_seconds=300,
        )
    )
    with TestClient(app) as client:
        yield client


def test_catalog_requires_auth_and_hides_files(media_client: TestClient) -> None:
    assert media_client.get("/api/learning-media/catalog").status_code == 401
    response = media_client.get("/api/learning-media/catalog", headers=_headers(media_client))
    assert response.status_code == 200
    artifact = response.json()["packs"][0]["artifacts"][0]
    assert artifact["id"] == "audio-overview"
    assert "file" not in artifact


def test_signed_media_url_supports_byte_ranges(media_client: TestClient) -> None:
    headers = _headers(media_client)
    signed = media_client.get(
        "/api/learning-media/artifacts/audio-overview/access", headers=headers
    )
    assert signed.status_code == 200
    url = signed.json()["url"]

    response = media_client.get(url, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["content-security-policy"].startswith("sandbox allow-scripts")


def test_artifact_detail_returns_structured_content_without_paths(
    media_client: TestClient,
) -> None:
    response = media_client.get(
        "/api/learning-media/artifacts/audio-overview", headers=_headers(media_client)
    )
    assert response.status_code == 200
    assert response.json()["content"]["segments"][0]["chapter"] == "Start"
    assert "file" not in response.json()
    assert "content_file" not in response.json()


def test_tampered_signed_media_url_is_rejected(media_client: TestClient) -> None:
    headers = _headers(media_client)
    url = media_client.get(
        "/api/learning-media/artifacts/audio-overview/access", headers=headers
    ).json()["url"]
    response = media_client.get(url + "x")
    assert response.status_code == 403


def test_learning_media_routes_are_absent_when_disabled(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            llm_provider="mock",
            debug=True,
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'disabled.db'}",
            learning_media_enabled=False,
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/learning-media/catalog").status_code == 404
