"""Authenticated, owner-scoped live operational logs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from app.observability.log_buffer import OwnerLogBuffer
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _visibility(user: dict[str, Any], all_users: bool) -> tuple[str, bool]:
    """Admins may explicitly request all owners; everyone defaults to their own logs."""
    return str(user["user_id"]), bool(all_users and user.get("is_admin") is True)


@router.get("/stream")
async def stream_logs(
    request: Request,
    all_users: bool = Query(default=False),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> StreamingResponse:
    """Stream this owner's logs, or all app-local logs when explicitly requested by an admin."""
    buffer = cast(OwnerLogBuffer, request.app.state.log_buffer)
    owner_id, include_all = _visibility(user, all_users)
    queue = buffer.subscribe(owner_id=owner_id, include_all=include_all)

    async def event_stream() -> AsyncIterator[str]:
        try:
            for entry in buffer.recent(owner_id=owner_id, include_all=include_all, limit=50):
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            buffer.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/recent")
async def recent_logs(
    request: Request,
    limit: int = Query(default=50, ge=0, le=200),
    all_users: bool = Query(default=False),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> list[dict[str, Any]]:
    """Return app-local recent logs visible to the authenticated owner."""
    owner_id, include_all = _visibility(user, all_users)
    buffer = cast(OwnerLogBuffer, request.app.state.log_buffer)
    return buffer.recent(owner_id=owner_id, include_all=include_all, limit=limit)
