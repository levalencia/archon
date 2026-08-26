"""Skills management API: list, search, import from GitHub, delete.

GET    /api/skills              — List all registered skills
POST   /api/skills/search       — Search skills by keyword
POST   /api/skills/import       — Import a skill from a GitHub repo
DELETE /api/skills/{name}       — Remove a skill
GET    /api/skills/{name}       — Get full skill content
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.observability.logging import safe_value_metadata
from app.security.auth import get_current_user, require_admin
from app.skills.registry import Skill, SkillRegistry, create_default_skills

logger = structlog.get_logger()

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[Depends(get_current_user)])

# Module-level registry (shared with chat routes)
_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get or create the shared skill registry."""
    global _registry
    if _registry is None:
        _registry = create_default_skills()
    return _registry


class SkillSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class SkillImportRequest(BaseModel):
    repo: str = Field(
        ...,
        min_length=3,
        description="GitHub repo in 'owner/repo' format",
        examples=["mattpocock/skills"],
    )
    path: str = Field(
        default="SKILL.md",
        description="Path to SKILL.md in the repo",
    )
    branch: str = Field(default="main")


class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class SkillResponse(BaseModel):
    name: str
    description: str
    source_url: str = ""
    tags: list[str] = []
    content_length: int = 0


class SkillDetailResponse(BaseModel):
    name: str
    description: str
    content: str
    source_url: str = ""
    tags: list[str] = []


@router.get("", response_model=list[SkillResponse])
async def list_skills() -> list[SkillResponse]:
    """List all registered skills."""
    registry = get_skill_registry()
    return [SkillResponse(**s) for s in registry.list_all()]


@router.get("/{name}", response_model=SkillDetailResponse)
async def get_skill(name: str) -> SkillDetailResponse | dict:
    """Get full skill content by name."""
    registry = get_skill_registry()
    skill = registry.get(name)
    if not skill:
        return {"error": f"Skill '{name}' not found"}
    return SkillDetailResponse(
        name=skill.name,
        description=skill.description,
        content=skill.content,
        source_url=skill.source_url,
        tags=skill.tags,
    )


@router.post("/search", response_model=list[SkillResponse])
async def search_skills(body: SkillSearchRequest) -> list[SkillResponse]:
    """Search skills by keyword."""
    registry = get_skill_registry()
    results = registry.search(body.query, limit=body.limit)
    return [
        SkillResponse(
            name=s.name,
            description=s.description,
            source_url=s.source_url,
            tags=s.tags,
            content_length=len(s.content),
        )
        for s in results
    ]


@router.post(
    "/import",
    response_model=SkillResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def import_skill(body: SkillImportRequest) -> SkillResponse | dict:
    """Import a skill from a GitHub repository.

    Example: repo='mattpocock/skills', path='skills/engineering/tdd/SKILL.md'
    """
    registry = get_skill_registry()

    logger.info(
        "skill_import_started",
        **safe_value_metadata("repo", body.repo),
        **safe_value_metadata("path", body.path),
        **safe_value_metadata("branch", body.branch),
    )

    skill = await registry.load_from_github(
        repo=body.repo,
        path=body.path,
        branch=body.branch,
    )

    if not skill:
        return {"error": f"Failed to import from {body.repo}/{body.path}"}

    logger.info(
        "skill_imported",
        **safe_value_metadata("name", skill.name),
        **safe_value_metadata("repo", body.repo),
        content_length=len(skill.content),
    )

    return SkillResponse(
        name=skill.name,
        description=skill.description,
        source_url=skill.source_url,
        tags=skill.tags,
        content_length=len(skill.content),
    )


@router.post(
    "", response_model=SkillResponse, status_code=201, dependencies=[Depends(require_admin)]
)
async def create_skill(body: SkillCreateRequest) -> SkillResponse:
    """Create a custom skill manually."""
    registry = get_skill_registry()

    skill = Skill(
        name=body.name,
        description=body.description,
        content=body.content,
        tags=body.tags,
    )
    registry.register(skill)

    return SkillResponse(
        name=skill.name,
        description=skill.description,
        tags=skill.tags,
        content_length=len(skill.content),
    )


@router.delete("/{name}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_skill(name: str) -> None:
    """Remove a skill from the registry."""
    registry = get_skill_registry()
    if registry.get(name):
        registry._skills.pop(name, None)
        logger.info("skill_deleted", name=name)
