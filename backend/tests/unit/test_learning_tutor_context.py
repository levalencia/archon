"""Contracts for trusted Visual Learning context resolution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_tutor.context import LearningContextRequest, LearningContextResolver


def _media_library(root: Path) -> LearningMediaCatalog:
    target = root / "published" / "code-first" / "video-02"
    target.mkdir(parents=True)
    video = target / "lesson.mp4"
    video.write_bytes(b"video")
    transcript = target / "transcript.json"
    transcript.write_text(
        json.dumps(
            {
                "schema": "cogentrex.video-transcript",
                "version": 1,
                "segments": [
                    {
                        "chapter": "Application state",
                        "speaker": "narrator",
                        "start_seconds": 286.94,
                        "end_seconds": 347.156,
                        "text": (
                            "A service slot starts empty and lifespan later installs the service."
                        ),
                        "sources": [
                            {"path": "backend/app/main.py", "line_start": 418, "line_end": 420}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = {
        "schema": "cogentrex.learning-library",
        "version": 1,
        "generated_at": "2026-09-12T00:00:00Z",
        "source_commit": "a" * 40,
        "packs": [
            {
                "id": "code-first-series",
                "title": "Cogentrex From the Code",
                "purpose": "Learn from code.",
                "artifacts": [
                    {
                        "id": "code-first-video-02",
                        "type": "video",
                        "title": "Video 2",
                        "status": "published",
                        "language": "en",
                        "file": str(video.relative_to(root)),
                        "media_type": "video/mp4",
                        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                        "source_commit": "a" * 40,
                        "duration_seconds": 679.766667,
                        "limitations": ["Derived learning material."],
                        "content_file": str(transcript.relative_to(root)),
                        "content_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
                    }
                ],
            }
        ],
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return LearningMediaCatalog(root)


def _studio(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "cogentrex.visual-learning-studio",
                "version": 3,
                "concepts": [
                    {
                        "id": "application-composition",
                        "title": "Application composition",
                        "summary": "Factories, middleware, routers, and application state.",
                        "sources": [
                            {
                                "path": "backend/app/main.py",
                                "label": "Application factory",
                                "line_start": 391,
                                "line_end": 443,
                            }
                        ],
                        "tests": [],
                        "evidence": [],
                        "limitations": ["Local implementation evidence only."],
                    }
                ],
                "modules": [
                    {
                        "id": "python-architecture",
                        "title": "Python Architecture",
                        "concept_ids": ["application-composition"],
                    }
                ],
                "stories": [],
                "architecture": {"layers": [], "relations": []},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_resolves_video_timestamp_to_authoritative_segment(tmp_path: Path) -> None:
    resolver = LearningContextResolver(
        studio_path=_studio(tmp_path / "studio.json"),
        media_catalog=_media_library(tmp_path / "media"),
    )

    context = resolver.resolve(
        LearningContextRequest(
            view="present",
            artifact_id="code-first-video-02",
            playback_seconds=300.0,
        )
    )

    assert context.title == "Video 2"
    assert context.segment is not None
    assert context.segment.chapter == "Application state"
    assert context.segment.start_seconds == 286.94
    assert context.source_commit == "a" * 40


def test_resolves_concept_and_rejects_client_supplied_unknown_ids(tmp_path: Path) -> None:
    resolver = LearningContextResolver(studio_path=_studio(tmp_path / "studio.json"))

    context = resolver.resolve(
        LearningContextRequest(view="evidence", concept_id="application-composition")
    )
    assert context.context_key == "concept:application-composition"
    assert context.source_references[0]["path"] == "backend/app/main.py"

    with pytest.raises(ValueError, match="Unknown learning concept"):
        resolver.resolve(LearningContextRequest(view="evidence", concept_id="forged"))


def test_rejects_timestamp_outside_declared_video_duration(tmp_path: Path) -> None:
    resolver = LearningContextResolver(
        studio_path=_studio(tmp_path / "studio.json"),
        media_catalog=_media_library(tmp_path / "media"),
    )
    with pytest.raises(ValueError, match="playback position"):
        resolver.resolve(
            LearningContextRequest(
                view="present",
                artifact_id="code-first-video-02",
                playback_seconds=700,
            )
        )


def test_story_and_architecture_selections_keep_page_specific_context(tmp_path: Path) -> None:
    studio_path = _studio(tmp_path / "studio.json")
    payload = json.loads(studio_path.read_text(encoding="utf-8"))
    payload["stories"] = [
        {
            "id": "request-lifecycle",
            "title": "Request lifecycle",
            "steps": [{"title": "Runtime", "concept_ids": ["application-composition"]}],
        }
    ]
    payload["architecture"] = {
        "layers": [
            {
                "components": [
                    {
                        "id": "runtime",
                        "title": "Agent runtime",
                        "concept_ids": ["application-composition"],
                    }
                ]
            }
        ],
        "relations": [],
    }
    studio_path.write_text(json.dumps(payload), encoding="utf-8")
    resolver = LearningContextResolver(studio_path=studio_path)

    story = resolver.resolve(
        LearningContextRequest(
            view="stories",
            story_id="request-lifecycle",
            step_index=0,
            concept_id="application-composition",
        )
    )
    node = resolver.resolve(
        LearningContextRequest(
            view="architecture",
            selected_node_id="runtime",
            concept_id="application-composition",
        )
    )

    assert story.context_key == "story:request-lifecycle:step:0"
    assert node.context_key == "architecture:node:runtime"
    with pytest.raises(ValueError, match="architecture component"):
        resolver.resolve(LearningContextRequest(view="architecture", selected_node_id="forged"))
