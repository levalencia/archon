"""Memory and session search tools for the agent.

memory_tool: add/remove/list persistent facts
session_search_tool: search past conversations
"""

from __future__ import annotations

import json

from app.memory.persistent import get_persistent_memory, get_session_store


async def memory_tool(action: str, content: str = "", old_text: str = "", **kwargs) -> str:
    """Manage persistent memory. Actions: add, remove, replace, list.

    Use to save durable facts about the user (preferences, environment, name).
    These facts are injected into every conversation automatically.

    Examples:
    - memory(action="add", content="User lives in Brussels, Belgium")
    - memory(action="add", content="User prefers Spanish for casual, English for technical")
    - memory(action="remove", old_text="Brussels")
    - memory(action="list")
    """
    # Handle alternative parameter names LLMs sometimes use
    if not content and "value" in kwargs:
        content = str(kwargs["value"])
    if not content and "key" in kwargs and action == "add":
        content = f"{kwargs['key']}: {kwargs.get('value', '')}"
    if not old_text and "key" in kwargs and action in ("remove", "replace"):
        old_text = str(kwargs["key"])
    mem = get_persistent_memory()

    if action == "add":
        if not content:
            return json.dumps({"error": "content required for add"})
        result = mem.add(content)
    elif action == "remove":
        result = mem.remove(old_text or content)
    elif action == "replace":
        if not old_text or not content:
            return json.dumps({"error": "old_text and content required for replace"})
        result = mem.replace(old_text, content)
    elif action == "list":
        entries = mem.list_all()
        result = {"entries": [e["content"] for e in entries], "stats": mem.get_stats()}
    else:
        result = {"error": f"Unknown action: {action}. Use: add, remove, replace, list"}

    return json.dumps(result, ensure_ascii=False)


async def session_search_tool(query: str, limit: int = 3) -> str:
    """Search past conversations for information.

    Use when the user asks about something discussed in a previous conversation.
    Returns matching sessions with snippets.

    Examples:
    - session_search(query="authentication bug")
    - session_search(query="database migration")
    """
    store = get_session_store()
    results = store.search(query, limit=limit)

    if not results:
        return json.dumps(
            {
                "query": query,
                "results": [],
                "message": "No matching past conversations found",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "query": query,
            "results": results,
            "total": len(results),
        },
        ensure_ascii=False,
    )
