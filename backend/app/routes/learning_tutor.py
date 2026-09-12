"""Authenticated API for context-aware Visual Learning questions."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from app.learning_tutor.context import LearningContextRequest
from app.learning_tutor.service import LearningTutorService
from app.observability.logging import get_correlation_id
from app.security.auth import get_current_user
from app.security.compliance import ComplianceViolationError
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/learning-tutor", tags=["learning-tutor"])

_CHUNK_SIZE = 80  # characters per answer_delta chunk


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


def _sse(event: str, data: Any) -> str:
    """Format a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/answer/stream")
async def stream_learning_answer(
    body: TutorQuestionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> StreamingResponse:
    """SSE stream that delivers verified tutor answer in incremental chunks.

    Event protocol:
      status   – immediate acknowledgement with run metadata
      progress – retrieval/verification milestones
      : heartbeat – keep-alive comment every 5 s while workflow runs
      answer_delta – verified answer text chunk (only from final grounded answer)
      result   – full verified payload identical to POST /answer JSON
      done     – terminal event, close the connection
      error    – on any failure
    """
    await enforce_rate_limit(request, user, "learning_tutor_answer")
    compliance = getattr(request.app.state, "compliance", None)
    if compliance is not None:
        try:
            compliance.enforce_input(body.question)
        except ComplianceViolationError as exc:
            raise HTTPException(status_code=422, detail="Question rejected by policy") from exc

    service = _service(request)
    run_id = str(uuid.uuid4())

    async def event_stream() -> AsyncIterator[str]:
        # Immediate status event
        yield _sse(
            "status",
            {
                "run_id": run_id,
                "phase": "started",
                "message": "Retrieving evidence for your question…",
            },
        )

        # Run the full grounded workflow in a task so we can heartbeat
        result_future: asyncio.Task[Any] = asyncio.create_task(
            service.ask(
                question=body.question,
                context_request=body.context,
                owner_id=str(user["user_id"]),
                project_id=body.project_id,
                correlation_id=get_correlation_id() or "learning-tutor",
            )
        )

        yield _sse(
            "progress",
            {
                "run_id": run_id,
                "phase": "retrieving",
                "message": "Searching indexed learning sources…",
            },
        )

        # Heartbeat while waiting for the workflow
        try:
            while not result_future.done():
                try:
                    await asyncio.wait_for(asyncio.shield(result_future), timeout=5.0)
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if not result_future.done():
                result_future.cancel()
                with suppress(asyncio.CancelledError):
                    await result_future

        try:
            result = result_future.result()
        except ValueError:
            yield _sse(
                "error",
                {"run_id": run_id, "message": "The learning context could not be resolved."},
            )
            yield _sse("done", {"run_id": run_id})
            return
        except Exception:
            yield _sse(
                "error",
                {"run_id": run_id, "message": "The learning tutor encountered an error."},
            )
            yield _sse("done", {"run_id": run_id})
            return

        yield _sse(
            "progress",
            {
                "run_id": run_id,
                "phase": "verified",
                "message": "Evidence verified. Streaming answer…",
            },
        )

        # Stream verified answer in chunks — only the final grounded text
        payload = result.public()
        if compliance is not None:
            payload = cast(dict[str, Any], compliance.enforce_payload(payload))

        answer = payload.get("answer_markdown", "")
        offset = 0
        chunk_index = 0
        while offset < len(answer):
            end = min(offset + _CHUNK_SIZE, len(answer))
            yield _sse(
                "answer_delta",
                {
                    "run_id": run_id,
                    "index": chunk_index,
                    "delta": answer[offset:end],
                },
            )
            chunk_index += 1
            offset = end

        # Full authoritative result
        yield _sse("result", payload)
        yield _sse("done", {"run_id": run_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
