"""Authenticated stored-data replay, fork, and comparison endpoints."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.runtime.run_models import RunEventRecord
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.services.context_snapshots import ContextSnapshotRepository
from app.services.effect_ledger import EffectRepository, EffectReviewConflictError
from app.services.monetary_budget import MonetaryBudgetRepository
from app.services.run_exports import ExportIntegrityError, RunExportService
from app.services.run_ledger import LedgerDataError, RunRepository

router = APIRouter(prefix="/api/runs", tags=["runs"])


class EffectReviewRequest(BaseModel):
    disposition: Literal["confirmed_committed", "confirmed_failed", "requires_compensation"]


class ShareGrantRequest(BaseModel):
    recipient_user_id: str = Field(min_length=1, max_length=255)
    purpose: Literal["audit", "incident_review", "evaluation", "support"]
    expires_in_seconds: int = Field(default=3600, ge=60, le=604800)


def _export_service(request: Request) -> RunExportService:
    return cast(RunExportService, request.app.state.run_exports)


def _effect_repository(request: Request) -> EffectRepository:
    return EffectRepository(request.app.state.conversations.session_factory)


def _budget_repository(request: Request) -> MonetaryBudgetRepository:
    return MonetaryBudgetRepository(request.app.state.conversations.session_factory)


def _usd_string(nusd: int) -> str:
    return format(Decimal(nusd) / Decimal(1_000_000_000), "f")


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
    evidence: list[dict[str, Any]] = []
    for event in events:
        item = {"sequence": event.sequence, "iteration": event.iteration, **event.payload}
        if event.kind == "policy_decided":
            policies.append(item)
        elif event.kind in {"approval_required", "approval_decided"}:
            approvals.append({"kind": event.kind, **item})
        elif event.kind in {"tool_call_requested", "tool_call_completed", "tool_denied"}:
            tools.append({"kind": event.kind, **item})
        elif event.kind in {"evidence_retrieved", "claim_verified", "grounded_answer"}:
            evidence.append({"kind": event.kind, **item})
    return {
        "policy": policies,
        "approvals": approvals,
        "tools": tools,
        "evidence": evidence,
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


@router.post("/{run_id}/exports", status_code=201)
async def create_run_export(
    run_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "run_export")
    result = await _export_service(request).create_export(user["user_id"], run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return asdict(result)


@router.get("/{run_id}/exports")
async def list_run_exports(
    run_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "run_export")
    if await _repository(request).get(user["user_id"], run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    items = await _export_service(request).list_exports(user["user_id"], run_id)
    return {"items": [asdict(item) for item in items]}


@router.get("/{run_id}/exports/{export_id}/download")
async def download_run_export(
    run_id: str,
    export_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> JSONResponse:
    await enforce_rate_limit(request, user, "run_export")
    try:
        bundle = await _export_service(request).download(user["user_id"], export_id)
    except ExportIntegrityError as exc:
        raise HTTPException(status_code=409, detail="Export integrity verification failed") from exc
    if bundle is None or bundle["manifest"]["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Export not found")
    return JSONResponse(
        bundle, headers={"Content-Disposition": f'attachment; filename="run-{run_id}.json"'}
    )


@router.post("/{run_id}/exports/{export_id}/shares", status_code=201)
async def create_share_grant(
    run_id: str,
    export_id: str,
    body: ShareGrantRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "share_create")
    export = await _export_service(request).download(user["user_id"], export_id)
    if export is None or export["manifest"]["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Export not found")
    try:
        created = await _export_service(request).create_grant(
            user["user_id"],
            export_id,
            body.recipient_user_id,
            body.purpose,
            body.expires_in_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created is None:
        raise HTTPException(status_code=404, detail="Export not found")
    grant, token = created
    return {**asdict(grant), "token": token}


@router.get("/{run_id}/exports/{export_id}/shares")
async def list_share_grants(
    run_id: str,
    export_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "share_list")
    export = await _export_service(request).download(user["user_id"], export_id)
    if export is None or export["manifest"]["run_id"] != run_id:
        raise HTTPException(status_code=404, detail="Export not found")
    grants = await _export_service(request).list_grants(user["user_id"], export_id)
    return {"items": [asdict(item) for item in grants or ()]}


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


@router.get("/{run_id}/context")
async def get_run_context(
    run_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    run = await _repository(request).get(user["user_id"], run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    snapshot = await ContextSnapshotRepository(request.app.state.conversations.session_factory).get(
        owner_id=user["user_id"], project_id=run.project_id, run_id=run_id
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Context snapshot not found")
    return {
        "snapshot_id": snapshot.snapshot_id,
        "schema_version": snapshot.schema_version,
        "run_id": snapshot.run_id,
        "conversation_id": snapshot.conversation_id,
        "project_id": snapshot.project_id,
        "selected_message_ids": list(snapshot.selected_message_ids),
        "summarized_message_ids": list(snapshot.summarized_message_ids),
        "memory_ids": list(snapshot.memory_ids),
        "skill_ids": list(snapshot.skill_ids),
        "input_asset_fingerprints": list(snapshot.input_asset_fingerprints),
        "estimated_tokens": snapshot.estimated_tokens,
        "summary_version": snapshot.summary_version,
        "truncation_reason": snapshot.truncation_reason,
        "manifest_hash": snapshot.manifest_hash,
    }


@router.get("/{run_id}/effective-context")
async def get_run_effective_context(
    run_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Return metadata-only provenance matching the inspector contract."""
    await _rate_limit(request, user)
    run = await _repository(request).get(user["user_id"], run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    snapshot = await request.app.state.context_snapshots.get(
        owner_id=user["user_id"], project_id=run.project_id, run_id=run_id
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Context snapshot not found")
    return {
        "run_id": run_id,
        "project_id": run.project_id,
        "manifest_hash": snapshot.manifest_hash,
        "instruction_revisions": [
            {
                "id": item.revision_id,
                "revision": item.revision_id,
                "content_hash": item.content_hash,
                "selection_reason": "approved_current_revision",
            }
            for item in snapshot.instruction_revisions
        ],
        "skill_revisions": [
            {
                "id": item.capability_id,
                "name": item.capability_id,
                "revision": item.revision_id,
                "content_hash": item.content_hash,
                "selection_reason": ",".join(item.reasons) or "selected",
            }
            for item in snapshot.skill_revisions
        ],
        "capabilities": [
            {"id": item, "name": item, "permission": "allow", "reason": "selected"}
            for item in snapshot.selected_capability_ids
        ],
        "context_cost": {
            "estimated_tokens": snapshot.estimated_tokens,
            "byte_count": snapshot.context_cost_bytes,
        },
        "omission_reasons": [
            f"{item}: rejected by policy, relevance, or context budget"
            for item in snapshot.rejected_capability_ids
        ],
    }


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
        budget = await _budget_repository(request).summary(
            owner_id=user["user_id"], project_id=run.project_id, run_id=run_id
        )
        result["monetary_budget"] = (
            None
            if budget is None
            else {
                "limit_usd": _usd_string(budget.run_limit_nusd),
                "spent_usd": _usd_string(budget.run_spent_nusd),
                "reserved_usd": _usd_string(budget.run_reserved_nusd),
                "remaining_usd": _usd_string(
                    budget.run_limit_nusd - budget.run_spent_nusd - budget.run_reserved_nusd
                ),
                "project_limit_usd": _usd_string(budget.project_limit_nusd),
                "project_spent_usd": _usd_string(budget.project_spent_nusd),
                "project_reserved_usd": _usd_string(budget.project_reserved_nusd),
            }
        )
        return result
    except LedgerDataError as exc:
        raise HTTPException(status_code=500, detail="Stored run data is unavailable") from exc


@router.get("/{run_id}/effects")
async def get_run_effects(
    run_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    run = await _repository(request).get(user["user_id"], run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    effects = await _effect_repository(request).list(
        owner_id=user["user_id"],
        project_id=run.project_id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return {"items": [asdict(item) for item in effects], "limit": limit, "offset": offset}


@router.post("/{run_id}/effects/{effect_id}/review")
async def review_run_effect(
    run_id: str,
    effect_id: str,
    body: EffectReviewRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "run_effect_review")
    run = await _repository(request).get(user["user_id"], run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        reviewed = await _effect_repository(request).review_indeterminate(
            effect_id,
            owner_id=user["user_id"],
            project_id=run.project_id,
            run_id=run_id,
            disposition=body.disposition,
            reviewed_by=user["user_id"],
        )
    except EffectReviewConflictError as exc:
        raise HTTPException(status_code=409, detail="Effect is not reviewable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid effect review") from exc
    return asdict(reviewed)


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


@router.get("/{run_id}/children")
async def get_run_children(
    run_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Return only direct children of an owner-visible parent run."""
    await _rate_limit(request, user)
    repository = _repository(request)
    try:
        if await repository.get(user["user_id"], run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        page = await repository.list_children(user["user_id"], run_id, limit=limit, offset=offset)
    except LedgerDataError as exc:
        raise HTTPException(status_code=500, detail="Stored run data is unavailable") from exc
    return {"items": [asdict(item) for item in page.items], "limit": limit, "offset": offset}


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
