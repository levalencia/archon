"""Helpers shared by Anthropic and Azure AI Foundry SDK adapters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition


def anthropic_request(
    messages: Sequence[Message], tools: Sequence[ToolDefinition], max_tokens: int
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
                                "media_type": "image/jpeg",
                                "data": image,
                            },
                        }
                        for image in message.images
                    ),
                    {"type": "text", "text": message.content},
                ]
            converted.append(block)
    request: dict[str, Any] = {"messages": converted, "max_tokens": max_tokens}
    if system_parts:
        request["system"] = "\n\n".join(system_parts)
    if tools:
        request["tools"] = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": dict(tool.input_schema),
            }
            for tool in tools
        ]
    return request


def anthropic_response(response: Any) -> ModelResponse:
    text: list[str] = []
    calls: list[ToolCall] = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text.append(block.text)
        elif block_type == "tool_use":
            calls.append(ToolCall(block.id, block.name, block.input))
    return ModelResponse(
        content="".join(text) or None,
        tool_calls=tuple(calls),
        usage=TokenUsage(
            getattr(response.usage, "input_tokens", 0),
            getattr(response.usage, "output_tokens", 0),
        ),
        provider_stop_reason=getattr(response, "stop_reason", None),
    )
