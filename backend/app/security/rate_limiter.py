"""Concurrency-safe authenticated-user sliding-window rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

import structlog

logger = structlog.get_logger()

_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, member)
  redis.call('PEXPIRE', key, math.ceil(window))
  return {1, count + 1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window
if oldest[2] then retry = math.max(1, math.ceil(oldest[2] + window - now)) end
redis.call('PEXPIRE', key, math.ceil(window))
return {0, count, 0, retry}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    current: int
    limit: int
    remaining: int
    retry_after: int | None

    def __getitem__(self, key: str) -> bool | int | None:
        return cast(bool | int | None, getattr(self, key))


class RateLimiter:
    """Atomic sliding window limiter; local mode is process-local by design."""

    def __init__(
        self,
        redis_client: Any | None = None,
        max_requests: int = 60,
        window_seconds: int = 60,
        key_prefix: str = "rate_limit",
        *,
        owns_redis: bool = False,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if window_seconds < 1:
            raise ValueError("window_seconds must be positive")
        if not key_prefix:
            raise ValueError("key_prefix must not be empty")
        self._redis = redis_client
        self._max_requests = max_requests
        self._window = window_seconds
        self._prefix = key_prefix
        self._owns_redis = owns_redis
        self._local_store: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    def _key(self, identifier: str) -> str:
        # Never expose user identifiers, request bodies, tokens, or secrets in Redis keys.
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        return f"{self._prefix}:{digest}"

    async def check(self, identifier: str) -> RateLimitResult:
        if self._redis is not None:
            return await self._check_redis(identifier)
        return await self._check_local(identifier)

    async def _check_redis(self, identifier: str) -> RateLimitResult:
        redis = self._redis
        if redis is None:  # pragma: no cover - guarded by check()
            raise RuntimeError("Redis client is not configured")
        now_ms = int(time.time() * 1000)
        key = self._key(identifier)
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            values = await redis.eval(
                _LUA,
                1,
                key,
                now_ms,
                self._window * 1000,
                self._max_requests,
                member,
            )
        except Exception as exc:
            # Some Redis-compatible test/development servers do not implement EVAL.  Keep
            # production on the one-round-trip Lua path, but retain Redis-backed atomicity
            # rather than silently degrading to the process-local limiter.
            if "unknown command" not in str(exc).lower() or "eval" not in str(exc).lower():
                raise
            values = await self._check_redis_transaction(key, now_ms, member)
        return self._redis_result(values)

    async def _check_redis_transaction(
        self, key: str, now_ms: int, member: str
    ) -> tuple[int, int, int, int]:
        """WATCH/MULTI fallback for Redis implementations without Lua scripting."""
        from redis.exceptions import WatchError

        redis = self._redis
        if redis is None:  # pragma: no cover - guarded by check()
            raise RuntimeError("Redis client is not configured")
        window_ms = self._window * 1000
        while True:
            async with redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    # Use an exclusive lower bound: Lua removes scores <= the cutoff.
                    active = await pipe.zrangebyscore(
                        key, f"({now_ms - window_ms}", "+inf", withscores=True
                    )
                    count = len(active)
                    allowed = count < self._max_requests
                    retry_ms = 0
                    if not allowed:
                        retry_ms = max(1, math.ceil(float(active[0][1]) + window_ms - now_ms))

                    pipe.multi()
                    pipe.zremrangebyscore(key, "-inf", now_ms - window_ms)
                    if allowed:
                        pipe.zadd(key, {member: now_ms})
                    pipe.pexpire(key, window_ms)
                    await pipe.execute()
                    current = count + int(allowed)
                    return int(allowed), current, max(0, self._max_requests - current), retry_ms
                except WatchError:
                    # A concurrent request changed the bucket; recompute against its result.
                    continue

    def _redis_result(self, values: Any) -> RateLimitResult:
        allowed, current, remaining, retry_ms = (int(value) for value in values)
        result = RateLimitResult(
            bool(allowed),
            current,
            self._max_requests,
            remaining,
            None if allowed else max(1, math.ceil(retry_ms / 1000)),
        )
        if not result.allowed:
            logger.warning("rate_limit_exceeded", limit=self._max_requests)
        return result

    async def _check_local(self, identifier: str) -> RateLimitResult:
        key = self._key(identifier)
        async with self._lock:
            now = time.monotonic()
            entries = [
                stamp for stamp in self._local_store.get(key, ()) if stamp > now - self._window
            ]
            allowed = len(entries) < self._max_requests
            if allowed:
                entries.append(now)
            self._local_store[key] = entries
            retry = None
            if not allowed:
                retry = max(1, math.ceil(entries[0] + self._window - now))
                logger.warning("rate_limit_exceeded", limit=self._max_requests)
            return RateLimitResult(
                allowed,
                len(entries),
                self._max_requests,
                max(0, self._max_requests - len(entries)),
                retry,
            )

    async def close(self) -> None:
        if self._redis is not None and self._owns_redis:
            await self._redis.aclose()
