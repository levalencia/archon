"""HTTP dependency helpers for application-scoped security services."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from fastapi import HTTPException, Request

_OPAQUE_TRANSPORT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def client_transport_identifier(request: Request) -> str:
    """Return a canonical direct-peer identifier without trusting forwarding headers."""
    host = request.client.host if request.client is not None else "unknown"
    try:
        return f"ip:{ipaddress.ip_address(host).compressed}"
    except ValueError:
        # ASGI test servers and non-IP transports can supply a short opaque peer name.
        opaque = host.strip().lower()
        if not _OPAQUE_TRANSPORT_RE.fullmatch(opaque):
            opaque = "unknown"
        return f"transport:{opaque}"


def _action_limit(request: Request, scope: str) -> int:
    settings = request.app.state.settings
    category = scope.split("_", 1)[0]
    configured = getattr(settings, f"rate_limit_{category}_requests", None)
    return int(configured if configured is not None else settings.rate_limit_requests)


def _rate_limit_error(retry_after: int | None) -> HTTPException:
    retry = retry_after or 1
    return HTTPException(
        status_code=429,
        detail={
            "error": "rate_limit_exceeded",
            "message": "Request rate limit exceeded",
            "retry_after": retry,
        },
        headers={"Retry-After": str(retry)},
    )


async def enforce_ip_rate_limit(request: Request, scope: str) -> None:
    """Consume one direct-peer quota unit before unauthenticated work."""
    result = await request.app.state.rate_limiter.check(
        f"{scope}:ip:{client_transport_identifier(request)}", _action_limit(request, scope)
    )
    if not result.allowed:
        raise _rate_limit_error(result.retry_after)


async def enforce_rate_limit(request: Request, user: dict[str, Any], scope: str) -> None:
    """Consume user then direct-peer quota before authenticated endpoint work.

    A successful user check is consumed even if the subsequent IP check rejects the request.
    An exhausted user bucket does not consume IP quota.
    """
    limit = _action_limit(request, scope)
    user_result = await request.app.state.rate_limiter.check(
        f"{scope}:user:{user['user_id']}", limit
    )
    if not user_result.allowed:
        raise _rate_limit_error(user_result.retry_after)
    ip_result = await request.app.state.rate_limiter.check(
        f"{scope}:ip:{client_transport_identifier(request)}", limit
    )
    if not ip_result.allowed:
        raise _rate_limit_error(ip_result.retry_after)
