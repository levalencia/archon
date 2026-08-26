"""Build runtime context while preserving conversation, persistent memory, and skills."""

from __future__ import annotations

import datetime
import json
from typing import Any
from zoneinfo import ZoneInfo

from app.agents.agent import SYSTEM_PROMPT
from app.runtime.models import Message, Role


async def build_messages(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    system_prompt_extra: str = "",
    images: list[str] | None = None,
    user_id: str = "default",
    persistent_memory_text: str = "",
) -> list[Message]:
    descriptions = (
        json.dumps(tools.list_tools(), indent=2) if tools.list_tools() else "None configured"
    )
    prompt = (
        SYSTEM_PROMPT.replace("{tool_descriptions}", descriptions)
        .replace("{tool_budget}", "8")
        .replace(
            "{current_date}",
            datetime.datetime.now(ZoneInfo("Europe/Brussels")).strftime(
                "%A, %B %d, %Y at %H:%M %Z"
            ),
        )
    )
    # Native schemas supersede the legacy textual call syntax.
    prompt = prompt.replace(
        "When you need to use a tool, respond ONLY with a JSON object:\n"
        '{"tool_call": {"name": "tool_name", "parameters": {"key": "value"}}}\n',
        "Use the provider's native tool calling mechanism whenever a tool is needed.\n",
    )
    if persistent_memory_text:
        prompt += (
            "\n\nPERSISTENT MEMORY (facts about the user in this project):\n"
            f"{persistent_memory_text}\n"
        )
    if system_prompt_extra:
        prompt += system_prompt_extra
    result = [Message(Role.SYSTEM, prompt)]
    if memory:
        for item in await memory.retrieve(conversation_id, limit=20, user_id=user_id):
            role = Role(item["role"])
            result.append(Message(role, item["content"]))
    result.append(Message(Role.USER, user_input, images=tuple(images or ())))
    return result
