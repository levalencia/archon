"""Contracts for the published learning-media library."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_media.paths import resolve_published_file
from app.learning_media.signatures import sign_media_token, verify_media_token
from app.learning_media.streaming import parse_byte_range


def _write_library(root: Path) -> tuple[Path, str]:
    published = root / "published" / "request-lifecycle" / "audio-overview"
    published.mkdir(parents=True)
    media = published / "lesson.mp3"
    media.write_bytes(b"0123456789")
    checksum = hashlib.sha256(media.read_bytes()).hexdigest()
    catalog = {
        "schema": "archon.learning-library",
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
                        "sha256": checksum,
                        "source_commit": "a" * 40,
                        "limitations": ["Derived learning material, not canonical evidence."],
                    }
                ],
            }
        ],
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return media, checksum


def test_catalog_loads_only_valid_published_artifacts(tmp_path: Path) -> None:
    media, checksum = _write_library(tmp_path)

    catalog = LearningMediaCatalog(tmp_path)
    payload = catalog.public_catalog()

    assert payload["schema"] == "archon.learning-library"
    artifact = payload["packs"][0]["artifacts"][0]
    assert artifact["id"] == "audio-overview"
    assert artifact["sha256"] == checksum
    assert "file" not in artifact
    assert catalog.artifact("audio-overview").path == media.resolve()


def test_catalog_rejects_checksum_mismatch(tmp_path: Path) -> None:
    media, _ = _write_library(tmp_path)
    media.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="checksum"):
        LearningMediaCatalog(tmp_path)


def test_catalog_rejects_mime_mismatch(tmp_path: Path) -> None:
    _write_library(tmp_path)
    catalog_path = tmp_path / "catalog.json"
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    payload["packs"][0]["artifacts"][0]["media_type"] = "text/html"
    catalog_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="media type"):
        LearningMediaCatalog(tmp_path)


def test_published_paths_reject_traversal_and_symlinks(tmp_path: Path) -> None:
    media, _ = _write_library(tmp_path)
    assert (
        resolve_published_file(tmp_path, "published/request-lifecycle/audio-overview/lesson.mp3")
        == media.resolve()
    )

    with pytest.raises(ValueError):
        resolve_published_file(tmp_path, "../outside.mp3")

    link = tmp_path / "published" / "request-lifecycle" / "audio-overview" / "linked.mp3"
    link.symlink_to(media)
    with pytest.raises(ValueError):
        resolve_published_file(tmp_path, str(link.relative_to(tmp_path)))


def test_signed_media_tokens_detect_tampering_and_expiry() -> None:
    token = sign_media_token(
        "secret", artifact_id="audio-overview", checksum="a" * 64, expires_at=2_000
    )
    assert verify_media_token("secret", token, now=1_999) == {
        "artifact_id": "audio-overview",
        "checksum": "a" * 64,
        "expires_at": 2_000,
    }
    assert verify_media_token("secret", token + "x", now=1_999) is None
    assert verify_media_token("secret", token, now=2_000) is None


def test_byte_range_parser_handles_full_partial_suffix_and_invalid_ranges() -> None:
    assert parse_byte_range(None, 10) == (0, 9, False)
    assert parse_byte_range("bytes=2-5", 10) == (2, 5, True)
    assert parse_byte_range("bytes=7-", 10) == (7, 9, True)
    assert parse_byte_range("bytes=-3", 10) == (7, 9, True)
    with pytest.raises(ValueError):
        parse_byte_range("bytes=10-11", 10)
    with pytest.raises(ValueError):
        parse_byte_range("items=0-1", 10)
    with pytest.raises(ValueError):
        parse_byte_range("bytes=0-1,4-5", 10)
