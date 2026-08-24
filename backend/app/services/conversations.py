"""Unified persistent repository for conversation metadata, messages, and run events."""

from __future__ import annotations

from app.services.db_store import DatabaseStore


class ConversationRepository:
    """Persist user-scoped conversations, messages, and runtime events."""

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

    async def create(self, conversation_id: str, title: str, user_id: str = "default") -> dict:
        await self._store.create_conversation(conversation_id, title, user_id)
        conversation = await self._store.get_conversation(conversation_id, user_id)
        assert conversation is not None
        return {**conversation, "message_count": 0}

    async def list(self, user_id: str = "default") -> list[dict]:
        return await self._store.list_conversations(user_id)

    async def get(self, conversation_id: str, user_id: str = "default") -> dict | None:
        conversation = await self._store.get_conversation(conversation_id, user_id)
        if conversation is None:
            return None
        messages = await self.retrieve(conversation_id, user_id=user_id)
        return {**conversation, "messages": messages, "message_count": len(messages)}

    async def delete(self, conversation_id: str, user_id: str = "default") -> bool:
        return await self._store.delete_conversation(conversation_id, user_id)

    async def store(
        self, conversation_id: str, role: str, content: str, user_id: str = "default"
    ) -> None:
        await self._store.store_message(conversation_id, role, content, user_id)

    async def retrieve(
        self, conversation_id: str, limit: int = 50, user_id: str = "default"
    ) -> list[dict]:
        return await self._store.retrieve(conversation_id, limit, user_id)
