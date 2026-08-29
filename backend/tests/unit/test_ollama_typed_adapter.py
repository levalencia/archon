"""Typed Ollama /api/chat adapter contract tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agents.llm_factory import _create_single_client
from app.agents.ollama_adapter import OllamaAdapter, OllamaAdapterError
from app.config import Settings
from app.runtime.capabilities import ProviderCapabilities, UnsupportedProviderCapability
from app.runtime.models import Message, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.structured_output import ResponseContract


def adapter_with_response(
    payload: object,
    requests: list[httpx.Request],
    **kwargs: object,
) -> OllamaAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    adapter = OllamaAdapter(model="configured-model", **kwargs)
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
    )
    return adapter


def response(*, message: object = None, **extra: object) -> dict[str, object]:
    return {
        "message": message if message is not None else {"role": "assistant", "content": "ok"},
        "done_reason": "stop",
        **extra,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_typed_text_request_response_usage_stop_and_actual_model() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(
            message={"role": "assistant", "content": "Hello"},
            prompt_eval_count=12,
            eval_count=3,
            model="llama3.2:latest",
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
        "stream": False,
        "options": {"num_predict": 77},
    }
    assert result.content == "Hello"
    assert result.usage == TokenUsage(12, 3)
    assert result.provider_stop_reason == "stop"
    assert result.actual_provider == "ollama"
    assert result.actual_model == "llama3.2:latest"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tools_history_and_results_use_native_ollama_shapes() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(
            message={
                "role": "assistant",
                "content": "Checking.",
                "tool_calls": [{"function": {"name": "weather", "arguments": '{"city":"Ghent"}'}}],
            }
        ),
        requests,
        native_tools_enabled=True,
    )
    historical = ToolCall("call-1", "weather", {"units": "c", "city": "Paris"})
    result = await adapter.complete(
        [
            Message(Role.USER, "Paris weather?"),
            Message(Role.ASSISTANT, "", tool_calls=(historical,)),
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
            {"function": {"name": "weather", "arguments": {"city": "Paris", "units": "c"}}}
        ],
    }
    assert payload["messages"][2] == {
        "role": "tool",
        "content": '{"temp":20}',
        "tool_name": "weather",
    }
    assert result.content == "Checking."
    assert result.tool_calls[0].name == "weather"
    assert result.tool_calls[0].arguments == {"city": "Ghent"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_tool_call_ids_are_deterministic_unique_and_safe() -> None:
    calls = [
        {"function": {"name": "weather", "arguments": {"city": "Ghent"}}},
        {"function": {"name": "weather", "arguments": {"city": "Ghent"}}},
    ]
    adapter = adapter_with_response(
        response(message={"role": "assistant", "content": "", "tool_calls": calls}),
        [],
        native_tools_enabled=True,
    )
    first = await adapter.complete([Message(Role.USER, "hi")])
    second = await adapter.complete([Message(Role.USER, "hi")])

    first_ids = [call.id for call in first.tool_calls]
    assert first_ids == [call.id for call in second.tool_calls]
    assert len(set(first_ids)) == 2
    assert all(
        identifier.startswith("ollama_call_") and identifier.isascii() for identifier in first_ids
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["", "   "])
async def test_blank_tool_definition_names_fail_before_network(name: str) -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests, native_tools_enabled=True)

    with pytest.raises(OllamaAdapterError) as typed_error:
        await adapter.complete([Message(Role.USER, "go")], [ToolDefinition(name)])
    with pytest.raises(OllamaAdapterError) as legacy_error:
        await adapter.chat(
            [{"role": "user", "content": "go"}],
            tools=[{"name": name, "parameters": {"type": "object"}}],
        )

    assert typed_error.value.code == "invalid_tool_definition"
    assert legacy_error.value.code == "invalid_tool_definition"
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_generated_tool_ids_are_namespaced_across_accumulated_history() -> None:
    requests: list[httpx.Request] = []
    repeated_call = [{"function": {"name": "weather", "arguments": {"city": "Ghent"}}}]
    adapter = adapter_with_response(
        response(message={"role": "assistant", "content": "", "tool_calls": repeated_call}),
        requests,
        native_tools_enabled=True,
    )
    history = [Message(Role.USER, "weather?")]

    first = await adapter.complete(history)
    history.extend(
        [
            Message(Role.ASSISTANT, "", tool_calls=first.tool_calls),
            Message(Role.TOOL, '{"temp":20}', tool_call_id=first.tool_calls[0].id),
            Message(Role.USER, "weather?"),
        ]
    )
    second = await adapter.complete(history)

    assert first.tool_calls[0].id != second.tool_calls[0].id
    assert json.loads(requests[1].content)["messages"][2]["tool_name"] == "weather"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_images_use_explicit_vision_model_and_validated_base64() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(),
        requests,
        native_tools_enabled=True,
        vision_model="llava:7b",
        vision_native_tools_enabled=True,
    )
    await adapter.complete(
        [Message(Role.USER, "Describe", images=("data:image/png;base64,YWJj", "cmF3"))],
        [ToolDefinition("inspect", input_schema={"type": "object"})],
    )

    payload = json.loads(requests[0].content)
    assert payload["model"] == "llava:7b"
    assert payload["messages"] == [
        {"role": "user", "content": "Describe", "images": ["YWJj", "cmF3"]}
    ]
    assert payload["tools"][0]["function"]["name"] == "inspect"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "image",
    [
        "",
        "not-base64!",
        "YWJj=",
        "data:image/png;base64,",
        "data:image/png;base64,YWJj!",
        "data:image/svg+xml;base64,YWJj",
        "data:text/plain;base64,YWJj",
        "data:image/png,YWJj",
    ],
)
async def test_invalid_or_unsupported_images_fail_safely_before_network(image: str) -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests, vision_model="llava")

    with pytest.raises(OllamaAdapterError) as raised:
        await adapter.complete([Message(Role.USER, "secret", images=(image,))])

    assert raised.value.code == "invalid_image"
    assert str(raised.value) == "Invalid Ollama image"
    if image:
        assert image not in str(raised.value)
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_native_tool_protocol_requires_opt_in_even_without_tools_argument() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests)
    call = ToolCall("call-1", "weather", {})

    cases = (
        ([Message(Role.USER, "request")], [ToolDefinition("weather")]),
        ([Message(Role.ASSISTANT, "", tool_calls=(call,))], []),
        ([Message(Role.TOOL, "result", tool_call_id="call-1")], []),
        ([Message(Role.USER, "bad", tool_call_id="call-1")], []),
    )
    for history, tools in cases:
        with pytest.raises(UnsupportedProviderCapability) as raised:
            await adapter.complete(history, tools)
        assert raised.value.missing_capabilities == ("native_tools",)
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_tools_require_independent_combined_opt_in() -> None:
    requests: list[httpx.Request] = []
    image_message = Message(Role.USER, "describe", images=("YWJj",))
    adapter = adapter_with_response(
        response(), requests, vision_model="llava", native_tools_enabled=True
    )

    with pytest.raises(UnsupportedProviderCapability) as raised:
        await adapter.complete([image_message], [ToolDefinition("inspect")])
    assert raised.value.missing_capabilities == ("vision_native_tools",)

    historical_call = ToolCall("call-1", "inspect", {})
    with pytest.raises(UnsupportedProviderCapability) as history_raised:
        await adapter.complete(
            [
                Message(Role.ASSISTANT, "", tool_calls=(historical_call,)),
                Message(Role.TOOL, "done", tool_call_id="call-1"),
                image_message,
            ]
        )
    assert history_raised.value.missing_capabilities == ("vision_native_tools",)
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        Message(Role.USER, "bad", tool_calls=(ToolCall("call-1", "tool", {}),)),
        Message(Role.ASSISTANT, "bad", tool_call_id="call-1"),
        Message(Role.ASSISTANT, "", tool_calls=(ToolCall("   ", "tool", {}),)),
        Message(Role.TOOL, "bad"),
        Message(Role.TOOL, "bad", tool_call_id="   "),
        Message(Role.TOOL, "bad", tool_call_id="call-1", tool_calls=(ToolCall("x", "tool", {}),)),
    ],
)
async def test_invalid_typed_tool_field_roles_fail_before_network(message: Message) -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests, native_tools_enabled=True)

    with pytest.raises(ValueError, match="Ollama tool"):
        await adapter.complete([message])
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_images_without_model_and_non_user_images_fail_before_network() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests)
    with pytest.raises(UnsupportedProviderCapability) as missing:
        await adapter.complete([Message(Role.USER, "Describe", images=("abc",))])
    assert missing.value.missing_capabilities == ("images",)

    adapter = adapter_with_response(response(), requests, vision_model="llava")
    with pytest.raises(ValueError, match="only supported on user messages"):
        await adapter.complete([Message(Role.ASSISTANT, "bad", images=("abc",))])
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_json_schema_and_json_mode_use_ollama_format() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(), requests, json_mode_enabled=True, json_schema_enabled=True
    )
    contract = ResponseContract(
        "answer", "v1", {"type": "object", "required": ("answer",)}, lambda value: value
    )
    await adapter.complete([Message(Role.USER, "answer")], response_contract=contract)
    await adapter.complete([Message(Role.USER, "answer")], response_format="json")

    assert json.loads(requests[0].content)["format"] == {
        "type": "object",
        "required": ["answer"],
    }
    assert json.loads(requests[1].content)["format"] == "json"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_contract_and_format_are_mutually_exclusive_before_network() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(response(), requests, json_schema_enabled=True)
    contract = ResponseContract("answer", "v1", {"type": "object"}, lambda value: value)
    with pytest.raises(ValueError, match="mutually exclusive"):
        await adapter.complete(
            [Message(Role.USER, "hi")], response_contract=contract, response_format="json"
        )
    assert requests == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"message": "bad"},
        response(message={"role": "assistant", "content": []}),
        response(prompt_eval_count=-1),
        response(eval_count=True),
        response(done_reason=3),
    ],
)
async def test_malformed_response_is_a_stable_sanitized_error(payload: object) -> None:
    adapter = adapter_with_response(payload, [])
    with pytest.raises(OllamaAdapterError, match="Invalid Ollama response") as raised:
        await adapter.complete([Message(Role.USER, "secret")])
    assert "secret" not in str(raised.value)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    ["not json", "[]", "null", '{"value":NaN}', '{"value":1e999}'],
)
async def test_bad_tool_arguments_are_strict_sanitized(arguments: object) -> None:
    adapter = adapter_with_response(
        response(
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [{"function": {"name": "weather", "arguments": arguments}}],
            }
        ),
        [],
        native_tools_enabled=True,
    )
    with pytest.raises(OllamaAdapterError) as raised:
        await adapter.complete([Message(Role.USER, "hi")])
    assert raised.value.code == "invalid_tool_arguments"
    assert str(raised.value) == "Invalid Ollama tool arguments"
    assert raised.value.__cause__ is None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("second_id", ["call-1", "   "])
async def test_supplied_duplicate_or_blank_tool_ids_are_rejected(second_id: str) -> None:
    calls = [
        {"id": "call-1", "function": {"name": "weather", "arguments": {}}},
        {"id": second_id, "function": {"name": "weather", "arguments": {}}},
    ]
    adapter = adapter_with_response(
        response(message={"role": "assistant", "content": "", "tool_calls": calls}),
        [],
        native_tools_enabled=True,
    )
    with pytest.raises(OllamaAdapterError, match="Invalid Ollama response"):
        await adapter.complete([Message(Role.USER, "hi")])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_blank_response_tool_name_is_rejected() -> None:
    adapter = adapter_with_response(
        response(
            message={
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "   ", "arguments": {}}}],
            }
        ),
        [],
        native_tools_enabled=True,
    )
    with pytest.raises(OllamaAdapterError, match="Invalid Ollama response"):
        await adapter.complete([Message(Role.USER, "hi")])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_actual_model_is_sanitized_and_bounded() -> None:
    adapter = adapter_with_response(response(model="unsafe model\nsecret"), [])
    result = await adapter.complete([Message(Role.USER, "hi")])
    assert result.actual_model == "configured-model"


@pytest.mark.unit
def test_capabilities_default_and_opt_ins_are_conservative() -> None:
    assert OllamaAdapter().capabilities == ProviderCapabilities(
        native_tools=False,
        images=False,
        json_mode=False,
        json_schema=False,
        prompt_caching=False,
        cache_usage=False,
        usage=True,
        stop_reason=True,
        streaming=False,
    )
    enabled = OllamaAdapter(
        native_tools_enabled=True,
        vision_model=" llava:7b ",
        vision_native_tools_enabled=True,
        json_schema_enabled=True,
    )
    assert enabled.capabilities.native_tools is True
    assert enabled.capabilities.images is True
    assert enabled.capabilities.json_schema is True
    assert enabled.capabilities.json_mode is True
    assert enabled.vision_native_tools_enabled is True


@pytest.mark.unit
def test_factory_forwards_only_ollama_opt_ins() -> None:
    settings = Settings(
        llm_provider="ollama",
        ollama_native_tools_enabled=True,
        ollama_vision_model="llava:7b",
        ollama_vision_native_tools_enabled=True,
        ollama_json_schema_enabled=True,
    )
    assert settings.ollama_json_mode_enabled is True
    adapter = _create_single_client("ollama", settings)
    assert isinstance(adapter, OllamaAdapter)
    assert adapter.vision_model == "llava:7b"
    assert adapter.capabilities.native_tools is True
    assert adapter.capabilities.images is True
    assert adapter.capabilities.json_mode is True
    assert adapter.capabilities.json_schema is True
    assert adapter.vision_native_tools_enabled is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_legacy_chat_keeps_tools_images_and_does_not_mutate_messages() -> None:
    requests: list[httpx.Request] = []
    adapter = adapter_with_response(
        response(),
        requests,
        vision_model="llava",
        native_tools_enabled=True,
        vision_native_tools_enabled=True,
    )
    messages = [{"role": "user", "content": "describe"}]
    original = json.loads(json.dumps(messages))
    result = await adapter.chat(
        messages,
        max_tokens=123,
        tools=[{"name": "inspect", "parameters": {"type": "object"}}],
        images=["data:image/jpeg;base64,YWJj"],
    )

    assert result == "ok"
    assert messages == original
    payload = json.loads(requests[0].content)
    assert payload["model"] == "llava"
    assert payload["messages"][0]["images"] == ["YWJj"]
    assert payload["tools"][0]["function"]["name"] == "inspect"
    assert payload["options"] == {"num_predict": 123}
