"""Unit tests for LLM adapters using deterministic SDK and HTTP transports."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.agents.anthropic_adapter import AnthropicAdapter
from app.agents.foundry_adapter import FoundryAdapter
from app.agents.mock_llm import MockLLM
from app.agents.ollama_adapter import OllamaAdapter
from app.agents.openai_adapter import OpenAIAdapter
from app.agents.protocols import LLMClient
from app.runtime.models import Message, Role, TokenUsage, ToolCall, ToolDefinition


class TestAdapterProtocolCompliance:
    """All adapters must satisfy LLMClient Protocol."""

    @pytest.mark.unit
    def test_openai_satisfies_protocol(self) -> None:
        assert isinstance(OpenAIAdapter(api_key="test", model="gpt-4o"), LLMClient)

    @pytest.mark.unit
    def test_anthropic_satisfies_protocol(self) -> None:
        assert isinstance(AnthropicAdapter(api_key="test"), LLMClient)

    @pytest.mark.unit
    def test_foundry_satisfies_protocol(self) -> None:
        adapter = FoundryAdapter(api_key="test", base_url="https://example.com")
        assert isinstance(adapter, LLMClient)

    @pytest.mark.unit
    def test_ollama_satisfies_protocol(self) -> None:
        assert isinstance(OllamaAdapter(model="llama3"), LLMClient)

    @pytest.mark.unit
    def test_mock_satisfies_protocol(self) -> None:
        assert isinstance(MockLLM(), LLMClient)


class TestOpenAIAdapter:
    """OpenAI adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_converts_request_and_parses_response(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "Hello from OpenAI!"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )

        adapter = OpenAIAdapter(api_key="test-key", model="gpt-4o")
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.openai.com/v1",
            headers={"Authorization": "Bearer test-key"},
        )
        messages = [{"role": "user", "content": "hi"}]

        result = await adapter.chat(messages, max_tokens=123, temperature=0.25)

        assert result == "Hello from OpenAI!"
        assert requests[0].url == "https://api.openai.com/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer test-key"
        assert json.loads(requests[0].content) == {
            "model": "gpt-4o",
            "messages": messages,
            "max_tokens": 123,
            "temperature": 0.25,
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_raises_on_error(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(401, json={"error": "unauthorized"})
        )
        adapter = OpenAIAdapter(api_key="bad-key", model="gpt-4o")
        adapter._client = httpx.AsyncClient(
            transport=transport, base_url="https://api.openai.com/v1"
        )

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.chat([{"role": "user", "content": "hi"}])


class TestAnthropicAdapter:
    """Anthropic adapter with a deterministic SDK transport."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_complete_converts_request_and_parses_tool_use(self, monkeypatch) -> None:
        import anthropic

        constructor: dict = {}
        request: dict = {}

        class Messages:
            async def create(self, **kwargs):
                request.update(kwargs)
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(type="text", text="Checking weather. "),
                        SimpleNamespace(
                            type="tool_use",
                            id="call-weather",
                            name="weather",
                            input={"city": "Ghent"},
                        ),
                    ],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    stop_reason="tool_use",
                )

        class Client:
            def __init__(self, **kwargs):
                constructor.update(kwargs)
                self.messages = Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", Client)
        adapter = AnthropicAdapter(api_key="test-key", model="claude-test")
        response = await adapter.complete(
            [Message(Role.SYSTEM, "Be concise"), Message(Role.USER, "Weather in Ghent?")],
            [
                ToolDefinition(
                    "weather",
                    "Look up weather",
                    {"type": "object", "properties": {"city": {"type": "string"}}},
                )
            ],
            max_tokens=123,
        )

        assert constructor == {"api_key": "test-key"}
        assert request == {
            "model": "claude-test",
            "system": [
                {
                    "type": "text",
                    "text": "Be concise",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": "Weather in Ghent?"}],
            "tools": [
                {
                    "name": "weather",
                    "description": "Look up weather",
                    "input_schema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                    },
                }
            ],
            "max_tokens": 123,
        }
        assert response.content == "Checking weather. "
        assert response.tool_calls == (ToolCall("call-weather", "weather", {"city": "Ghent"}),)
        assert response.usage == TokenUsage(10, 5)
        assert response.provider_stop_reason == "tool_use"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_system_message_extracted_with_http_transport(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"content": [{"type": "text", "text": "ok"}], "usage": {}},
            )

        adapter = AnthropicAdapter(api_key="test-key")
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.anthropic.com/v1"
        )
        await adapter.chat(
            [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "hi"},
            ]
        )

        payload = json.loads(requests[0].content)
        assert payload["system"] == [
            {
                "type": "text",
                "text": "You are helpful",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert payload["messages"] == [{"role": "user", "content": "hi"}]


class TestFoundryAdapter:
    """Foundry adapter with a deterministic SDK transport."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_converts_request_and_parses_response(self, monkeypatch) -> None:
        import anthropic

        constructor: dict = {}
        request: dict = {}

        class Messages:
            async def create(self, **kwargs):
                request.update(kwargs)
                return SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="Hello from Foundry!")],
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                    stop_reason="end_turn",
                )

        class Client:
            def __init__(self, **kwargs):
                constructor.update(kwargs)
                self.messages = Messages()

        monkeypatch.setattr(anthropic, "AsyncAnthropic", Client)
        adapter = FoundryAdapter(
            api_key="test-key",
            base_url="https://foundry.example.com/anthropic",
            model="foundry-claude",
        )

        result = await adapter.chat([{"role": "user", "content": "hi"}], max_tokens=321)

        assert result == "Hello from Foundry!"
        assert constructor == {
            "api_key": "test-key",
            "base_url": "https://foundry.example.com/anthropic",
        }
        assert request == {
            "model": "foundry-claude",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 321,
        }


class TestOllamaAdapter:
    """Ollama adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_converts_request_and_parses_response(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "message": {"role": "assistant", "content": "Hello from Ollama!"},
                    "eval_count": 42,
                },
            )

        adapter = OllamaAdapter(model="llama3")
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
        )
        messages = [{"role": "user", "content": "hi"}]

        result = await adapter.chat(messages, max_tokens=222)

        assert result == "Hello from Ollama!"
        assert requests[0].url == "http://localhost:11434/api/chat"
        assert json.loads(requests[0].content) == {
            "model": "llama3",
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 222},
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_converts_and_parses_tool_calls(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "weather",
                                    "arguments": {"city": "Ghent"},
                                }
                            }
                        ],
                    }
                },
            )

        adapter = OllamaAdapter(model="llama3", native_tools_enabled=True)
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="http://localhost:11434"
        )
        tools = [
            {
                "name": "weather",
                "description": "Look up weather",
                "parameters": {"type": "object", "required": ["city"]},
            }
        ]

        result = await adapter.chat([{"role": "user", "content": "weather?"}], tools=tools)

        assert json.loads(result) == {
            "tool_calls": [{"tool": "weather", "args": {"city": "Ghent"}}]
        }
        assert json.loads(requests[0].content)["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Look up weather",
                    "parameters": {"type": "object", "required": ["city"]},
                },
            }
        ]
