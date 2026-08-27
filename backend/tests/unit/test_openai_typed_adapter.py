"""Typed OpenAI Chat Completions adapter contract tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.openai_adapter import OpenAIAdapter, OpenAIAdapterError
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract


def adapter_with_response(payload: object, requests: list[httpx.Request]) -> OpenAIAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    adapter = OpenAIAdapter("test", model="configured-model")
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.openai.com/v1"
    )
    return adapter


def response(*, message: dict | None = None, **extra: object) -> dict:
    return {
        "choices": [
            {
                "message": message or {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
        **extra,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_typed_text_request_response_and_usage() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(
            message={"role": "assistant", "content": "Hello"},
            usage={"prompt_tokens": 12, "completion_tokens": 3},
        ),
        requests,
    )

    result = await adapter.complete(
        [Message(Role.SYSTEM, "Be concise"), Message(Role.USER, "Hi")], max_tokens=77
    )

    assert json.loads(requests[0].content) == {
        "model": "configured-model",
        "messages": [
            {"role": "system", "content": "Be concise"},
            {"role": "user", "content": "Hi"},
        ],
        "max_tokens": 77,
    }
    assert result.content == "Hello"
    assert result.usage == TokenUsage(12, 3)
    assert result.provider_stop_reason == "stop"
    assert result.actual_provider == "openai"
    assert result.actual_model == "configured-model"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tools_request_response_and_history_are_native_and_canonical() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(
            message={
                "role": "assistant",
                "content": "Checking.",
                "tool_calls": [
                    {
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": '{"city":"Ghent"}',
                        },
                    }
                ],
            }
        ),
        requests,
    )
    historical_call = ToolCall("call-1", "weather", {"units": "c", "city": "Paris"})

    result = await adapter.complete(
        [
            Message(Role.USER, "Paris weather?"),
            Message(Role.ASSISTANT, "", tool_calls=(historical_call,)),
            Message(Role.TOOL, '{"temp":20}', tool_call_id="call-1"),
            Message(Role.USER, "And Ghent?"),
        ],
        [
            ToolDefinition(
                "weather",
                "Look up weather",
                {"type": "object", "properties": {"city": {"type": "string"}}},
            )
        ],
    )

    payload = json.loads(requests[0].content)
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "weather",
                "description": "Look up weather",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            },
        }
    ]
    assert payload["messages"][1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "weather",
                    "arguments": '{"city":"Paris","units":"c"}',
                },
            }
        ],
    }
    assert payload["messages"][2] == {
        "role": "tool",
        "content": '{"temp":20}',
        "tool_call_id": "call-1",
    }
    assert result.content == "Checking."
    assert result.tool_calls == (ToolCall("call-2", "weather", {"city": "Ghent"}),)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_user_images_preserve_data_urls_and_prefix_raw_base64() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests)

    await adapter.complete(
        [
            Message(
                Role.USER,
                "Describe",
                images=("data:image/png;base64,abc", "raw-base64"),
            )
        ]
    )

    assert json.loads(requests[0].content)["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,raw-base64"},
                },
            ],
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_native_json_schema_and_legacy_json_mode() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests)
    contract = ResponseContract(
        "answer/schema",
        "v1.0",
        {"type": "object", "required": ("answer",), "properties": {"answer": {"type": "string"}}},
        lambda value: value,
    )

    await adapter.complete([Message(Role.USER, "answer")], response_contract=contract)
    await adapter.complete([Message(Role.USER, "answer")], response_format="json")

    schema_format = json.loads(requests[0].content)["response_format"]
    assert schema_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "answer_schema_v1_0",
            "schema": {
                "type": "object",
                "required": ["answer"],
                "properties": {"answer": {"type": "string"}},
            },
            "strict": True,
        },
    }
    assert json.loads(requests[1].content)["response_format"] == {"type": "json_object"}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details, expected", [(None, None), ({"cached_tokens": 0}, 0), ({"cached_tokens": 7}, 7)]
)
async def test_cache_usage_absent_zero_and_value(details: object, expected: int | None) -> None:
    requests: list[httpx.Request] = []
    usage: dict[str, object] = {"prompt_tokens": 12, "completion_tokens": 3}
    if details is not None:
        usage["prompt_tokens_details"] = details
    adapter = adapter_with_response(response(usage=usage), requests)

    result = await adapter.complete([Message(Role.USER, "hi")])

    assert result.usage == TokenUsage(12, 3, expected, None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_response_model_overrides_configured_model() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(model="gpt-4.1-2026", usage={}), requests)

    result = await adapter.complete([Message(Role.USER, "hi")])

    assert result.actual_model == "gpt-4.1-2026"
    assert result.actual_provider == "openai"
    assert result.provider_stop_reason == "stop"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": "bad"}]},
        response(usage={"prompt_tokens": -1, "completion_tokens": 2}),
        response(usage={"prompt_tokens": True, "completion_tokens": 2}),
    ],
)
async def test_malformed_response_shapes_raise_stable_typed_error(payload: object) -> None:
    adapter = adapter_with_response(payload, [])

    with pytest.raises(OpenAIAdapterError, match="Invalid OpenAI response"):
        await adapter.complete([Message(Role.USER, "secret prompt")])


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ["not secret valid json", "[]", "null", "1"])
async def test_malformed_or_non_object_tool_arguments_do_not_leak_raw_content(
    arguments: str,
) -> None:
    adapter = adapter_with_response(
        response(
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "weather", "arguments": arguments},
                    }
                ],
            }
        ),
        [],
    )

    with pytest.raises(OpenAIAdapterError) as raised:
        await adapter.complete([Message(Role.USER, "secret prompt")])
    assert str(raised.value) == "Invalid OpenAI tool arguments"
    assert arguments not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_contract_and_format_are_mutually_exclusive_without_transport() -> None:
    adapter = adapter_with_response(response(), [])
    contract = ResponseContract("answer", "v1", {"type": "object"}, lambda value: value)

    with pytest.raises(ValueError, match="mutually exclusive"):
        await adapter.complete(
            [Message(Role.USER, "hi")], response_contract=contract, response_format="json"
        )


@pytest.mark.unit
def test_capabilities_are_explicit() -> None:
    adapter = OpenAIAdapter("test")
    assert adapter.capabilities == ProviderCapabilities(
        native_tools=True,
        images=True,
        json_mode=True,
        json_schema=True,
        prompt_caching=False,
        cache_usage=True,
        usage=True,
        stop_reason=True,
        streaming=False,
    )
