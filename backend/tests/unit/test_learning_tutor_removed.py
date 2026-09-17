from __future__ import annotations

from pathlib import Path

from app.main import create_app
from app.services.db_store import Base

ROOT = Path(__file__).parents[3]
TUTOR_TABLES = {
    "learning_sources",
    "learning_chunks",
    "learning_tutor_sessions",
    "learning_tutor_turns",
}


def test_contextual_learning_tutor_product_surface_is_removed() -> None:
    tutor_package = ROOT / "backend/app/learning_tutor"
    assert not tutor_package.exists() or not any(tutor_package.glob("*.py"))
    assert not (ROOT / "backend/app/routes/learning_tutor.py").exists()
    assert not (ROOT / "frontend/src/lib/learning-tutor.ts").exists()
    assert not (ROOT / "frontend/src/lib/components/learning/LearningTutorPanel.svelte").exists()
    assert not (ROOT / "frontend/src/lib/components/learning/TutorDiagram.svelte").exists()


def test_learning_tutor_tables_are_not_part_of_current_orm_metadata() -> None:
    assert TUTOR_TABLES.isdisjoint(Base.metadata.tables)


def test_learning_tutor_route_is_absent() -> None:
    app = create_app()
    assert all(
        not str(getattr(route, "path", "")).startswith("/api/learning-tutor")
        for route in app.routes
    )


def test_visual_learning_and_media_surfaces_remain() -> None:
    required = (
        "backend/app/learning_media/catalog.py",
        "backend/app/routes/learning_media.py",
        "frontend/src/lib/visual-learning.ts",
        "frontend/src/lib/components/learning/VisualLearningStudio.svelte",
        "frontend/src/lib/components/learning/VideoLessonPlayer.svelte",
        "frontend/src/lib/components/learning/AudioLessonPlayer.svelte",
        "frontend/src/lib/components/learning/QuizPlayer.svelte",
        "frontend/src/lib/components/learning/DiagramViewer.svelte",
        "frontend/static/learning/cogentrex-studio.json",
        "schemas/visual-learning/learning-library.schema.json",
    )
    assert all((ROOT / path).exists() for path in required)
