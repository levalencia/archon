"""Admin API routes for observability dashboard.

GET /api/admin/health      — Detailed health with service status
GET /api/admin/audit       — Recent audit entries
GET /api/admin/audit/stats — Audit action counts
GET /api/admin/metrics     — System metrics (circuit breaker, rate limiter, agents)
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter

from app.security.audit_logger import StructuredAuditLogger
from app.security.circuit_breaker import CircuitBreaker

logger = structlog.get_logger()

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Module-level instances (will be replaced by DI)
_audit_logger = StructuredAuditLogger()
_circuit_breakers: dict[str, CircuitBreaker] = {}
_start_time = time.time()


@router.get("/health")
async def detailed_health() -> dict:
    """Detailed health check with service status."""
    uptime = time.time() - _start_time
    return {
        "status": "healthy",
        "uptime_seconds": round(uptime, 2),
        "services": {
            "api": "up",
            "audit_logger": "up",
            "circuit_breakers": len(_circuit_breakers),
        },
    }


@router.get("/audit")
async def get_audit_log(limit: int = 50) -> dict:
    """Get recent audit entries."""
    entries = await _audit_logger.get_recent(limit=limit)
    return {
        "entries": entries,
        "count": len(entries),
        "limit": limit,
    }


@router.get("/audit/stats")
async def get_audit_stats() -> dict:
    """Get audit action counts."""
    counts = await _audit_logger.count_by_action()
    return {
        "action_counts": counts,
        "total": sum(counts.values()),
    }


@router.get("/audit/search")
async def search_audit(
    correlation_id: str | None = None,
    agent_id: str | None = None,
    action: str | None = None,
    security_level: str | None = None,
) -> dict:
    """Search audit entries by filters."""
    entries = await _audit_logger.search(
        correlation_id=correlation_id,
        agent_id=agent_id,
        action=action,
        security_level=security_level,
    )
    return {"entries": entries, "count": len(entries)}


@router.get("/metrics")
async def get_metrics() -> dict:
    """System metrics for monitoring dashboard."""
    cb_stats = {name: cb.get_stats() for name, cb in _circuit_breakers.items()}

    return {
        "uptime_seconds": round(time.time() - _start_time, 2),
        "circuit_breakers": cb_stats,
        "circuit_breaker_count": len(_circuit_breakers),
    }


@router.get("/circuit-breakers")
async def get_circuit_breakers() -> dict:
    """Get all circuit breaker states."""
    return {name: cb.get_stats() for name, cb in _circuit_breakers.items()}


@router.post("/circuit-breakers/{name}/reset", status_code=200)
async def reset_circuit_breaker(name: str) -> dict:
    """Manually reset a circuit breaker."""
    if name not in _circuit_breakers:
        return {"error": f"Circuit breaker '{name}' not found"}

    _circuit_breakers[name].reset()
    logger.info("circuit_breaker_manual_reset", name=name)
    return {"status": "reset", "name": name}
