"""Persistent memory: durable facts that survive across ALL conversations.

Like Hermes memory tool: stores user preferences, environment details,
stable facts. Injected into every system prompt automatically.

Also includes session search: find information from past conversations.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()

MEMORY_FILE = "archon_memory.json"
MAX_MEMORY_CHARS = 2000


class PersistentMemory:
    """Durable fact store — persists across all conversations.

    Operations: add, replace, remove, list.
    Stored as JSON file. Injected into system prompt automatically.
    """

    def __init__(self, path: str = MEMORY_FILE) -> None:
        self._path = Path(path)
        self._entries: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._entries = json.loads(self._path.read_text())
                logger.info("persistent_memory_loaded", entries=len(self._entries))
            except Exception:
                self._entries = []
        else:
            self._entries = []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._entries, indent=2, ensure_ascii=False))

    def add(self, content: str) -> dict:
        """Add a new memory entry."""
        total_chars = sum(len(e["content"]) for e in self._entries)
        if total_chars + len(content) > MAX_MEMORY_CHARS:
            return {
                "error": (
                    f"Memory full ({total_chars}/{MAX_MEMORY_CHARS} chars). "
                    "Remove old entries first."
                )
            }

        entry = {
            "content": content,
            "created_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._entries.append(entry)
        self._save()
        logger.info("memory_added", content=content[:50], total=len(self._entries))
        return {"status": "added", "total_entries": len(self._entries)}

    def remove(self, substring: str) -> dict:
        """Remove entry matching substring."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if substring.lower() not in e["content"].lower()]
        after = len(self._entries)
        if before == after:
            return {"error": f"No entry matching '{substring}'"}
        self._save()
        return {"status": "removed", "removed": before - after}

    def replace(self, old_text: str, new_content: str) -> dict:
        """Replace entry matching old_text with new content."""
        for entry in self._entries:
            if old_text.lower() in entry["content"].lower():
                entry["content"] = new_content
                entry["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
                self._save()
                return {"status": "replaced"}
        return {"error": f"No entry matching '{old_text}'"}

    def list_all(self) -> list[dict]:
        return self._entries

    def get_context_text(self) -> str:
        """Get all memories as text for system prompt injection."""
        if not self._entries:
            return ""
        lines = [e["content"] for e in self._entries]
        return "\n".join(f"- {line}" for line in lines)

    def get_stats(self) -> dict:
        total_chars = sum(len(e["content"]) for e in self._entries)
        return {
            "entries": len(self._entries),
            "chars_used": total_chars,
            "chars_limit": MAX_MEMORY_CHARS,
            "utilization_pct": round(total_chars / MAX_MEMORY_CHARS * 100, 1),
        }


class SessionStore:
    """Search past conversations by content.

    Stores conversation summaries for cross-session recall.
    Like Hermes session_search tool.
    """

    def __init__(self, path: str = "archon_sessions.json") -> None:
        self._path = Path(path)
        self._sessions: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._sessions = json.loads(self._path.read_text())
            except Exception:
                self._sessions = []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._sessions, indent=2, ensure_ascii=False))

    def save_session(self, conversation_id: str, title: str, messages: list[dict]) -> None:
        """Save a conversation summary for future search."""
        # Build searchable content from messages
        content_parts = []
        for m in messages:
            role = m.get("role", "")
            text = m.get("content", "")[:500]
            if role in ("user", "assistant") and text:
                content_parts.append(f"[{role}] {text}")

        summary = "\n".join(content_parts)

        self._sessions.append(
            {
                "conversation_id": conversation_id,
                "title": title,
                "summary": summary,
                "message_count": len(messages),
                "saved_at": time.strftime("%Y-%m-%d %H:%M"),
            }
        )

        # Keep last 100 sessions
        if len(self._sessions) > 100:
            self._sessions = self._sessions[-100:]

        self._save()
        logger.info("session_saved", conversation_id=conversation_id, messages=len(messages))

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Search past sessions by keyword."""
        query_lower = query.lower()
        query_words = {w for w in query_lower.split() if len(w) > 2}

        scored = []
        for session in self._sessions:
            content = (session.get("title", "") + " " + session.get("summary", "")).lower()
            score = sum(1 for w in query_words if w in content)
            if score > 0:
                scored.append((score, session))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _score, session in scored[:limit]:
            results.append(
                {
                    "conversation_id": session["conversation_id"],
                    "title": session["title"],
                    "saved_at": session["saved_at"],
                    "message_count": session["message_count"],
                    "snippet": session["summary"][:300],
                }
            )

        return results


# Singletons
_persistent_memory: PersistentMemory | None = None
_session_store: SessionStore | None = None
_redis_memory: "RedisMemory | None" = None  # type: ignore[name-defined]  # noqa: F821


def get_persistent_memory() -> PersistentMemory:
    global _persistent_memory
    if _persistent_memory is None:
        _persistent_memory = PersistentMemory()
        # Wrap with encryption if configured
        try:
            from app.config import get_settings
            settings = get_settings()
            if settings.memory_encryption_enabled and settings.encryption_master_key:
                from app.memory.encrypted_memory import EncryptedMemoryStore
                _encrypted_store = EncryptedMemoryStore(settings.encryption_master_key)
                _persistent_memory._encrypted_store = _encrypted_store
                logger.info("persistent_memory_encryption_enabled")
        except Exception:
            logger.debug("persistent_memory_encryption_skipped", reason="config unavailable or error")
    return _persistent_memory


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


async def get_redis_memory():
    """Get a RedisMemory instance when memory_backend='redis'.

    Returns the RedisMemory hot tier if configured and connectable,
    otherwise returns None (caller should fall back to file-only).
    """
    global _redis_memory
    if _redis_memory is not None:
        return _redis_memory

    try:
        from app.config import get_settings
        settings = get_settings()
    except Exception:
        return None

    if settings.memory_backend != "redis":
        return None

    from app.memory.redis_memory import RedisMemory

    rm = RedisMemory(redis_url=settings.redis_url)
    connected = await rm.connect()
    if connected:
        _redis_memory = rm
        return _redis_memory

    logger.warning("redis_memory_fallback", reason="connection failed, using file-only")
    return None


def reset_singletons() -> None:
    """Reset all singletons — for testing only."""
    global _persistent_memory, _session_store, _redis_memory
    _persistent_memory = None
    _session_store = None
    _redis_memory = None
