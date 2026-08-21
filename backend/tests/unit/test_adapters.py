"""Unit tests for LLM adapters. All use MockLLM or mock httpx responses."""
from __future__ import annotations

import json

import httpx
import pytest

from app.agents.anthropic_adapter import AnthropicAdapter
from app.agents.foundry_adapter import FoundryAdapter
from app.agents.mock_llm import MockLLM
from app.agents.ollama_adapter import OllamaAdapter
from app.agents.openai_adapter import OpenAIAdapter
from app.agents.protocols import LLMClient


class TestAdapterProtocolCompliance:
    """All adapters must satisfy LLMClient Protocol."""

    @pytest.mark.unit
    def test_openai_satisfies_protocol(self) -> None:
        adapter = OpenAIAdapter(api_key="test", model="gpt-4o")
        assert isinstance(adapter, LLMClient)

    @pytest.mark.unit
    def test_anthropic_satisfies_protocol(self) -> None:
        adapter = AnthropicAdapter(api_key="test")
        assert isinstance(adapter, LLMClient)

    @pytest.mark.unit
    def test_foundry_satisfies_protocol(self) -> None:
        adapter = FoundryAdapter(api_key="test", base_url="https://example.com")
        assert isinstance(adapter, LLMClient)

    @pytest.mark.unit
    def test_ollama_satisfies_protocol(self) -> None:
        adapter = OllamaAdapter(model="llama3")
        assert isinstance(adapter, LLMClient)

    @pytest.mark.unit
    def test_mock_satisfies_protocol(self) -> None:
        adapter = MockLLM()
        assert isinstance(adapter, LLMClient)


class TestOpenAIAdapter:
    """OpenAI adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_parses_response(self) -> None:
        mock_response = {
            "choices": [{"message": {"content": "Hello from OpenAI!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=mock_response)
        )
        adapter = OpenAIAdapter(api_key="test-key", model="gpt-4o")
        adapter._client = httpx.AsyncClient(
            transport=transport, base_url="https://api.openai.com/v1"
        )

        result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello from OpenAI!"

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
    """Anthropic adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_parses_response(self) -> None:
        mock_response = {
            "content": [{"type": "text", "text": "Hello from Claude!"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=mock_response)
        )
        adapter = AnthropicAdapter(api_key="test-key")
        adapter._client = httpx.AsyncClient(
            transport=transport, base_url="https://api.anthropic.com/v1"
        )

        result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello from Claude!"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_system_message_extracted(self) -> None:
        """Anthropic requires system message separate from messages list."""
        received_payloads: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            received_payloads.append(payload)
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {},
                },
            )

        transport = httpx.MockTransport(handler)
        adapter = AnthropicAdapter(api_key="test-key")
        adapter._client = httpx.AsyncClient(
            transport=transport, base_url="https://api.anthropic.com/v1"
        )

        await adapter.chat([
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
        ])

        payload = received_payloads[0]
        assert payload["system"] == "You are helpful"
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"


class TestFoundryAdapter:
    """Foundry adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_parses_response(self) -> None:
        mock_response = {
            "content": [{"type": "text", "text": "Hello from Foundry!"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=mock_response)
        )
        adapter = FoundryAdapter(
            api_key="test-key",
            base_url="https://foundry.example.com/anthropic",
        )
        adapter._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://foundry.example.com/anthropic",
        )

        result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello from Foundry!"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_uses_api_key_header(self) -> None:
        """Foundry uses api-key header, not Authorization Bearer."""
        received_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            received_headers.update(dict(request.headers))
            return httpx.Response(
                200,
                json={
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {},
                },
            )

        transport = httpx.MockTransport(handler)
        adapter = FoundryAdapter(
            api_key="my-foundry-key",
            base_url="https://foundry.example.com",
        )
        # Recreate client with mock transport but keep the api-key header
        adapter._client = httpx.AsyncClient(
            transport=transport,
            base_url="https://foundry.example.com",
            headers={
                "api-key": "my-foundry-key",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )

        await adapter.chat([{"role": "user", "content": "hi"}])
        assert received_headers.get("api-key") == "my-foundry-key"


class TestOllamaAdapter:
    """Ollama adapter with mocked HTTP responses."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_chat_parses_response(self) -> None:
        mock_response = {
            "message": {"role": "assistant", "content": "Hello from Ollama!"},
            "eval_count": 42,
        }

        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json=mock_response)
        )
        adapter = OllamaAdapter(model="llama3")
        adapter._client = httpx.AsyncClient(
            transport=transport, base_url="http://localhost:11434"
        )

        result = await adapter.chat([{"role": "user", "content": "hi"}])
        assert result == "Hello from Ollama!"
