# ruff: noqa: B008
"""Owner/project-scoped workspace instruction governance API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.instructions.loaders import (
    InstructionLoadError,
    load_project_instructions,
)
from app.instructions.resolver import resolve_effective_context
from app.security.auth import get_current_user, require_admin
from app.security.dependencies import enforce_rate_limit
from app.skills.persistence import ProjectInstructionRepository

router = APIRouter(prefix="/api/projects/{project_id}", tags=["project-instructions"])
ProjectId = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InstructionCreate(StrictModel):
    content: str = Field(min_length=1, max_length=262144)


class ScanRequest(StrictModel):
    target_path: str = Field(default=".", max_length=1000)
    family: Literal["archon", "agents", "claude"] = "archon"


class InstructionItem(StrictModel):
    id: str
    relative_path: str
    scope_path: str
    revision: int
    content_hash: str
    trust_state: str
    byte_count: int


class InstructionDetail(InstructionItem):
    content: str


class EffectiveSummary(StrictModel):
    project_id: str
    items: list[InstructionItem]
    omitted: list[str]
    context_cost_bytes: int


def _repo(request: Request) -> ProjectInstructionRepository:
    return cast(ProjectInstructionRepository, request.app.state.instruction_repository)


async def _limit(request: Request, user: dict[str, Any], action: str) -> None:
    await enforce_rate_limit(request, user, f"instructions_{action}")


def _item(row: Any, source: Any) -> InstructionItem:
    return InstructionItem(
        id=row.id,
        relative_path=source.relative_path,
        scope_path=source.scope_path,
        revision=row.revision_number,
        content_hash=source.content_hash,
        trust_state=row.review_state,
        byte_count=source.byte_count,
    )


@router.post("/workspace", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, str]:
    await _limit(request, user, "write")
    await _repo(request).ensure_workspace(owner_id=user["user_id"], project_id=project_id)
    return {"project_id": project_id, "status": "ready"}


@router.post("/instructions", response_model=InstructionDetail, status_code=status.HTTP_201_CREATED)
async def create_instruction(
    project_id: ProjectId,
    body: InstructionCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> InstructionDetail:
    await _limit(request, user, "write")
    row = await _repo(request).append(
        owner_id=user["user_id"],
        project_id=project_id,
        content=body.content,
        review_state="pending",
    )
    snapshot = await _repo(request).get_snapshot(
        owner_id=user["user_id"], project_id=project_id, revision_id=row.id
    )
    assert snapshot is not None
    source = snapshot.sources[0]
    return InstructionDetail(**_item(row, source).model_dump(), content=source.content)


@router.get("/instructions", response_model=list[InstructionItem])
@router.get("/instructions/revisions", response_model=list[InstructionItem])
async def list_instructions(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> list[InstructionItem]:
    await _limit(request, user, "read")
    result: list[InstructionItem] = []
    for revision in await _repo(request).list_revisions(
        owner_id=user["user_id"], project_id=project_id
    ):
        snapshot = await _repo(request).get_snapshot(
            owner_id=user["user_id"], project_id=project_id, revision_id=revision.id
        )
        if snapshot is not None:
            result.extend(_item(revision, source) for source in snapshot.sources)
    return result


@router.post("/instructions/scan", response_model=list[InstructionItem])
async def scan(
    project_id: ProjectId,
    body: ScanRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> list[InstructionItem]:
    await _limit(request, user, "scan")
    configured = request.app.state.settings.project_workspace_root
    if not configured:
        raise HTTPException(503, detail={"code": "workspace_scan_disabled"})
    root = (Path(configured).resolve() / user["user_id"] / project_id).resolve()
    try:
        root.relative_to(Path(configured).resolve())
        sources = load_project_instructions(root, body.target_path, family=body.family)
    except (ValueError, OSError, InstructionLoadError):
        raise HTTPException(422, detail={"code": "invalid_workspace_instructions"}) from None
    if not sources:
        return []
    snapshot = await _repo(request).append_sources(
        owner_id=user["user_id"],
        project_id=project_id,
        sources=sources,
        review_state="pending",
    )
    return [_item(snapshot.revision, source) for source in snapshot.sources]


@router.post(
    "/instructions/{revision_id}/approve",
    response_model=InstructionItem,
    dependencies=[Depends(require_admin)],
)
async def approve(
    project_id: ProjectId,
    revision_id: str,
    request: Request,
    owner_id: Annotated[str | None, Query(max_length=255)] = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> InstructionItem:
    await _limit(request, user, "admin")
    row = await _repo(request).set_current(
        owner_id=owner_id or user["user_id"], project_id=project_id, revision_id=revision_id
    )
    if row is None:
        raise HTTPException(404, detail={"code": "instruction_not_found"})
    snapshot = await _repo(request).get_snapshot(
        owner_id=owner_id or user["user_id"], project_id=project_id, revision_id=row.id
    )
    assert snapshot is not None
    return _item(row, snapshot.sources[0])


@router.post("/instructions/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> None:
    await _limit(request, user, "write")
    await _repo(request).set_current(
        owner_id=user["user_id"], project_id=project_id, revision_id=None
    )


@router.get("/instructions/resolve", response_model=EffectiveSummary)
async def resolve(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> EffectiveSummary:
    await _limit(request, user, "read")
    snapshot = await _repo(request).current_snapshot(
        owner_id=user["user_id"], project_id=project_id
    )
    if snapshot is None or snapshot.revision.review_state != "approved":
        return EffectiveSummary(project_id=project_id, items=[], omitted=[], context_cost_bytes=0)
    from app.instructions.loaders import InstructionSource

    sources = tuple(
        InstructionSource.from_content(
            source.content,
            source.relative_path,
            source.scope_path,
            source.family,
            is_override=source.is_override,
        )
        for source in snapshot.sources
    )
    effective = resolve_effective_context(project_instructions=sources, user_task="")
    return EffectiveSummary(
        project_id=project_id,
        items=[_item(snapshot.revision, source) for source in snapshot.sources],
        omitted=list(effective.omitted),
        context_cost_bytes=effective.context_cost_bytes,
    )
