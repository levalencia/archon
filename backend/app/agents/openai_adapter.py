"""OpenAI adapter using the Chat Completions HTTP API."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx
import structlog

from app.observability.logging import safe_value_metadata
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract

logger = structlog.get_logger()

_MODEL_IDENTITY_RE = re.compile(r"[A-Za-z0-9._:/-]{1,128}\Z")

OpenAIAdapterErrorCode = Literal["invalid_response", "invalid_tool_arguments"]


class OpenAIAdapterError(ValueError):
    """A sanitized failure to decode an OpenAI response."""

    def __init__(self, code: OpenAIAdapterErrorCode) -> None:
        self.code = code
        message = {
            "invalid_response": "Invalid OpenAI response",
            "invalid_tool_arguments": "Invalid OpenAI tool arguments",
        }[code]
        super().__init__(message)


def _invalid_response() -> OpenAIAdapterError:
    return OpenAIAdapterError("invalid_response")


def _model_identity(value: object, *, fallback: object = "unknown") -> str:
    """Return only a bounded model identifier suitable for metadata and logs."""
    if type(value) is str and _MODEL_IDENTITY_RE.fullmatch(value):
        return value
    if type(fallback) is str and _MODEL_IDENTITY_RE.fullmatch(fallback):
        return fallback
    return "unknown"


def _plain_json(value: Any, *, seen: frozenset[int] = frozenset()) -> Any:
    """Return JSON containers without mapping proxies, tuples, or exotic leaves."""
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in seen:
            raise TypeError("JSON value must not contain cycles")
        nested_seen = seen | {identity}
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise TypeError("JSON object keys must be strings")
            return {key: _plain_json(item, seen=nested_seen) for key, item in value.items()}
        return [_plain_json(item, seen=nested_seen) for item in value]
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _schema_name(contract: ResponseContract) -> str:
    """Build a deterministic OpenAI-safe (and at most 64 character) schema name."""
    source = f"{contract.schema_id}_{contract.schema_version}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", source).strip("_-") or "response"
    if len(safe) <= 64:
        return safe
    digest = hashlib.sha256(source.encode()).hexdigest()[:12]
    return f"{safe[:51]}_{digest}"


def _canonical_arguments(arguments: Mapping[str, Any]) -> str:
    return json.dumps(
        _plain_json(arguments),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _image_url(image: str) -> str:
    return image if image.startswith("data:") else f"data:image/jpeg;base64,{image}"


def _message_payload(message: Message) -> dict[str, Any]:
    if message.images and message.role is not Role.USER:
        raise ValueError("OpenAI images are only supported on user messages")
    if message.role is Role.USER and message.images:
        image_content: list[dict[str, Any]] = [{"type": "text", "text": message.content}]
        image_content.extend(
            {"type": "image_url", "image_url": {"url": _image_url(image)}}
            for image in message.images
        )
        content: str | list[dict[str, Any]] = image_content
    else:
        content = message.content

    payload: dict[str, Any] = {"role": message.role.value, "content": content}
    if message.role is Role.ASSISTANT and message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": _canonical_arguments(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    if message.role is Role.TOOL:
        if not message.tool_call_id:
            raise ValueError("OpenAI tool result messages require tool_call_id")
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": _plain_json(tool.input_schema),
        },
    }


def _nonnegative_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _invalid_response()
    return value


def _usage(payload: object) -> TokenUsage:
    if payload is None:
        return TokenUsage()
    if type(payload) is not dict:
        raise _invalid_response()

    prompt_tokens = _nonnegative_count(payload.get("prompt_tokens", 0))
    completion_tokens = _nonnegative_count(payload.get("completion_tokens", 0))
    cache_read: int | None = None
    if "prompt_tokens_details" in payload:
        details = payload["prompt_tokens_details"]
        if type(details) is not dict:
            raise _invalid_response()
        if "cached_tokens" in details:
            cache_read = _nonnegative_count(details["cached_tokens"])
            if cache_read > prompt_tokens:
                raise _invalid_response()
    return TokenUsage(prompt_tokens, completion_tokens, cache_read, None)


def _parse_tool_calls(payload: object) -> tuple[ToolCall, ...]:
    if payload is None:
        return ()
    if type(payload) is not list:
        raise _invalid_response()

    calls: list[ToolCall] = []
    call_ids: set[str] = set()
    for item in payload:
        if type(item) is not dict or item.get("type") != "function":
            raise _invalid_response()
        call_id = item.get("id")
        function = item.get("function")
        if (
            type(call_id) is not str
            or not call_id.strip()
            or call_id in call_ids
            or type(function) is not dict
        ):
            raise _invalid_response()
        call_ids.add(call_id)
        name = function.get("name")
        encoded_arguments = function.get("arguments")
        if type(name) is not str or not name or type(encoded_arguments) is not str:
            raise _invalid_response()
        try:
            decoded_arguments = json.loads(
                encoded_arguments,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
            if type(decoded_arguments) is not dict:
                raise TypeError
            arguments = _plain_json(decoded_arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise OpenAIAdapterError("invalid_tool_arguments") from None
        calls.append(ToolCall(call_id, name, arguments))
    return tuple(calls)


def _parse_response(data: object, *, configured_model: str) -> ModelResponse:
    try:
        if type(data) is not dict:
            raise _invalid_response()
        choices = data.get("choices")
        if type(choices) is not list or not choices or type(choices[0]) is not dict:
            raise _invalid_response()
        choice = choices[0]
        message = choice.get("message")
        if type(message) is not dict:
            raise _invalid_response()
        content = message.get("content")
        if content is not None and type(content) is not str:
            raise _invalid_response()
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and type(finish_reason) is not str:
            raise _invalid_response()
        response_model = _model_identity(data.get("model"), fallback=configured_model)
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            usage=_usage(data.get("usage")),
            provider_stop_reason=finish_reason,
            actual_provider="openai",
            actual_model=response_model,
        )
    except OpenAIAdapterError:
        raise
    except (KeyError, TypeError, ValueError):
        raise _invalid_response() from None


class OpenAIAdapter:
    """OpenAI-compatible adapter with legacy and typed provider boundaries."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        *,
        native_tools_enabled: bool = False,
        images_enabled: bool = False,
        json_mode_enabled: bool = False,
        json_schema_enabled: bool = False,
        cache_usage_enabled: bool = False,
    ) -> None:
        self.model = model
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.capabilities = ProviderCapabilities(
            native_tools=native_tools_enabled,
            images=images_enabled,
            json_mode=json_mode_enabled or json_schema_enabled,
            json_schema=json_schema_enabled,
            prompt_caching=False,
            cache_usage=cache_usage_enabled,
            usage=True,
            stop_reason=True,
            streaming=False,
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        logger.info(
            "openai_adapter_init",
            model=_model_identity(model),
            **safe_value_metadata("base_url", self.base_url),
        )

    async def _send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        try:
            data = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            raise _invalid_response() from None
        if type(data) is not dict:
            raise _invalid_response()
        return data

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
    ) -> ModelResponse:
        """Complete a typed request using native OpenAI tools and content parts."""
        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_payload(message) for message in messages],
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        if response_contract is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(response_contract),
                    "schema": _plain_json(response_contract.json_schema),
                    "strict": True,
                },
            }
        elif response_format is not None:
            payload["response_format"] = {"type": "json_object"}

        data = await self._send(payload)
        result = _parse_response(data, configured_model=self.model)
        logger.info(
            "openai_complete",
            model=result.actual_model,
            input_messages=len(messages),
            tool_calls=len(result.tool_calls),
        )
        return result

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Preserve the legacy text API, including its temperature request field."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        result = _parse_response(await self._send(payload), configured_model=self.model)
        logger.info("openai_chat_complete", model=result.actual_model, input_messages=len(messages))
        return result.content or ""
