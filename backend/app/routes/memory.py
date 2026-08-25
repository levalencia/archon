"""Memory API routes: tiers, context window, and checkpoints.

Exposes the memory subsystem to the frontend dashboard.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.memory.checkpoints import CheckpointManager
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(get_current_user)])

_checkpoint_mgr = CheckpointManager()


@router.get("/tiers")
async def get_memory_tiers() -> dict:
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
async def get_context_window() -> dict:
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
async def list_checkpoints() -> dict:
    """Return all saved checkpoints across conversations."""
    all_cps: list[dict] = []
    for cps in _checkpoint_mgr._checkpoints.values():
        all_cps.extend(cp.to_dict() for cp in cps)
    all_cps.sort(key=lambda c: c["created_at"], reverse=True)
    return {"checkpoints": all_cps}
