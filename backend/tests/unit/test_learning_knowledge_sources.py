"""Source-aware knowledge collection for the Visual Learning tutor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_tutor.sources import (
    LearningSourceInput,
    collect_markdown,
    collect_python,
    collect_video_transcripts,
)


def test_markdown_is_chunked_by_heading_with_exact_lines(tmp_path: Path) -> None:
    path = tmp_path / "concept.md"
    path.write_text(
        "# Application composition\n\nIntro.\n\n## Service slots\n\nA slot starts empty.\n",
        encoding="utf-8",
    )

    sources = collect_markdown(
        path, relative_path="docs/course/concepts/concept.md", revision="a" * 40
    )

    assert [item.title for item in sources] == [
        "Application composition",
        "Application composition — Service slots",
    ]
    assert sources[1].locator["line_start"] == 5
    assert sources[1].locator["line_end"] == 7
    assert sources[1].text == "## Service slots\n\nA slot starts empty."


def test_python_is_chunked_by_symbol_and_preserves_code_lines(tmp_path: Path) -> None:
    path = tmp_path / "main.py"
    path.write_text(
        '"""Module docs."""\n\nVALUE = None\n\n'
        "def create_app():\n    app = object()\n    return app\n",
        encoding="utf-8",
    )

    sources = collect_python(path, relative_path="backend/app/main.py", revision="b" * 40)

    function = next(item for item in sources if item.locator.get("symbol") == "create_app")
    assert function.locator["line_start"] == 5
    assert function.locator["line_end"] == 7
    assert "return app" in function.text
    assert function.kind == "code"


def _catalog(root: Path) -> LearningMediaCatalog:
    target = root / "published" / "code-first" / "video-02"
    target.mkdir(parents=True)
    media = target / "lesson.mp4"
    media.write_bytes(b"video")
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
                        "text": "A service slot starts empty.",
                        "sources": [{"path": "backend/app/main.py", "line_start": 418}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "schema": "cogentrex.learning-library",
        "version": 1,
        "generated_at": "2026-09-12T00:00:00Z",
        "source_commit": "c" * 40,
        "packs": [
            {
                "id": "code-first-series",
                "title": "Code first",
                "purpose": "Learn.",
                "artifacts": [
                    {
                        "id": "code-first-video-02",
                        "type": "video",
                        "title": "Video 2",
                        "status": "review-ready",
                        "language": "en",
                        "file": str(media.relative_to(root)),
                        "media_type": "video/mp4",
                        "sha256": hashlib.sha256(media.read_bytes()).hexdigest(),
                        "source_commit": "c" * 40,
                        "duration_seconds": 679.7,
                        "limitations": ["Review pending."],
                        "content_file": str(transcript.relative_to(root)),
                        "content_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
                    }
                ],
            }
        ],
    }
    (root / "catalog.json").write_text(json.dumps(payload), encoding="utf-8")
    return LearningMediaCatalog(root)


def test_video_transcript_segments_keep_timestamps_and_source_links(tmp_path: Path) -> None:
    sources = collect_video_transcripts(
        _catalog(tmp_path),
        artifact_ids={"code-first-video-02"},
        include_review_ready=True,
    )

    assert len(sources) == 1
    source = sources[0]
    assert source.kind == "video"
    assert source.locator["artifact_id"] == "code-first-video-02"
    assert source.locator["start_seconds"] == 286.94
    assert source.locator["end_seconds"] == 347.156
    assert source.locator["sources"][0]["path"] == "backend/app/main.py"


def test_video_collector_excludes_review_ready_by_default(tmp_path: Path) -> None:
    assert collect_video_transcripts(_catalog(tmp_path), artifact_ids={"code-first-video-02"}) == []


def test_source_id_is_stable_and_does_not_contain_path_data() -> None:
    source = LearningSourceInput(
        kind="documentation",
        key="docs/course/concepts/application-composition.md#service-slots",
        title="Service slots",
        text="A service slot starts empty.",
        revision="d" * 40,
        locator={"path": "docs/course/concepts/application-composition.md"},
    )
    assert source.id == replace(source).id
    assert len(source.id) == 32
    assert "/" not in source.id


def test_collectors_reject_paths_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    with pytest.raises(ValueError, match="relative path"):
        collect_markdown(outside, relative_path="../outside.md", revision="a" * 40)
