# ruff: noqa: B008
"""Owner/project-scoped workspace instruction governance API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.instructions.loaders import (
    InstructionFamily,
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
    family: InstructionFamily = InstructionFamily.ARCHON


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


def _item(row: Any) -> InstructionItem:
    return InstructionItem(
        id=row.id,
        relative_path=".archon/instructions.md",
        scope_path=".",
        revision=row.revision_number,
        content_hash=row.content_hash,
        trust_state=row.review_state,
        byte_count=len(row.content.encode("utf-8")),
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
    return InstructionDetail(**_item(row).model_dump(), content=row.content)


@router.get("/instructions", response_model=list[InstructionItem])
@router.get("/instructions/revisions", response_model=list[InstructionItem])
async def list_instructions(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> list[InstructionItem]:
    await _limit(request, user, "read")
    return [
        _item(x)
        for x in await _repo(request).list_revisions(
            owner_id=user["user_id"], project_id=project_id
        )
    ]


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
    combined = "\n\n".join(f"<!-- {x.relative_path} -->\n{x.content}" for x in sources)
    row = await _repo(request).append(
        owner_id=user["user_id"], project_id=project_id, content=combined, review_state="pending"
    )
    return [
        InstructionItem(
            id=row.id,
            relative_path=x.relative_path,
            scope_path=x.scope_path,
            revision=row.revision_number,
            content_hash=x.content_hash,
            trust_state="pending",
            byte_count=x.byte_count,
        )
        for x in sources
    ]


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
    return _item(row).model_copy(update={"trust_state": "approved"})


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
    row = await _repo(request).current(owner_id=user["user_id"], project_id=project_id)
    if row is None:
        return EffectiveSummary(project_id=project_id, items=[], omitted=[], context_cost_bytes=0)
    from app.instructions.loaders import InstructionSource

    source = InstructionSource.from_content(row.content, ".archon/instructions.md", ".", "archon")
    effective = resolve_effective_context(project_instructions=[source], user_task="")
    return EffectiveSummary(
        project_id=project_id,
        items=[_item(row).model_copy(update={"trust_state": "approved"})],
        omitted=list(effective.omitted),
        context_cost_bytes=effective.context_cost_bytes,
    )
