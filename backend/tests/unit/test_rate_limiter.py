"""Tests for rate limiter (in-memory and Redis via fakeredis)."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest
from redis.exceptions import ResponseError

from app.security.rate_limiter import RateLimiter


class TestRateLimiterLocal:
    """In-memory rate limiter tests (no Redis needed)."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_allows_within_limit(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            result = await limiter.check("user-1")
            assert result["allowed"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            await limiter.check("user-1")

        result = await limiter.check("user-1")
        assert result["allowed"] is False
        assert result["retry_after"] == 60

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_different_users_independent(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        await limiter.check("user-1")
        await limiter.check("user-1")

        # user-1 is at limit, user-2 should still be fine
        result = await limiter.check("user-2")
        assert result["allowed"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_remaining_count(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        result = await limiter.check("user-1")
        assert result["remaining"] == 4
        assert result["current"] == 1
        assert result["limit"] == 5

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retry_after_none_when_allowed(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        result = await limiter.check("user-1")
        assert result["retry_after"] is None


class TestRateLimiterRedis:
    """Redis-backed rate limiter tests using fakeredis."""

    @pytest.fixture
    async def redis_limiter(self) -> RateLimiter:
        redis = fakeredis.aioredis.FakeRedis()
        return RateLimiter(redis_client=redis, max_requests=3, window_seconds=60)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_redis_allows_within_limit(self, redis_limiter: RateLimiter) -> None:
        for _ in range(3):
            result = await redis_limiter.check("user-1")
            assert result["allowed"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_redis_blocks_over_limit(self, redis_limiter: RateLimiter) -> None:
        for _ in range(3):
            await redis_limiter.check("user-1")

        result = await redis_limiter.check("user-1")
        assert result["allowed"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_redis_different_users(self, redis_limiter: RateLimiter) -> None:
        for _ in range(3):
            await redis_limiter.check("user-1")

        result = await redis_limiter.check("user-2")
        assert result["allowed"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_fakeredis_transaction_fallback_is_atomic_under_concurrency(self) -> None:
        limiter = RateLimiter(
            redis_client=fakeredis.aioredis.FakeRedis(), max_requests=7, window_seconds=60
        )

        results = await asyncio.gather(*(limiter.check("same-user") for _ in range(30)))

        assert sum(result.allowed for result in results) == 7
        assert sum(not result.allowed for result in results) == 23

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_eval_redis_errors_fail_closed_without_local_fallback(self) -> None:
        class BrokenRedis:
            async def eval(self, *_args: object) -> None:
                raise ResponseError("connection dropped")

        limiter = RateLimiter(redis_client=BrokenRedis(), max_requests=1)
        with pytest.raises(ResponseError, match="connection dropped"):
            await limiter.check("user")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_lua_fast_path_uses_unique_members(self) -> None:
        class EvalRedis:
            def __init__(self) -> None:
                self.members: list[str] = []

            async def eval(self, _script: str, _keys: int, _key: str, *args: object) -> list[int]:
                self.members.append(str(args[-1]))
                count = len(self.members)
                return [1, count, 3 - count, 0]

        redis = EvalRedis()
        limiter = RateLimiter(redis_client=redis, max_requests=3)
        await asyncio.gather(*(limiter.check("user") for _ in range(3)))

        assert len(set(redis.members)) == 3
