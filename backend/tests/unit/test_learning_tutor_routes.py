"""API contracts for the context-aware Visual Learning tutor."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.learning_tutor.context import LearningContext
from app.learning_tutor.repository import TutorSession
from app.learning_tutor.workflow import LearningTutorResult, TutorCitation
from app.routes.learning_tutor import router
from app.security.auth import get_current_user


class FakeTutor:
    def __init__(self) -> None:
        self.context = LearningContext(
            context_key="artifact:code-first-video-02",
            view="present",
            title="Video 2",
            concept_ids=("application-composition",),
            module_id=None,
            story_id=None,
            step_index=None,
            artifact_id="code-first-video-02",
            playback_seconds=300.0,
            selected_node_id=None,
            selected_edge_id=None,
            source_commit="a" * 40,
            source_references=(),
        )

    async def ask(self, *, question, context_request, owner_id, project_id, correlation_id):
        assert question == "What is a service slot?"
        assert context_request.artifact_id == "code-first-video-02"
        assert owner_id == "alice"
        return LearningTutorResult(
            run_id="run-1",
            session_id="session-1",
            answer_markdown="A service slot starts empty. [E1]",
            citations=(
                TutorCitation(
                    id="E1",
                    kind="code",
                    title="main.py",
                    excerpt="app.state.sandbox_executor = None",
                    score=1.0,
                    source_commit="a" * 40,
                    locator={"path": "backend/app/main.py", "line_start": 418},
                ),
            ),
            related_questions=("When is it populated?",),
            diagram=None,
            grounded=True,
            unsupported=(),
            metrics={"faithfulness_score": 1.0},
        )

    async def history(self, *, session_id, owner_id):
        if owner_id != "alice":
            return None
        return TutorSession(
            id=session_id,
            owner_id=owner_id,
            project_id="default",
            context_key="artifact:code-first-video-02",
            title="Video 2",
            turns=(),
        )


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.learning_tutor = FakeTutor()
    app.state.rate_limiter = SimpleNamespace()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice"}
    return app


def test_tutor_answer_requires_typed_context_and_returns_citations(monkeypatch) -> None:
    async def no_limit(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routes.learning_tutor.enforce_rate_limit", no_limit)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/learning-tutor/answer",
            json={
                "question": "What is a service slot?",
                "project_id": "default",
                "context": {
                    "view": "present",
                    "artifact_id": "code-first-video-02",
                    "playback_seconds": 300.0,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["grounded"] is True
    assert response.json()["citations"][0]["locator"]["line_start"] == 418


def test_tutor_rejects_unknown_context_fields(monkeypatch) -> None:
    async def no_limit(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routes.learning_tutor.enforce_rate_limit", no_limit)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/learning-tutor/answer",
            json={
                "question": "Explain this",
                "context": {
                    "view": "present",
                    "artifact_id": "code-first-video-02",
                    "source_path": "../../.env",
                },
            },
        )
    assert response.status_code == 422


def test_tutor_history_is_owner_scoped(monkeypatch) -> None:
    async def no_limit(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routes.learning_tutor.enforce_rate_limit", no_limit)
    app = _app()
    with TestClient(app) as client:
        response = client.get("/api/learning-tutor/sessions/session-1")
        assert response.status_code == 200
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "bob"}
        denied = client.get("/api/learning-tutor/sessions/session-1")
    assert denied.status_code == 404
