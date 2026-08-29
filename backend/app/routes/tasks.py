"""Authenticated owner-isolated durable background-job APIs."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.services.task_queue import DurableJobQueue, InvalidJob

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["echo", "run_export"]
    project_id: str = Field(default="default", min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)
    max_attempts: int = Field(default=3, ge=1, le=10)


def _queue(request: Request) -> DurableJobQueue:
    return cast(DurableJobQueue, request.app.state.job_queue)


@router.post("", status_code=status.HTTP_201_CREATED)
@router.post("/submit", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_job(
    body: JobCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "task_submit")
    try:
        return await _queue(request).create(
            user["user_id"],
            body.project_id,
            body.kind,
            body.payload,
            idempotency_key=body.idempotency_key,
            max_attempts=body.max_attempts,
        )
    except InvalidJob as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
async def list_jobs(
    request: Request,
    project_id: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "task_list")
    items = await _queue(request).list(
        user["user_id"], project_id=project_id, limit=limit, offset=offset
    )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    project_id: str = Query(..., min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "task_status")
    item = await _queue(request).get(user["user_id"], project_id, job_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return item


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    request: Request,
    project_id: str = Query(..., min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, str]:
    await enforce_rate_limit(request, user, "task_cancel")
    if not await _queue(request).cancel(user["user_id"], project_id, job_id):
        raise HTTPException(status_code=404, detail="Cancellable job not found")
    return {"job_id": job_id, "status": "cancelled"}


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: str,
    request: Request,
    project_id: str = Query(..., min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, str]:
    await enforce_rate_limit(request, user, "task_retry")
    if not await _queue(request).retry(user["user_id"], project_id, job_id):
        raise HTTPException(status_code=404, detail="Retryable job not found")
    return {"job_id": job_id, "status": "pending"}
