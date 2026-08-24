"""Unified persistent repository for conversation metadata and messages."""

from __future__ import annotations

from app.services.db_store import DatabaseStore


class ConversationRepository:
    """Persist conversation metadata and messages in one database-backed store."""

    def __init__(self, database_url: str) -> None:
        self._store = DatabaseStore(database_url)

    async def initialize(self) -> None:
        await self._store.initialize()

    async def close(self) -> None:
        await self._store.close()

    async def check_health(self) -> None:
        await self._store.ping()

    async def append_runtime_event(self, **event) -> None:
        await self._store.append_runtime_event(event)

    async def recent_runtime_events(
        self, *, run_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        return await self._store.recent_runtime_events(run_id=run_id, limit=min(max(limit, 1), 200))

    async def create(self, conversation_id: str, title: str) -> dict:
        await self._store.create_conversation(conversation_id, title)
        conversation = await self._store.get_conversation(conversation_id)
        assert conversation is not None
        return {**conversation, "message_count": 0}

    async def list(self) -> list[dict]:
        return await self._store.list_conversations()

    async def get(self, conversation_id: str) -> dict | None:
        conversation = await self._store.get_conversation(conversation_id)
        if conversation is None:
            return None
        messages = await self.retrieve(conversation_id)
        return {**conversation, "messages": messages, "message_count": len(messages)}

    async def delete(self, conversation_id: str) -> bool:
        return await self._store.delete_conversation(conversation_id)

    async def store(self, conversation_id: str, role: str, content: str) -> None:
        await self._store.store_message(conversation_id, role, content)

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict]:
        return await self._store.retrieve(conversation_id, limit)
