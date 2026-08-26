"""Redis-backed hot tier memory for conversations.

Stores recent messages in Redis for fast access.
Falls back to in-memory dict when Redis is unavailable.
"""

from __future__ import annotations

import json

import structlog

from app.observability.logging import safe_exception_metadata

logger = structlog.get_logger()


class RedisMemory:
    """Redis-backed conversation memory (hot tier).

    Stores last N messages per conversation in Redis sorted sets.
    Falls back to in-memory when Redis is unavailable.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        max_messages: int = 50,
    ) -> None:
        self.redis_url = redis_url
        self.max_messages = max_messages
        self._redis = None
        self._fallback: dict[str, list[dict]] = {}

    async def connect(self) -> bool:
        """Connect to Redis. Returns False if unavailable."""
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("redis_connected")
            return True
        except Exception as exc:
            logger.warning("redis_unavailable", **safe_exception_metadata(exc, "connection_failed"))
            self._redis = None
            return False

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()

    async def store(self, conversation_id: str, message: dict) -> None:
        """Store a message in the hot tier."""
        if self._redis:
            try:
                key = f"archon:conv:{conversation_id}:messages"
                await self._redis.rpush(key, json.dumps(message))
                # Trim to max_messages
                await self._redis.ltrim(key, -self.max_messages, -1)
                # Set TTL (24 hours)
                await self._redis.expire(key, 86400)
                return
            except Exception as exc:
                logger.warning("redis_store_error", **safe_exception_metadata(exc, "write_failed"))

        # Fallback
        msgs = self._fallback.setdefault(conversation_id, [])
        msgs.append(message)
        if len(msgs) > self.max_messages:
            self._fallback[conversation_id] = msgs[-self.max_messages :]

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict]:
        """Retrieve messages from hot tier."""
        if self._redis:
            try:
                key = f"archon:conv:{conversation_id}:messages"
                raw = await self._redis.lrange(key, -limit, -1)
                return [json.loads(r) for r in raw]
            except Exception as exc:
                logger.warning(
                    "redis_retrieve_error", **safe_exception_metadata(exc, "read_failed")
                )

        # Fallback
        msgs = self._fallback.get(conversation_id, [])
        return msgs[-limit:]

    async def delete(self, conversation_id: str) -> None:
        """Delete conversation from hot tier."""
        if self._redis:
            try:
                key = f"archon:conv:{conversation_id}:messages"
                await self._redis.delete(key)
                return
            except Exception:
                pass
        self._fallback.pop(conversation_id, None)

    async def get_stats(self) -> dict:
        """Get Redis memory stats."""
        if self._redis:
            try:
                info = await self._redis.info("memory")
                return {
                    "backend": "redis",
                    "used_memory_mb": round(info.get("used_memory", 0) / 1024 / 1024, 2),
                    "connected": True,
                }
            except Exception:
                pass

        return {
            "backend": "in-memory-fallback",
            "conversations": len(self._fallback),
            "connected": False,
        }
