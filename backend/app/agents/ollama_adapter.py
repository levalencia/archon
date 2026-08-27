"""Ollama adapter for the native, non-streaming ``/api/chat`` API."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import httpx
import structlog

from app.observability.logging import safe_value_metadata
from app.runtime.capabilities import ProviderCapabilities, UnsupportedProviderCapability
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract

logger = structlog.get_logger()

_MODEL_IDENTITY_RE = re.compile(r"[A-Za-z0-9._:/-]{1,128}\Z")
_DATA_IMAGE_RE = re.compile(r"\Adata:image/[A-Za-z0-9.+-]+;base64,(.*)\Z", re.DOTALL)
OllamaAdapterErrorCode = Literal["invalid_response", "invalid_tool_arguments"]


class OllamaAdapterError(ValueError):
    """A stable, sanitized failure to decode an Ollama response."""

    def __init__(self, code: OllamaAdapterErrorCode) -> None:
        self.code = code
        message = {
            "invalid_response": "Invalid Ollama response",
            "invalid_tool_arguments": "Invalid Ollama tool arguments",
        }[code]
        super().__init__(message)


def _invalid_response() -> OllamaAdapterError:
    return OllamaAdapterError("invalid_response")


def _model_identity(value: object, *, fallback: object = "unknown") -> str:
    """Return a bounded model identifier safe for metadata and logs."""
    if type(value) is str and _MODEL_IDENTITY_RE.fullmatch(value):
        return value
    if type(fallback) is str and _MODEL_IDENTITY_RE.fullmatch(fallback):
        return fallback
    return "unknown"


def _plain_json(value: Any, *, seen: frozenset[int] = frozenset()) -> Any:
    """Copy a recursively finite JSON value into only plain Python containers."""
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
    raise TypeError("unsupported JSON value")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _plain_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _image_data(image: str) -> str:
    match = _DATA_IMAGE_RE.fullmatch(image)
    return match.group(1) if match is not None else image


def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": _plain_json(tool.input_schema),
        },
    }


def _typed_messages(messages: Sequence[Message]) -> tuple[list[dict[str, Any]], bool]:
    """Convert typed history, retaining tool-result identity through ``tool_name``."""
    payloads: list[dict[str, Any]] = []
    historical_tools: dict[str, str] = {}
    has_images = False

    for message in messages:
        if message.images and message.role is not Role.USER:
            raise ValueError("Ollama images are only supported on user messages")

        payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
        if message.images:
            has_images = True
            payload["images"] = [_image_data(image) for image in message.images]

        if message.role is Role.ASSISTANT and message.tool_calls:
            calls: list[dict[str, Any]] = []
            for call in message.tool_calls:
                if call.id in historical_tools:
                    raise ValueError("Ollama tool call history contains duplicate IDs")
                historical_tools[call.id] = call.name
                calls.append(
                    {
                        "function": {
                            "name": call.name,
                            "arguments": _plain_json(call.arguments),
                        }
                    }
                )
            payload["tool_calls"] = calls

        if message.role is Role.TOOL:
            if not message.tool_call_id or message.tool_call_id not in historical_tools:
                raise ValueError("Ollama tool results require a known prior tool_call_id")
            payload["tool_name"] = historical_tools[message.tool_call_id]

        payloads.append(payload)
    return payloads, has_images


def _nonnegative_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _invalid_response()
    return value


def _tool_arguments(value: object) -> dict[str, Any]:
    try:
        decoded: object
        if type(value) is str:
            decoded = json.loads(
                value,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        else:
            decoded = value
        if not isinstance(decoded, Mapping):
            raise TypeError
        plain = _plain_json(decoded)
        if type(plain) is not dict:
            raise TypeError
        return plain
    except (json.JSONDecodeError, TypeError, ValueError):
        raise OllamaAdapterError("invalid_tool_arguments") from None


def _generated_call_id(name: str, arguments: Mapping[str, Any], index: int) -> str:
    source = f"{index}\0{name}\0{_canonical_json(arguments)}"
    return f"ollama_call_{hashlib.sha256(source.encode()).hexdigest()[:20]}"


def _parse_tool_calls(payload: object) -> tuple[ToolCall, ...]:
    if payload is None:
        return ()
    if type(payload) is not list:
        raise _invalid_response()

    calls: list[ToolCall] = []
    call_ids: set[str] = set()
    for index, item in enumerate(payload):
        if type(item) is not dict:
            raise _invalid_response()
        if "type" in item and item["type"] != "function":
            raise _invalid_response()
        function = item.get("function")
        if type(function) is not dict:
            raise _invalid_response()
        name = function.get("name")
        if type(name) is not str or not name:
            raise _invalid_response()
        arguments = _tool_arguments(function.get("arguments"))

        supplied_id = item.get("id")
        if "id" in item:
            if type(supplied_id) is not str or not supplied_id.strip():
                raise _invalid_response()
            call_id = supplied_id
        else:
            call_id = _generated_call_id(name, arguments, index)
            suffix = 1
            base_id = call_id
            while call_id in call_ids:
                call_id = f"{base_id}_{suffix}"
                suffix += 1
        if call_id in call_ids:
            raise _invalid_response()
        call_ids.add(call_id)
        calls.append(ToolCall(call_id, name, arguments))
    return tuple(calls)


def _parse_response(data: object, *, selected_model: str) -> ModelResponse:
    try:
        if type(data) is not dict:
            raise _invalid_response()
        message = data.get("message")
        if type(message) is not dict or message.get("role") != "assistant":
            raise _invalid_response()
        content = message.get("content")
        if content is not None and type(content) is not str:
            raise _invalid_response()
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        if content is None and not tool_calls:
            raise _invalid_response()
        done_reason = data.get("done_reason")
        if done_reason is not None and type(done_reason) is not str:
            raise _invalid_response()
        prompt_tokens = _nonnegative_count(data.get("prompt_eval_count", 0))
        completion_tokens = _nonnegative_count(data.get("eval_count", 0))
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(prompt_tokens, completion_tokens),
            provider_stop_reason=done_reason,
            actual_provider="ollama",
            actual_model=_model_identity(data.get("model"), fallback=selected_model),
        )
    except OllamaAdapterError:
        raise
    except (KeyError, TypeError, ValueError):
        raise _invalid_response() from None


class OllamaAdapter:
    """Typed Ollama adapter with explicit, model-dependent capability opt-ins.

    Ollama's current chat request can carry both ``tools`` and user-message
    ``images``. This adapter therefore sends that combination faithfully when
    both capabilities are explicitly configured; it never drops either field.
    """

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
        *,
        native_tools_enabled: bool = False,
        vision_model: str | None = None,
        json_mode_enabled: bool = False,
        json_schema_enabled: bool = False,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.vision_model = vision_model.strip() if vision_model and vision_model.strip() else None
        self.capabilities = ProviderCapabilities(
            native_tools=native_tools_enabled,
            images=self.vision_model is not None,
            json_mode=json_mode_enabled or json_schema_enabled,
            json_schema=json_schema_enabled,
            prompt_caching=False,
            cache_usage=False,
            usage=True,
            stop_reason=True,
            streaming=False,
        )
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)
        logger.info(
            "ollama_adapter_init",
            model=_model_identity(model),
            vision_configured=self.vision_model is not None,
            **safe_value_metadata("base_url", self.base_url),
        )

    def _require(self, capability: str, available: bool) -> None:
        if not available:
            raise UnsupportedProviderCapability("ollama", (capability,))

    async def _send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/api/chat", json=payload)
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
        max_tokens: int = 2048,
        response_contract: ResponseContract | None = None,
        response_format: str | None = None,
    ) -> ModelResponse:
        """Complete a typed request using Ollama's non-streaming chat endpoint."""
        if response_contract is not None and response_format is not None:
            raise ValueError("response_contract and response_format are mutually exclusive")

        converted_messages, has_images = _typed_messages(messages)
        if tools:
            self._require("native_tools", self.capabilities.native_tools)
        if has_images:
            self._require("images", self.capabilities.images)
        if response_contract is not None:
            self._require("json_schema", self.capabilities.json_schema)
        elif response_format is not None:
            self._require("json_mode", self.capabilities.json_mode)

        selected_model = self.vision_model if has_images else self.model
        if selected_model is None:  # narrowed by the explicit image capability check above
            raise UnsupportedProviderCapability("ollama", ("images",))
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": converted_messages,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        if response_contract is not None:
            payload["format"] = _plain_json(response_contract.json_schema)
        elif response_format is not None:
            payload["format"] = "json"

        result = _parse_response(await self._send(payload), selected_model=selected_model)
        logger.info(
            "ollama_complete",
            model=result.actual_model,
            input_messages=len(messages),
            tool_calls=len(result.tool_calls),
            has_images=has_images,
        )
        return result

    async def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 2048,
        tools: list[dict[str, Any]] | None = None,
        images: list[str] | None = None,
    ) -> str:
        """Preserve the legacy dict/string API without mutating caller messages."""
        converted = copy.deepcopy(messages)
        has_images = bool(images) or any(bool(message.get("images")) for message in converted)
        if has_images and self.vision_model is None:
            raise UnsupportedProviderCapability("ollama", ("images",))
        if images:
            for message in reversed(converted):
                if message.get("role") == "user":
                    message["images"] = [_image_data(image) for image in images]
                    break
            else:
                raise ValueError("Ollama images require a user message")
        for message in converted:
            message_images = message.get("images")
            if message_images:
                if message.get("role") != "user":
                    raise ValueError("Ollama images are only supported on user messages")
                message["images"] = [_image_data(image) for image in message_images]

        selected_model = self.vision_model if has_images else self.model
        if selected_model is None:
            raise UnsupportedProviderCapability("ollama", ("images",))
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": converted,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for tool in tools
            ]

        result = _parse_response(await self._send(payload), selected_model=selected_model)
        if result.tool_calls:
            return json.dumps(
                {
                    "tool_calls": [
                        {"tool": call.name, "args": dict(call.arguments)}
                        for call in result.tool_calls
                    ]
                }
            )
        return result.content or ""
