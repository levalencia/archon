# ruff: noqa: B008
"""Durable owner/project-scoped skill catalog and governance API."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.security.auth import get_current_user, require_admin
from app.security.dependencies import enforce_rate_limit
from app.skills.bundled import ARCHON_OWNER_ID
from app.skills.installer import PinnedSkillSource, SkillInstallationService, SkillSourceError
from app.skills.parser import parse_skill_markdown
from app.skills.persistence import SkillNotFoundError, SkillRepository
from app.skills.registry import SkillRegistry, create_default_skills

router = APIRouter(prefix="/api/skills", tags=["skills"])


def get_skill_registry() -> SkillRegistry:
    """Compatibility adapter returning a fresh immutable built-in catalog."""
    return create_default_skills()


ProjectId = Annotated[
    str, Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CatalogItem(StrictModel):
    id: str
    revision_id: str | None = None
    revision_owner_id: str | None = None
    name: str
    description: str
    kind: str = "skill"
    source: str
    version: str
    trust_state: str
    enabled: bool
    pinned: bool
    risk_classes: list[str]


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    project_id: ProjectId | None = None
    limit: int = Field(default=20, ge=1, le=100)


class InstallRequest(StrictModel):
    repository: str = Field(min_length=3, max_length=255)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    path: str = Field(default="SKILL.md", min_length=1, max_length=500)


class SkillCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    description: str = Field(min_length=1, max_length=2000)
    content: str = Field(min_length=1, max_length=262144)
    tags: list[str] = Field(default_factory=list, max_length=64)


class BindingRequest(StrictModel):
    revision_id: str = Field(min_length=1, max_length=64)
    revision_owner_id: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool = True
    pinned: bool = True


class ReviewRequest(StrictModel):
    owner_id: str = Field(min_length=1, max_length=255)


async def _limit(request: Request, user: dict[str, Any], action: str) -> None:
    await enforce_rate_limit(request, user, f"skills_{action}")


def _repo(request: Request) -> SkillRepository:
    return cast(SkillRepository, request.app.state.skill_repository)


async def _items(
    request: Request, owner_id: str, project_id: str | None = None, query: str = ""
) -> list[CatalogItem]:
    catalogs = [
        *(await _repo(request).list_catalog(owner_id=owner_id, query=query)),
        *(await _repo(request).list_catalog(owner_id=ARCHON_OWNER_ID, query=query)),
    ]
    selected_revision_ids = (
        set()
        if project_id is None
        else set(await _repo(request).list_pin_ids(owner_id=owner_id, project_id=project_id))
    )
    result: list[CatalogItem] = []
    for package, revision in catalogs:
        enabled = revision.id in selected_revision_ids
        result.append(
            CatalogItem(
                id=package.id,
                revision_id=revision.id,
                revision_owner_id=revision.owner_id,
                name=package.name,
                description=revision.description,
                source=revision.source_url,
                version=revision.declared_version,
                trust_state=revision.review_state,
                enabled=enabled,
                pinned=enabled,
                risk_classes=["read"],
            )
        )
    return sorted(result, key=lambda item: (item.name, item.revision_owner_id or ""))


@router.get("", response_model=list[CatalogItem])
@router.get("/catalog", response_model=list[CatalogItem])
async def catalog(
    request: Request,
    project_id: ProjectId | None = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> list[CatalogItem]:
    await _limit(request, user, "read")
    return await _items(request, user["user_id"], project_id)


@router.post("/search", response_model=list[CatalogItem])
async def search(
    body: SearchRequest, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> list[CatalogItem]:
    await _limit(request, user, "search")
    return (await _items(request, user["user_id"], body.project_id, body.query))[: body.limit]


@router.post(
    "",
    response_model=CatalogItem,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_skill(
    body: SkillCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> CatalogItem:
    await _limit(request, user, "admin")
    markdown = (
        f"---\nname: {body.name}\ndescription: {body.description}\n"
        f"version: 1\ntags: [{', '.join(body.tags)}]\n---\n{body.content}"
    )
    parsed = parse_skill_markdown(markdown.encode("utf-8"))
    installed = await _repo(request).install(
        owner_id=user["user_id"],
        parsed=parsed,
        source_url="managed",
        source_revision="managed",
        trust_state="verified",
        review_state="approved",
    )
    row = await _repo(request).get_revision(
        owner_id=user["user_id"],
        package_id=installed.package_id,
        revision_id=installed.revision_id,
    )
    return CatalogItem(
        id=installed.package_id,
        name=body.name,
        description=row.description,
        source="managed",
        version=row.declared_version,
        trust_state=row.review_state,
        enabled=False,
        pinned=False,
        risk_classes=["read"],
    )


@router.post("/install-requests", response_model=CatalogItem, status_code=status.HTTP_202_ACCEPTED)
async def install(
    body: InstallRequest, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> CatalogItem:
    await _limit(request, user, "install")
    try:
        installed = await cast(SkillInstallationService, request.app.state.skill_installer).install(
            owner_id=user["user_id"],
            source=PinnedSkillSource(body.repository, body.revision, body.path),
        )
        row = await _repo(request).get_revision(
            owner_id=user["user_id"],
            package_id=installed.package_id,
            revision_id=installed.revision_id,
        )
    except SkillSourceError as error:
        raise HTTPException(422, detail={"code": str(error)}) from None
    return CatalogItem(
        id=installed.package_id,
        name=next(
            package.name
            for package, _ in await _repo(request).list_catalog(owner_id=user["user_id"])
            if package.id == installed.package_id
        ),
        description=row.description,
        source=row.source_url,
        version=row.declared_version,
        trust_state=row.review_state,
        enabled=False,
        pinned=False,
        risk_classes=["read"],
    )


@router.post(
    "/{package_id}/revisions/{revision_id}/approve",
    response_model=CatalogItem,
    dependencies=[Depends(require_admin)],
)
async def approve(
    package_id: str,
    revision_id: str,
    body: ReviewRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> CatalogItem:
    await _limit(request, user, "admin")
    try:
        row = await _repo(request).set_review_state(
            owner_id=body.owner_id,
            package_id=package_id,
            revision_id=revision_id,
            review_state="approved",
        )
    except SkillNotFoundError:
        raise HTTPException(404, detail={"code": "skill_not_found"}) from None
    package = next(
        p
        for p, r in await _repo(request).list_catalog(owner_id=body.owner_id)
        if p.id == package_id
    )
    return CatalogItem(
        id=package.id,
        name=package.name,
        description=row.description,
        source=row.source_url,
        version=row.declared_version,
        trust_state=row.review_state,
        enabled=False,
        pinned=False,
        risk_classes=["read"],
    )


@router.post(
    "/{package_id}/revisions/{revision_id}/revoke",
    response_model=CatalogItem,
    dependencies=[Depends(require_admin)],
)
async def revoke(
    package_id: str,
    revision_id: str,
    body: ReviewRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> CatalogItem:
    await _limit(request, user, "admin")
    try:
        row = await _repo(request).set_review_state(
            owner_id=body.owner_id,
            package_id=package_id,
            revision_id=revision_id,
            review_state="rejected",
        )
    except SkillNotFoundError:
        raise HTTPException(404, detail={"code": "skill_not_found"}) from None
    package = next(
        p
        for p, r in await _repo(request).list_catalog(owner_id=body.owner_id)
        if p.id == package_id
    )
    return CatalogItem(
        id=package.id,
        name=package.name,
        description=row.description,
        source=row.source_url,
        version=row.declared_version,
        trust_state=row.review_state,
        enabled=False,
        pinned=False,
        risk_classes=["read"],
    )


@router.put("/projects/{project_id}/{package_id}", response_model=CatalogItem)
async def bind(
    project_id: ProjectId,
    package_id: str,
    body: BindingRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> CatalogItem:
    await _limit(request, user, "write")
    revision_owner_id = body.revision_owner_id or user["user_id"]
    if revision_owner_id not in {user["user_id"], ARCHON_OWNER_ID}:
        raise HTTPException(403, detail={"code": "skill_owner_forbidden"})
    try:
        revision = await _repo(request).get_revision(
            owner_id=revision_owner_id,
            package_id=package_id,
            revision_id=body.revision_id,
        )
        if revision.review_state != "approved" and body.enabled:
            raise HTTPException(409, detail={"code": "skill_not_approved"})
        if revision_owner_id == ARCHON_OWNER_ID and revision.trust_state != "verified":
            raise HTTPException(409, detail={"code": "bundled_skill_not_verified"})
        await _repo(request).bind(
            owner_id=user["user_id"],
            project_id=project_id,
            package_id=package_id,
            revision_id=body.revision_id,
            revision_owner_id=revision_owner_id,
            enabled=body.enabled,
        )
    except SkillNotFoundError:
        raise HTTPException(404, detail={"code": "skill_not_found"}) from None
    return next(x for x in await _items(request, user["user_id"], project_id) if x.id == package_id)


@router.get("/projects/{project_id}/effective", response_model=dict[str, Any])
async def effective(
    project_id: ProjectId, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    await _limit(request, user, "read")
    items = await _items(request, user["user_id"], project_id)
    enabled = [x for x in items if x.enabled]
    return {
        "project_id": project_id,
        "items": enabled,
        "summary": {
            "enabled": len(enabled),
            "pinned": sum(x.pinned for x in enabled),
            "context_cost_bytes": 0,
        },
    }
