"""Authenticated stored-data replay, fork, and comparison endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.runtime.run_models import RunEventRecord
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.services.run_ledger import LedgerDataError, RunRepository

router = APIRouter(prefix="/api/runs", tags=["runs"])


class ForkRequest(BaseModel):
    source_sequence: int = Field(ge=1)
    policy_profile: str = Field(default="default", min_length=1, max_length=100)
    selected_memory_ids: list[str] = Field(default_factory=list, max_length=100)


def _repository(request: Request) -> RunRepository:
    return cast(RunRepository, request.app.state.conversations.runs)


def _trajectory(events: tuple[RunEventRecord, ...], run: dict[str, Any]) -> dict[str, Any]:
    policies: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    for event in events:
        item = {"sequence": event.sequence, "iteration": event.iteration, **event.payload}
        if event.kind == "policy_decided":
            policies.append(item)
        elif event.kind in {"approval_required", "approval_decided"}:
            approvals.append({"kind": event.kind, **item})
        elif event.kind in {"tool_call_requested", "tool_call_completed", "tool_denied"}:
            tools.append({"kind": event.kind, **item})
    return {
        "policy": policies,
        "approvals": approvals,
        "tools": tools,
        "evidence": [],
        "tokens": {
            "input": run["input_tokens"],
            "output": run["output_tokens"],
            "total": run["total_tokens"],
        },
        "cost_usd": run["cost_usd"],
        "latency_ms": run["latency_ms"],
        "iterations": run["iterations"],
        "stop_reason": run["stop_reason"],
        "workspace_restoration": "none",
        "memory_ids": [],
        "context_ids": [],
    }


async def _rate_limit(request: Request, user: dict[str, Any]) -> None:
    await enforce_rate_limit(request, user, "run_read")


@router.get("")
async def list_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conversation_id: str | None = Query(default=None, max_length=255),
    project_id: str | None = Query(default=None, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    try:
        page = await _repository(request).list(
            user["user_id"],
            limit=limit,
            offset=offset,
            conversation_id=conversation_id,
            project_id=project_id,
        )
    except LedgerDataError as exc:
        raise HTTPException(status_code=500, detail="Stored run data is unavailable") from exc
    return {"items": [asdict(item) for item in page.items], "limit": limit, "offset": offset}


@router.get("/compare")
async def compare_runs(
    request: Request,
    a: str = Query(min_length=1),
    b: str = Query(min_length=1),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Deterministically compare stored safe fields without model or tool access."""
    await _rate_limit(request, user)
    repository = _repository(request)
    left, right = await repository.get(user["user_id"], a), await repository.get(user["user_id"], b)
    if left is None or right is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def view(run: Any) -> dict[str, Any]:
        page = await repository.events(user["user_id"], run.run_id, limit=200)
        if page is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raw = asdict(run)
        trajectory = _trajectory(page.items, raw)
        return {
            "run_id": run.run_id,
            "conversation_id": run.conversation_id,
            "project_id": run.project_id,
            "answer_summary": run.answer_summary,
            "provider": run.provider,
            "model": run.model,
            "schema_version": run.schema_version,
            "settings": None,
            "tools": trajectory["tools"],
            "approvals": trajectory["approvals"],
            "policy": trajectory["policy"],
            "evidence": trajectory["evidence"],
            "tokens": trajectory["tokens"],
            "cost_usd": run.cost_usd,
            "latency_ms": run.latency_ms,
            "iterations": run.iterations,
            "stop_reason": run.stop_reason,
            "memory_ids": [],
            "context_ids": [],
            "parent_run_id": run.parent_run_id,
            "fork_source_sequence": run.fork_source_sequence,
        }

    return {"a": await view(left), "b": await view(right)}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    repository = _repository(request)
    try:
        run = await repository.get(user["user_id"], run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        events = await repository.events(user["user_id"], run_id, limit=200)
        if events is None:
            raise HTTPException(status_code=404, detail="Run not found")
        result = asdict(run)
        result["trajectory"] = _trajectory(events.items, result)
        return result
    except LedgerDataError as exc:
        raise HTTPException(status_code=500, detail="Stored run data is unavailable") from exc


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    after_sequence: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    try:
        page = await _repository(request).events(
            user["user_id"], run_id, limit=limit, after_sequence=after_sequence
        )
    except LedgerDataError as exc:
        raise HTTPException(status_code=500, detail="Stored run data is unavailable") from exc
    if page is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "items": [asdict(item) for item in page.items],
        "limit": limit,
        "after_sequence": after_sequence,
    }


@router.post("/{run_id}/fork", status_code=201)
async def fork_run(
    run_id: str,
    body: ForkRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    try:
        fork = await _repository(request).fork(
            user["user_id"],
            run_id,
            body.source_sequence,
            policy_profile=body.policy_profile,
            selected_memory_ids=tuple(body.selected_memory_ids),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Run event not found") from exc
    if fork is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return fork
