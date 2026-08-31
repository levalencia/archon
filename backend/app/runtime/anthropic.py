"""Helpers shared by Anthropic and Azure AI Foundry SDK adapters."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition

_DATA_IMAGE_RE = re.compile(r"\Adata:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/]+={0,2})\Z")


def _anthropic_image(image: str) -> tuple[str, str]:
    match = _DATA_IMAGE_RE.fullmatch(image)
    if match is None:
        # Legacy raw image values were JPEG base64.
        return "image/jpeg", image
    return match.group(1), match.group(2)


def anthropic_request(
    messages: Sequence[Message],
    tools: Sequence[ToolDefinition],
    max_tokens: int,
    *,
    response_format: str | None = None,
    prompt_caching_enabled: bool = False,
    json_prefill_enabled: bool = True,
) -> dict[str, Any]:
    system_parts: list[str] = []
    converted: list[dict[str, Any]] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            system_parts.append(message.content)
        elif message.role is Role.TOOL:
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content,
                        }
                    ],
                }
            )
        elif message.role is Role.ASSISTANT and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": dict(call.arguments),
                }
                for call in message.tool_calls
            )
            converted.append({"role": "assistant", "content": blocks})
        else:
            block: dict[str, Any] = {"role": message.role.value, "content": message.content}
            if message.images:
                block["content"] = [
                    *(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _anthropic_image(image)[0],
                                "data": _anthropic_image(image)[1],
                            },
                        }
                        for image in message.images
                    ),
                    {"type": "text", "text": message.content},
                ]
            converted.append(block)
    request: dict[str, Any] = {"messages": converted, "max_tokens": max_tokens}
    if system_parts:
        system_text = "\n\n".join(system_parts)
        if prompt_caching_enabled:
            request["system"] = [
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            request["system"] = system_text
    if tools:
        request["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
            }
            for tool in tools
        ]
    if response_format == "json":
        # Add JSON instruction to system prompt
        json_instruction = "Respond with valid JSON only."
        if "system" in request:
            if isinstance(request["system"], list):
                request["system"].append({"type": "text", "text": json_instruction})
            else:
                request["system"] = request["system"] + "\n\n" + json_instruction
        else:
            request["system"] = json_instruction
        # Direct Anthropic supports assistant prefill; some Foundry endpoints reject it.
        if json_prefill_enabled:
            request["messages"].append({"role": "assistant", "content": "{"})
    return request


def normalize_json_mode_content(content: str) -> str:
    """Remove only an exact JSON Markdown fence; never extract arbitrary embedded JSON."""

    stripped = content.strip()
    if not stripped.startswith("```") or not stripped.endswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    if first_newline < 0:
        return stripped
    language = stripped[3:first_newline].strip().lower()
    if language not in {"", "json"}:
        return stripped
    return stripped[first_newline + 1 : -3].strip()


def anthropic_response(
    response: Any, *, json_prefill: bool = False, json_mode: bool = False
) -> ModelResponse:
    text: list[str] = []
    calls: list[ToolCall] = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text.append(block.text)
        elif block_type == "tool_use":
            calls.append(ToolCall(block.id, block.name, block.input))
    content = "".join(text) or None
    if json_mode and content is not None:
        content = normalize_json_mode_content(content)
    if json_prefill and content is not None and not content.lstrip().startswith("{"):
        content = "{" + content
    return ModelResponse(
        content=content,
        tool_calls=tuple(calls),
        usage=normalize_anthropic_usage(response.usage),
        provider_stop_reason=getattr(response, "stop_reason", None),
    )


_MISSING = object()


def normalize_anthropic_usage(usage: object) -> TokenUsage:
    """Normalize Anthropic usage while preserving absent cache counters.

    Anthropic's ``input_tokens`` excludes cache reads and cache creation, while
    the runtime's input count is total input consumed by the request.
    """

    def raw(name: str) -> object:
        if isinstance(usage, Mapping):
            return usage.get(name, _MISSING)
        return getattr(usage, name, _MISSING)

    def count(name: str, *, required: bool) -> int | None:
        value = raw(name)
        if value is _MISSING or (value is None and not required):
            return 0 if required else None
        if type(value) is not int:
            raise TypeError(f"Anthropic usage {name} must be an int")
        if value < 0:
            raise ValueError(f"Anthropic usage {name} cannot be negative")
        return value

    uncached = count("input_tokens", required=True)
    output = count("output_tokens", required=True)
    cache_write = count("cache_creation_input_tokens", required=False)
    cache_read = count("cache_read_input_tokens", required=False)
    assert uncached is not None and output is not None
    return TokenUsage(
        input_tokens=uncached + (cache_write or 0) + (cache_read or 0),
        output_tokens=output,
        cache_read_input_tokens=cache_read,
        cache_write_input_tokens=cache_write,
    )
