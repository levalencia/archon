"""HTTP dependency helpers for application-scoped security services."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request


async def enforce_rate_limit(request: Request, user: dict[str, Any], scope: str) -> None:
    """Consume one authenticated-user quota unit before expensive work."""
    result = await request.app.state.rate_limiter.check(f"{scope}:{user['user_id']}")
    if result.allowed:
        return
    retry_after = result.retry_after or 1
    raise HTTPException(
        status_code=429,
        detail={
            "error": "rate_limit_exceeded",
            "message": "Request rate limit exceeded",
            "retry_after": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
