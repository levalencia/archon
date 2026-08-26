"""Unified persistent repository for conversation metadata, messages, and run events."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any

from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore
from app.services.run_ledger import RunRepository


class ConversationRepository:
    """Persist user-scoped conversations, messages, and runtime events."""

    def __init__(self, database_url: str, redactor: PersistenceRedactor) -> None:
        self._store = DatabaseStore(database_url)
        self._redactor = redactor
        self.runs = RunRepository(self._store.session_factory, redactor)

    async def initialize(self) -> None:
        await self._store.initialize()

    async def close(self) -> None:
        await self._store.close()

    async def check_health(self) -> None:
        await self._store.ping()

    async def append_runtime_event(self, **event: Any) -> None:
        await self.runs.append(
            run_id=str(event["run_id"]),
            user_id=str(event.get("user_id", "default")),
            project_id=str(event.get("project_id", "default")),
            conversation_id=str(event["conversation_id"]),
            correlation_id=str(event["correlation_id"]),
            provider=str(event.get("provider", "unknown")),
            model=str(event.get("model", "unknown")),
            kind=str(event["kind"]),
            iteration=int(event["iteration"]),
            payload=event.get("data", event.get("payload", {})),
            input_tokens=int(event.get("input_tokens", 0)),
            output_tokens=int(event.get("output_tokens", 0)),
            total_tokens=int(event.get("total_tokens", 0)),
        )

    async def recent_runtime_events(
        self, *, run_id: str | None = None, limit: int = 100
    ) -> builtins.list[dict[str, Any]]:
        if run_id is None:
            pages = await self.runs.list("default", limit=min(max(limit, 1), 200))
            if not pages.items:
                return []
            run_id = pages.items[0].run_id
        page = await self.runs.events("default", run_id, limit=min(max(limit, 1), 200))
        if page is None:
            return []
        return [
            {
                "run_id": item.run_id,
                "conversation_id": item.conversation_id,
                "correlation_id": item.correlation_id,
                "kind": item.kind,
                "iteration": item.iteration,
                "data": dict(item.payload),
            }
            for item in page.items
        ]

    async def create(
        self, conversation_id: str, title: str, user_id: str = "default"
    ) -> dict[str, Any]:
        await self._store.create_conversation(
            conversation_id, self._redactor.redact_text(title).text, user_id
        )
        conversation = await self._store.get_conversation(conversation_id, user_id)
        assert conversation is not None
        return {**conversation, "message_count": 0}

    async def list(self, user_id: str = "default") -> builtins.list[dict[str, Any]]:
        return await self._store.list_conversations(user_id)

    async def get(self, conversation_id: str, user_id: str = "default") -> dict[str, Any] | None:
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
        await self._store.store_message(
            conversation_id, role, self._redactor.redact_text(content).text, user_id
        )

    async def retrieve(
        self, conversation_id: str, limit: int = 50, user_id: str = "default"
    ) -> builtins.list[dict[str, Any]]:
        return await self._store.retrieve(conversation_id, limit, user_id)

    async def retrieve_through(
        self,
        conversation_id: str,
        through: datetime,
        *,
        user_id: str,
        limit: int = 50,
    ) -> builtins.list[dict[str, Any]]:
        return await self._store.retrieve_through(
            conversation_id, through, user_id=user_id, limit=limit
        )

    async def search(
        self, user_id: str, query: str, *, limit: int = 3
    ) -> builtins.list[dict[str, Any]]:
        """Search persisted conversations without crossing the authenticated owner boundary."""
        return await self._store.search_conversations(user_id, query, limit=limit)
