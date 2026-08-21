"""In-memory conversation store for testing and development.

Simple dict-based store, no persistence, no encryption.
Perfect for unit tests and local dev without PostgreSQL.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


class InMemoryStore:
    """Non-persistent memory store. Data lives in a dict, lost on restart.

    Satisfies the MemoryStore Protocol.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, list[dict[str, str]]] = {}

    async def store(self, conversation_id: str, role: str, content: str) -> None:
        """Store a message in conversation history."""
        self._conversations.setdefault(conversation_id, []).append(
            {"role": role, "content": content}
        )
        logger.debug(
            "memory_stored",
            conversation_id=conversation_id,
            role=role,
            content_length=len(content),
        )

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict[str, str]]:
        """Retrieve recent messages for a conversation."""
        messages = self._conversations.get(conversation_id, [])
        return messages[-limit:]

    async def list_conversations(self) -> list[str]:
        """List all conversation IDs."""
        return list(self._conversations.keys())

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation. Returns True if it existed."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    async def get_message_count(self, conversation_id: str) -> int:
        """Count messages in a conversation."""
        return len(self._conversations.get(conversation_id, []))
