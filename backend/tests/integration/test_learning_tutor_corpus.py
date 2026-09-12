"""Integration coverage for the real repository and Video 1/2 learning corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_tutor.indexer import collect_learning_corpus

ROOT = Path(__file__).parents[3]
MEDIA = Path("/Users/luisvalencia/Documents/cogentrex-learning-media")
pytestmark = pytest.mark.skipif(
    not (MEDIA / "catalog.json").is_file(),
    reason="local reviewed learning-media library is unavailable",
)


def test_real_learning_corpus_contains_canonical_docs_code_tests_and_videos() -> None:
    catalog = LearningMediaCatalog(MEDIA)
    sources = collect_learning_corpus(
        repository_root=ROOT,
        studio_path=ROOT / "frontend/static/learning/cogentrex-studio.json",
        revision="working-tree:" + "a" * 16,
        media_catalog=catalog,
        video_artifact_ids={"code-first-video-01", "code-first-video-02"},
        include_review_ready=True,
    )

    assert any(
        item.locator.get("path") == "docs/course/concepts/application-composition.md"
        for item in sources
    )
    assert any(
        item.locator.get("path") == "backend/app/main.py"
        and item.locator.get("symbol") == "create_app"
        for item in sources
    )
    assert any(
        item.kind == "test" and item.locator.get("path", "").endswith("test_health.py")
        for item in sources
    )
    videos = [item for item in sources if item.kind == "video"]
    assert {item.locator["artifact_id"] for item in videos} == {
        "code-first-video-01",
        "code-first-video-02",
    }
    assert any("service slot" in item.text.lower() for item in videos)
    assert len(sources) == len({item.id for item in sources})
