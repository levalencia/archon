"""Azure Managed Identity token provider for OpenAI-compatible endpoints.

Acquires and caches tokens from ``azure.identity.aio.ManagedIdentityCredential``
(or any compatible ``TokenCredential``) and refreshes them before they expire.
Never logs or includes raw tokens in error messages.
"""

from __future__ import annotations

import time
from typing import Protocol

import structlog

logger = structlog.get_logger()

#: Default scope for Azure AI Foundry / DeepSeek Foundry endpoints.
DEFAULT_SCOPE = "https://ai.azure.com/.default"

#: Refresh a token when fewer than this many seconds remain.
_REFRESH_MARGIN_SECONDS = 300


class AsyncTokenCredential(Protocol):
    """Minimal protocol matching ``azure.identity.aio`` credential objects."""

    async def get_token(self, *scopes: str) -> _AccessToken: ...

    async def close(self) -> None: ...


class _AccessToken(Protocol):
    """Minimal protocol matching ``azure.core.credentials.AccessToken``."""

    token: str
    expires_on: int


class AzureTokenProvider:
    """Fetches and caches Azure AD tokens with proactive refresh.

    Parameters
    ----------
    credential:
        An async ``TokenCredential`` (e.g. ``ManagedIdentityCredential``).
    scope:
        OAuth2 scope.  Defaults to ``https://ai.azure.com/.default``.
    """

    def __init__(
        self,
        credential: AsyncTokenCredential,
        scope: str = DEFAULT_SCOPE,
    ) -> None:
        self._credential = credential
        self._scope = scope
        self._cached_token: str | None = None
        self._expires_on: float = 0.0

    async def get_bearer_token(self) -> str:
        """Return a valid Bearer token, refreshing if close to expiry."""
        now = time.monotonic()
        if self._cached_token is not None and now < self._expires_on:
            return self._cached_token
        return await self._refresh(now)

    async def _refresh(self, now: float) -> str:
        access = await self._credential.get_token(self._scope)
        # ``expires_on`` is UTC epoch; convert to monotonic-relative deadline.
        wall_now = time.time()
        ttl = access.expires_on - wall_now - _REFRESH_MARGIN_SECONDS
        self._expires_on = now + max(ttl, 0)
        self._cached_token = access.token
        logger.info(
            "azure_token_refreshed",
            scope=self._scope,
            ttl_seconds=round(ttl),
        )
        return access.token

    async def close(self) -> None:
        """Release the underlying credential transport."""
        await self._credential.close()
