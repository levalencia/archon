"""Tests for structured output (JSON mode) and Anthropic prompt caching."""

from __future__ import annotations

import pytest

from app.runtime.anthropic import anthropic_request
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolDefinition
from app.runtime.support import JsonModeProvider


class TestJsonModeAnthropicRequest:
    """Structured output / JSON mode in anthropic_request."""

    @pytest.mark.unit
    def test_json_mode_adds_system_instruction_and_prefill(self) -> None:
        messages = [Message(Role.USER, "List three colors")]
        result = anthropic_request(messages, (), 1024, response_format="json")

        # System should contain the JSON instruction
        assert "Respond with valid JSON only" in result["system"]
        # Last message should be the assistant prefill
        assert result["messages"][-1] == {"role": "assistant", "content": "{"}

    @pytest.mark.unit
    def test_json_mode_appends_to_existing_system(self) -> None:
        messages = [
            Message(Role.SYSTEM, "You are a helpful assistant"),
            Message(Role.USER, "List three colors"),
        ]
        result = anthropic_request(messages, (), 1024, response_format="json")

        # System should contain both the original and JSON instruction
        assert "You are a helpful assistant" in result["system"]
        assert "Respond with valid JSON only" in result["system"]
        # Last message should be the assistant prefill
        assert result["messages"][-1] == {"role": "assistant", "content": "{"}

    @pytest.mark.unit
    def test_no_json_mode_by_default(self) -> None:
        messages = [Message(Role.USER, "Hello")]
        result = anthropic_request(messages, (), 1024)

        # No system prompt should be added
        assert "system" not in result
        # No assistant prefill
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"

    @pytest.mark.unit
    def test_json_mode_with_caching_uses_list_system(self) -> None:
        messages = [
            Message(Role.SYSTEM, "You are an expert"),
            Message(Role.USER, "Give me data"),
        ]
        result = anthropic_request(
            messages, (), 1024, response_format="json", prompt_caching_enabled=True
        )

        # System should be a list (cached block + JSON instruction)
        assert isinstance(result["system"], list)
        assert len(result["system"]) == 2
        assert result["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert result["system"][1]["text"] == "Respond with valid JSON only."
        # Prefill
        assert result["messages"][-1] == {"role": "assistant", "content": "{"}


class TestJsonModeProvider:
    """JsonModeProvider wrapper forces JSON mode on delegates."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_json_mode_provider_passes_response_format(self) -> None:
        captured: dict = {}

        class FakeProvider:
            async def complete(self, messages, tools=(), *, max_tokens=4096, response_format=None):
                captured["response_format"] = response_format
                return ModelResponse(content='{"ok": true}', usage=TokenUsage(10, 5))

        provider = JsonModeProvider(FakeProvider())
        result = await provider.complete([Message(Role.USER, "test")])

        assert captured["response_format"] == "json"
        assert result.content == '{"ok": true}'


class TestPromptCaching:
    """Anthropic prompt caching via cache_control on system messages."""

    @pytest.mark.unit
    def test_caching_enabled_adds_cache_control(self) -> None:
        messages = [
            Message(Role.SYSTEM, "You are a helpful assistant"),
            Message(Role.USER, "Hello"),
        ]
        result = anthropic_request(messages, (), 1024, prompt_caching_enabled=True)

        # System should be a list with cache_control
        assert isinstance(result["system"], list)
        assert len(result["system"]) == 1
        block = result["system"][0]
        assert block["type"] == "text"
        assert block["text"] == "You are a helpful assistant"
        assert block["cache_control"] == {"type": "ephemeral"}

    @pytest.mark.unit
    def test_caching_disabled_uses_plain_string(self) -> None:
        messages = [
            Message(Role.SYSTEM, "You are a helpful assistant"),
            Message(Role.USER, "Hello"),
        ]
        result = anthropic_request(messages, (), 1024, prompt_caching_enabled=False)

        # System should be a plain string
        assert isinstance(result["system"], str)
        assert result["system"] == "You are a helpful assistant"

    @pytest.mark.unit
    def test_caching_default_is_disabled(self) -> None:
        messages = [
            Message(Role.SYSTEM, "System prompt"),
            Message(Role.USER, "Hello"),
        ]
        result = anthropic_request(messages, (), 1024)

        # Default: no caching, plain string
        assert isinstance(result["system"], str)

    @pytest.mark.unit
    def test_caching_with_multiple_system_messages(self) -> None:
        messages = [
            Message(Role.SYSTEM, "First system"),
            Message(Role.SYSTEM, "Second system"),
            Message(Role.USER, "Hello"),
        ]
        result = anthropic_request(messages, (), 1024, prompt_caching_enabled=True)

        # Multiple system parts joined, single cached block
        assert isinstance(result["system"], list)
        assert len(result["system"]) == 1
        assert "First system" in result["system"][0]["text"]
        assert "Second system" in result["system"][0]["text"]
        assert result["system"][0]["cache_control"] == {"type": "ephemeral"}
