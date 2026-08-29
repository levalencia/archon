"""Authenticated, metadata-only sandbox runner status."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class SandboxStatusResponse(BaseModel):
    enabled: bool
    available: bool
    isolation: str
    kinds: tuple[str, ...]
    network_access: bool
    timeout_seconds: float
    output_bytes: int
    memory_mb: int
    pids_limit: int
    cpus: float
    limits_source: str


@router.get("/status", response_model=SandboxStatusResponse)
async def sandbox_status(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> SandboxStatusResponse:
    await enforce_rate_limit(request, user, "task_status")
    settings = request.app.state.settings
    executor = request.app.state.sandbox_executor
    available = False
    if settings.execution_enabled and executor is not None:
        try:
            async with asyncio.timeout(2.5):
                await executor.preflight()
            available = True
        except (RuntimeError, TimeoutError, OSError):
            available = False
    return SandboxStatusResponse(
        enabled=settings.execution_enabled,
        available=available,
        isolation="runner-container" if settings.execution_enabled else "disabled",
        kinds=("python", "shell") if settings.execution_enabled else (),
        network_access=False,
        timeout_seconds=settings.execution_timeout_seconds,
        output_bytes=settings.execution_output_bytes,
        memory_mb=settings.execution_memory_mb,
        pids_limit=settings.execution_pids_limit,
        cpus=settings.execution_cpus,
        limits_source="backend-config",
    )
