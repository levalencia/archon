"""Authenticated API for context-aware Visual Learning questions."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.learning_tutor.context import LearningContextRequest
from app.learning_tutor.service import LearningTutorService
from app.observability.logging import get_correlation_id
from app.security.auth import get_current_user
from app.security.compliance import ComplianceViolationError
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/learning-tutor", tags=["learning-tutor"])


class TutorQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, max_length=5000)
    project_id: str = Field(
        default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    )
    context: LearningContextRequest


def _service(request: Request) -> LearningTutorService:
    service = getattr(request.app.state, "learning_tutor", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Learning tutor is unavailable")
    return cast(LearningTutorService, service)


@router.post("/answer")
async def answer_learning_question(
    body: TutorQuestionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "learning_tutor_answer")
    compliance = getattr(request.app.state, "compliance", None)
    if compliance is not None:
        try:
            compliance.enforce_input(body.question)
        except ComplianceViolationError as exc:
            raise HTTPException(status_code=422, detail="Question rejected by policy") from exc
    try:
        result = await _service(request).ask(
            question=body.question,
            context_request=body.context,
            owner_id=str(user["user_id"]),
            project_id=body.project_id,
            correlation_id=get_correlation_id() or "learning-tutor",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = result.public()
    if compliance is not None:
        payload = cast(dict[str, Any], compliance.enforce_payload(payload))
    return payload


@router.get("/sessions/{session_id}")
async def learning_tutor_history(
    session_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "learning_tutor_history")
    session = await _service(request).history(session_id=session_id, owner_id=str(user["user_id"]))
    if session is None:
        raise HTTPException(status_code=404, detail="Learning tutor session not found")
    return {
        "id": session.id,
        "project_id": session.project_id,
        "context_key": session.context_key,
        "title": session.title,
        "turns": [
            {
                "id": turn.id,
                "question": turn.question,
                "answer_markdown": turn.answer,
                "context": turn.context,
                "citations": turn.evidence,
                "diagram": turn.diagram,
                "metrics": turn.metrics,
                "created_at": turn.created_at.isoformat(),
            }
            for turn in session.turns
        ],
    }
