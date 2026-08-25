"""Tests for Redis hot-tier memory wiring."""

from __future__ import annotations

import pytest

from app.memory.redis_memory import RedisMemory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_memory_fallback_to_in_memory():
    """When Redis is unavailable, RedisMemory uses in-memory dict as fallback."""
    # Don't call connect() — _redis stays None, fallback is used
    rm = RedisMemory(max_messages=50)

    await rm.store("conv-1", {"role": "user", "content": "hello"})
    msgs = await rm.retrieve("conv-1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "hello"

    stats = await rm.get_stats()
    assert stats["backend"] == "in-memory-fallback"
    assert stats["connected"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_memory_respects_max_messages():
    """Fallback enforces max_messages trimming."""
    rm = RedisMemory(max_messages=3)

    for i in range(5):
        await rm.store("conv-1", {"role": "user", "content": f"msg-{i}"})

    msgs = await rm.retrieve("conv-1")
    assert len(msgs) == 3
    assert msgs[0]["content"] == "msg-2"
    assert msgs[-1]["content"] == "msg-4"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_memory_delete():
    """Delete removes conversation from fallback store."""
    rm = RedisMemory()

    await rm.store("conv-1", {"role": "user", "content": "hello"})
    assert len(await rm.retrieve("conv-1")) == 1

    await rm.delete("conv-1")
    assert len(await rm.retrieve("conv-1")) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_memory_retrieve_with_limit():
    """Retrieve respects the limit parameter."""
    rm = RedisMemory(max_messages=100)

    for i in range(10):
        await rm.store("conv-1", {"role": "user", "content": f"msg-{i}"})

    msgs = await rm.retrieve("conv-1", limit=3)
    assert len(msgs) == 3
    assert msgs[-1]["content"] == "msg-9"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_redis_memory_returns_none_for_file_backend(monkeypatch):
    """get_redis_memory returns None when memory_backend='file'."""
    monkeypatch.setenv("ARCHON_MEMORY_BACKEND", "file")

    from app.memory.persistent import get_redis_memory, reset_singletons

    reset_singletons()
    try:
        result = await get_redis_memory()
        assert result is None
    finally:
        reset_singletons()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_redis_memory_graceful_fallback_when_redis_down(monkeypatch):
    """get_redis_memory returns None when redis is configured but unreachable."""
    monkeypatch.setenv("ARCHON_MEMORY_BACKEND", "redis")
    # Use an unreachable URL
    bad = "redis://unreachable-host-xyzzy"
    monkeypatch.setenv("ARCHON_REDIS_URL", bad)

    from app.memory.persistent import get_redis_memory, reset_singletons

    reset_singletons()
    try:
        result = await get_redis_memory()
        assert result is None
    finally:
        reset_singletons()
