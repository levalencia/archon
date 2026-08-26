"""Factories for request-scoped encrypted memory and owner-scoped session tools."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.memory.persistent import SessionStore
from app.memory.scoped import MemoryLimitError, ScopedEncryptedMemoryRepository
from app.runtime.factory import RunContext
from app.services.conversations import ConversationRepository


def _provenance(context: RunContext, action: str) -> dict[str, str]:
    return {
        "source_conversation_id": context.conversation_id,
        "source_run_id": context.run_id,
        "source_action": action,
    }


def create_memory_tool(
    repository: ScopedEncryptedMemoryRepository | None, context: RunContext
) -> Callable[..., Awaitable[str]]:
    """Bind encrypted memory operations to an immutable request context."""

    async def memory_tool(action: str, content: str = "", old_text: str = "") -> str:
        if repository is None:
            return json.dumps({"error": "Persistent memory is disabled"})
        try:
            if action == "add":
                if not content:
                    return json.dumps({"error": "content required for add"})
                await repository.add(
                    context.user_id,
                    context.project_id,
                    content,
                    provenance=_provenance(context, action),
                )
                entries = await repository.list(context.user_id, context.project_id)
                result: dict[str, Any] = {"status": "added", "total_entries": len(entries)}
            elif action == "remove":
                removed = await repository.remove(
                    context.user_id, context.project_id, old_text or content
                )
                result = (
                    {"status": "removed", "removed": removed}
                    if removed
                    else {"error": "No matching entry"}
                )
            elif action == "replace":
                if not old_text or not content:
                    return json.dumps({"error": "old_text and content required for replace"})
                fact = await repository.replace(
                    context.user_id,
                    context.project_id,
                    old_text,
                    content,
                    provenance=_provenance(context, action),
                )
                result = {"status": "replaced"} if fact else {"error": "No matching entry"}
            elif action == "list":
                entries = await repository.list(context.user_id, context.project_id)
                chars = sum(len(entry.content) for entry in entries)
                result = {
                    "entries": [entry.content for entry in entries],
                    "stats": {"entries": len(entries), "chars_used": chars},
                }
            else:
                result = {"error": f"Unknown action: {action}. Use: add, remove, replace, list"}
        except MemoryLimitError:
            result = {"error": "Scoped memory character limit exceeded"}
        return json.dumps(result, ensure_ascii=False)

    return memory_tool


def create_session_search_tool(
    repository: ConversationRepository, context: RunContext
) -> Callable[..., Awaitable[str]]:
    """Bind conversation search to the authenticated owner for this request."""

    async def session_search_tool(query: str, limit: int = 3) -> str:
        results = await repository.search(context.user_id, query, limit=min(max(limit, 1), 20))
        payload: dict[str, Any] = {"query": query, "results": results, "total": len(results)}
        if not results:
            payload["message"] = "No matching past conversations found"
        return json.dumps(payload, ensure_ascii=False)

    return session_search_tool


# Historical entry points remain outside live request wiring.
def get_session_store() -> SessionStore:
    """Compatibility hook for historical tests; never used by live request registries."""
    from app.memory.persistent import get_session_store as legacy_get_session_store

    return legacy_get_session_store()


async def memory_tool(action: str, content: str = "", old_text: str = "", **kwargs: Any) -> str:
    del action, content, old_text, kwargs
    return json.dumps({"error": "Persistent memory requires a scoped request context"})


async def session_search_tool(query: str, limit: int = 3) -> str:
    results = get_session_store().search(query, limit=limit)
    return json.dumps(
        {"query": query, "results": results, "total": len(results)}, ensure_ascii=False
    )
