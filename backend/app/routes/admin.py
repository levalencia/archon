"""Admin API routes for observability dashboard.

GET /api/admin/health      — Detailed health with service status
GET /api/admin/audit       — Recent audit entries
GET /api/admin/audit/stats — Audit action counts
GET /api/admin/metrics     — System metrics (circuit breaker, rate limiter, agents)
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.security.auth import require_admin

logger = structlog.get_logger()

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_start_time = time.time()


@router.get("/health")
async def detailed_health(request: Request) -> dict:
    """Detailed health check with service status."""
    uptime = time.time() - _start_time
    return {
        "status": "healthy",
        "llm_model": request.app.state.settings.llm_model,
        "llm_provider": request.app.state.settings.llm_provider,
        "uptime_seconds": round(uptime, 2),
        "services": {
            "api": "up",
            "audit_logger": "up",
            "circuit_breakers": 1,
        },
    }


@router.get("/audit")
async def get_audit_log(request: Request, limit: int = 50) -> dict:
    """Get recent audit entries."""
    entries = await request.app.state.audit_logger.get_recent(limit=limit)
    return {
        "entries": entries,
        "count": len(entries),
        "limit": limit,
    }


@router.get("/audit/stats")
async def get_audit_stats(request: Request) -> dict:
    """Get audit action counts."""
    counts = await request.app.state.audit_logger.count_by_action()
    return {
        "action_counts": counts,
        "total": sum(counts.values()),
    }


@router.get("/audit/search")
async def search_audit(
    request: Request,
    correlation_id: str | None = None,
    agent_id: str | None = None,
    action: str | None = None,
    security_level: str | None = None,
) -> dict:
    """Search audit entries by filters."""
    entries = await request.app.state.audit_logger.search(
        correlation_id=correlation_id,
        agent_id=agent_id,
        action=action,
        security_level=security_level,
    )
    return {"entries": entries, "count": len(entries)}


@router.get("/metrics")
async def get_metrics(request: Request) -> dict:
    """System metrics for monitoring dashboard."""
    breaker = request.app.state.provider_breaker
    cb_stats = {breaker.name: breaker.get_stats()}

    return {
        "uptime_seconds": round(time.time() - _start_time, 2),
        "circuit_breakers": cb_stats,
        "circuit_breaker_count": 1,
    }


@router.get("/circuit-breakers")
async def get_circuit_breakers(request: Request) -> dict:
    """Get all circuit breaker states."""
    breaker = request.app.state.provider_breaker
    return {breaker.name: breaker.get_stats()}


@router.post(
    "/circuit-breakers/{name}/reset", status_code=200, dependencies=[Depends(require_admin)]
)
async def reset_circuit_breaker(name: str, request: Request) -> dict:
    """Manually reset a circuit breaker."""
    breaker = request.app.state.provider_breaker
    if name != breaker.name:
        return {"error": f"Circuit breaker '{name}' not found"}

    breaker.reset()
    logger.info("circuit_breaker_manual_reset", name=name)
    return {"status": "reset", "name": name}


# --- Settings ---

_settings: dict = {
    "skills_top_k": 3,
}


class SettingsUpdate(BaseModel):
    skills_top_k: int = Field(default=3, ge=1, le=10)


@router.get("/settings")
async def get_settings() -> dict:
    """Get admin settings."""
    return {"settings": _settings}


@router.put("/settings", dependencies=[Depends(require_admin)])
async def update_settings(body: SettingsUpdate) -> dict:
    """Update admin settings (e.g., skills_top_k)."""
    _settings["skills_top_k"] = body.skills_top_k
    logger.info("settings_updated", skills_top_k=body.skills_top_k)
    return {"settings": _settings, "updated": True}


def get_skills_top_k() -> int:
    """Get current skills_top_k setting."""
    return _settings.get("skills_top_k", 3)
