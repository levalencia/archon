"""Distributed rate limiter using Redis sliding window.

Uses sorted sets for accurate sliding window counting.
Falls back to in-memory when Redis is unavailable (dev mode).

See: https://github.com/levalencia/production-ai-agents/
Concept: Layer 5 - Guardrails (rate limiting)
Course reference: AIAMastery Day 4 - Resilient Agent
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger()


class RateLimiter:
    """Sliding window rate limiter.

    Uses Redis sorted sets in production, or in-memory dict for testing.
    """

    def __init__(
        self,
        redis_client: object | None = None,
        max_requests: int = 60,
        window_seconds: int = 60,
        key_prefix: str = "rate_limit",
    ) -> None:
        self._redis = redis_client
        self._max_requests = max_requests
        self._window = window_seconds
        self._prefix = key_prefix
        # In-memory fallback
        self._local_store: dict[str, list[float]] = {}

    async def check(self, identifier: str) -> dict:
        """Check if identifier is within rate limit.

        Returns: {allowed: bool, current: int, limit: int, remaining: int, retry_after: int|None}
        """
        if self._redis:
            return await self._check_redis(identifier)
        return self._check_local(identifier)

    async def _check_redis(self, identifier: str) -> dict:
        """Redis-backed sliding window check."""
        key = f"{self._prefix}:{identifier}"
        now = time.time()
        window_start = now - self._window

        pipe = self._redis.pipeline()  # type: ignore[union-attr]
        pipe.zremrangebyscore(key, 0, window_start)  # type: ignore[union-attr]
        pipe.zcard(key)  # type: ignore[union-attr]
        pipe.zadd(key, {str(now): now})  # type: ignore[union-attr]
        pipe.expire(key, self._window)  # type: ignore[union-attr]
        results = await pipe.execute()  # type: ignore[union-attr]

        current = results[1]
        allowed = current < self._max_requests

        if not allowed:
            await self._redis.zrem(key, str(now))  # type: ignore[union-attr]

        result = {
            "allowed": allowed,
            "current": current + (1 if allowed else 0),
            "limit": self._max_requests,
            "remaining": max(0, self._max_requests - current - (1 if allowed else 0)),
            "retry_after": self._window if not allowed else None,
        }

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                current=current,
                limit=self._max_requests,
            )

        return result

    def _check_local(self, identifier: str) -> dict:
        """In-memory sliding window check (for testing without Redis)."""
        now = time.time()
        window_start = now - self._window

        # Initialize or clean old entries
        if identifier not in self._local_store:
            self._local_store[identifier] = []

        self._local_store[identifier] = [
            t for t in self._local_store[identifier] if t > window_start
        ]

        current = len(self._local_store[identifier])
        allowed = current < self._max_requests

        if allowed:
            self._local_store[identifier].append(now)

        return {
            "allowed": allowed,
            "current": current + (1 if allowed else 0),
            "limit": self._max_requests,
            "remaining": max(0, self._max_requests - current - (1 if allowed else 0)),
            "retry_after": self._window if not allowed else None,
        }
