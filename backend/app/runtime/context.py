"""Build runtime context while preserving conversation, persistent memory, and skills."""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast
from zoneinfo import ZoneInfo

from app.agents.agent import SYSTEM_PROMPT
from app.memory.advanced import get_token_count
from app.runtime.context_provenance import EffectiveContext, EffectiveContextManifest
from app.runtime.models import Message, Role


async def _assemble_messages(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    system_prompt_extra: str,
    images: list[str] | None,
    user_id: str,
    persistent_memory_text: str,
    current_message_id: int | None = None,
    *,
    tool_budget: int,
) -> tuple[tuple[Message, ...], tuple[int | None, ...]]:
    descriptions = (
        json.dumps(tools.list_tools(), indent=2) if tools.list_tools() else "None configured"
    )
    prompt = (
        SYSTEM_PROMPT.replace("{tool_descriptions}", descriptions)
        .replace("{tool_budget}", str(tool_budget))
        .replace(
            "{current_date}",
            datetime.datetime.now(ZoneInfo("Europe/Brussels")).strftime(
                "%A, %B %d, %Y at %H:%M %Z"
            ),
        )
    )
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
    source_ids: list[int | None] = [None]
    found_current = False
    if memory:
        metadata_reader = getattr(memory, "retrieve_with_metadata", None)
        if callable(metadata_reader):
            reader = cast(Callable[..., Awaitable[list[dict[str, Any]]]], metadata_reader)
            history = await reader(conversation_id, limit=20, user_id=user_id)
        else:
            history = await memory.retrieve(conversation_id, limit=20, user_id=user_id)
        for item in history:
            role = Role(item["role"])
            source_id = item.get("id")
            is_current = current_message_id is not None and source_id == current_message_id
            if is_current and role is not Role.USER:
                raise ValueError("current context message must have user role")
            result.append(
                Message(
                    role,
                    item["content"],
                    images=tuple(images or ()) if is_current else (),
                )
            )
            source_ids.append(source_id if type(source_id) is int and source_id > 0 else None)
            found_current = found_current or is_current
    if current_message_id is not None and not found_current:
        raise ValueError("current context message is unavailable")
    if current_message_id is None:
        result.append(Message(Role.USER, user_input, images=tuple(images or ())))
        source_ids.append(None)
    return tuple(result), tuple(source_ids)


def derive_context_asset_hmac_key(application_secret: str) -> bytes:
    if not isinstance(application_secret, str) or not application_secret:
        raise ValueError("context asset fingerprint key is unavailable")
    return hmac.new(
        application_secret.encode("utf-8"),
        b"archon/context-asset-fingerprint-key/v1",
        hashlib.sha256,
    ).digest()


def _asset_fingerprints(
    images: list[str] | None,
    key: bytes | None,
    *,
    owner_id: str,
    project_id: str,
    run_id: str,
) -> tuple[str, ...]:
    if not images:
        return ()
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("context asset fingerprint key is unavailable")
    scope = b"\0".join(
        (owner_id.encode("utf-8"), project_id.encode("utf-8"), run_id.encode("utf-8"))
    )
    return tuple(
        hmac.new(
            key,
            b"archon/context-asset/v1\0" + scope + b"\0" + image.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        for image in images
    )


def _estimated_tokens(messages: tuple[Message, ...]) -> int:
    return sum(get_token_count(message.content) + 4 for message in messages)


async def build_effective_context(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    system_prompt_extra: str = "",
    images: list[str] | None = None,
    user_id: str = "default",
    persistent_memory_text: str = "",
    *,
    project_id: str,
    run_id: str,
    memory_ids: tuple[str, ...] = (),
    skill_ids: tuple[str, ...] = (),
    current_message_id: int | None = None,
    asset_hmac_key: bytes | None = None,
    tool_budget: int = 20,
) -> EffectiveContext:
    messages, source_ids = await _assemble_messages(
        user_input,
        conversation_id,
        memory,
        tools,
        system_prompt_extra,
        images,
        user_id,
        persistent_memory_text,
        current_message_id,
        tool_budget=tool_budget,
    )
    return EffectiveContext(
        messages=messages,
        source_message_ids=source_ids,
        manifest=EffectiveContextManifest(
            owner_id=user_id,
            project_id=project_id,
            run_id=run_id,
            conversation_id=conversation_id,
            selected_message_ids=tuple(
                source_id for source_id in source_ids if source_id is not None
            ),
            memory_ids=memory_ids,
            skill_ids=skill_ids,
            input_asset_fingerprints=_asset_fingerprints(
                images,
                asset_hmac_key,
                owner_id=user_id,
                project_id=project_id,
                run_id=run_id,
            ),
            estimated_tokens=_estimated_tokens(messages),
        ),
    )


async def build_messages(
    user_input: str,
    conversation_id: str,
    memory: Any,
    tools: Any,
    system_prompt_extra: str = "",
    images: list[str] | None = None,
    user_id: str = "default",
    persistent_memory_text: str = "",
    *,
    tool_budget: int = 20,
) -> list[Message]:
    messages, _ = await _assemble_messages(
        user_input,
        conversation_id,
        memory,
        tools,
        system_prompt_extra,
        images,
        user_id,
        persistent_memory_text,
        tool_budget=tool_budget,
    )
    return list(messages)
