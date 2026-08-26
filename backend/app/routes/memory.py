"""Memory API routes: tiers, context window, and checkpoints.

Exposes the memory subsystem to the frontend dashboard.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.memory.checkpoints import CheckpointManager
from app.memory.scoped import MemoryFact, ScopedEncryptedMemoryRepository
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(get_current_user)])

_checkpoint_mgr = CheckpointManager()


def _project_id(
    value: str = Query(
        default="default", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$"
    ),
) -> str:
    return value


def _serialize_fact(fact: MemoryFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "content": fact.content,
        "provenance": dict(fact.provenance),
        "created_at": fact.created_at.isoformat(),
        "updated_at": fact.updated_at.isoformat(),
    }


@router.get("/facts")
async def list_memory_facts(
    request: Request,
    project_id: str = Depends(_project_id),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """List decrypted facts in the authenticated owner/project scope."""
    repository = cast(ScopedEncryptedMemoryRepository | None, request.app.state.scoped_memory)
    if repository is None:
        raise HTTPException(status_code=503, detail="Persistent memory is disabled")
    facts = await repository.list(user["user_id"], project_id)
    return {"project_id": project_id, "facts": [_serialize_fact(fact) for fact in facts]}


@router.get("/export")
async def export_memory_facts(
    request: Request,
    project_id: str = Depends(_project_id),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Export the authenticated owner's decrypted facts and encrypted provenance."""
    repository = cast(ScopedEncryptedMemoryRepository | None, request.app.state.scoped_memory)
    if repository is None:
        raise HTTPException(status_code=503, detail="Persistent memory is disabled")
    facts = await repository.export(user["user_id"], project_id)
    return {"project_id": project_id, "facts": [_serialize_fact(fact) for fact in facts]}


@router.delete("/facts")
async def delete_memory_facts(
    request: Request,
    project_id: str = Depends(_project_id),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Delete every fact in exactly one authenticated owner/project scope."""
    repository = cast(ScopedEncryptedMemoryRepository | None, request.app.state.scoped_memory)
    if repository is None:
        raise HTTPException(status_code=503, detail="Persistent memory is disabled")
    deleted = await repository.delete_all(user["user_id"], project_id)
    return {"project_id": project_id, "deleted": deleted}


@router.get("/tiers")
async def get_memory_tiers() -> dict[str, Any]:
    """Return memory tier descriptions and status.

    The tiers are architectural — we report their design, not live metrics
    (Redis/PG connections are optional and may not be configured).
    """
    return {
        "tiers": [
            {
                "name": "Hot",
                "backend": "Redis",
                "description": "Current conversation context",
                "detail": "Last N messages, 24h TTL",
                "status": "active",
            },
            {
                "name": "Warm",
                "backend": "PostgreSQL",
                "description": "Summarized history, searchable",
                "detail": "Encrypted, indexed",
                "status": "persistent",
            },
            {
                "name": "Cold",
                "backend": "Archive",
                "description": "Full encrypted archives",
                "detail": "Compressed, blob storage",
                "status": "archived",
            },
        ]
    }


@router.get("/context")
async def get_context_window() -> dict[str, Any]:
    """Return context window usage estimate.

    In a real deployment this would reflect the active conversation's
    token budget.  For now we return sensible defaults so the frontend
    renders correctly.
    """
    return {
        "used_tokens": 1840,
        "max_tokens": 4096,
        "segments": [
            {"label": "System prompt", "tokens": 320},
            {"label": "History", "tokens": 1200},
            {"label": "Tools", "tokens": 320},
        ],
    }


@router.get("/checkpoints")
async def list_checkpoints() -> dict[str, Any]:
    """Return all saved checkpoints across conversations."""
    all_cps: list[dict[str, Any]] = []
    for cps in _checkpoint_mgr._checkpoints.values():
        all_cps.extend(cp.to_dict() for cp in cps)
    all_cps.sort(key=lambda c: c["created_at"], reverse=True)
    return {"checkpoints": all_cps}
