"""Tests for rate limiter (in-memory and Redis via fakeredis)."""

from __future__ import annotations

import pytest

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
        try:
            import fakeredis.aioredis

            redis = fakeredis.aioredis.FakeRedis()
            return RateLimiter(redis_client=redis, max_requests=3, window_seconds=60)
        except ImportError:
            pytest.skip("fakeredis not installed")
            return RateLimiter()  # unreachable but satisfies type checker

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
