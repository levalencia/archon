"""Tests for typed capability-aware LLM fallback and factory wiring."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.agents.fallback_chain import (
    FallbackLLMChain,
    NoCompatibleProviderError,
    ProviderFallbackExhausted,
)
from app.agents.llm_factory import create_llm_client
from app.config import Settings
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolDefinition
from app.runtime.structured_output import ResponseContract


class _TypedClient:
    def __init__(
        self,
        response: ModelResponse | None = None,
        *,
        capabilities: ProviderCapabilities | None = None,
        error: Exception | None = None,
        model: object = None,
    ) -> None:
        self.response = response or ModelResponse("ok")
        self.capabilities = capabilities or ProviderCapabilities()
        self.error = error
        self.model = model
        self.calls: list[tuple[object, object, dict[str, object]]] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        **kwargs: object,
    ) -> ModelResponse:
        self.calls.append((messages, tools, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


class _LegacyOKClient:
    def __init__(self, response: str = "ok") -> None:
        self._response = response
        self.calls: list[tuple[object, int]] = []

    # Intentionally Ollama-like: no temperature keyword.
    async def chat(self, messages, max_tokens=4096):
        self.calls.append((messages, max_tokens))
        return self._response


class _LegacyTemperatureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int, float]] = []

    async def chat(self, messages, max_tokens=4096, temperature=0.7):
        self.calls.append((messages, max_tokens, temperature))
        return "temperature-aware"


class _LegacyFailClient:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, max_tokens=4096, temperature=0.7):
        self.calls += 1
        raise RuntimeError("secret provider failure")


def _contract() -> ResponseContract:
    return ResponseContract("answer", "1", {"type": "object"}, lambda value: value)


@pytest.mark.asyncio
async def test_typed_primary_success() -> None:
    primary = _TypedClient(ModelResponse("primary"))
    fallback = _TypedClient(ModelResponse("fallback"))
    chain = FallbackLLMChain([primary, fallback])

    result = await chain.complete([Message(Role.USER, "hi")])

    assert result.content == "primary"
    assert len(primary.calls) == 1
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_typed_failure_then_compatible_fallback() -> None:
    capabilities = ProviderCapabilities(native_tools=True)
    primary = _TypedClient(capabilities=capabilities, error=RuntimeError("down"))
    fallback = _TypedClient(ModelResponse("fallback"), capabilities=capabilities)
    chain = FallbackLLMChain([primary, fallback])

    result = await chain.complete([Message(Role.USER, "hi")], [ToolDefinition("search")])

    assert result.content == "fallback"
    assert len(primary.calls) == len(fallback.calls) == 1
    assert chain.get_stats()["failures"] == {0: 1}


@pytest.mark.asyncio
async def test_incompatible_provider_is_skipped_without_invocation() -> None:
    primary = _TypedClient()
    fallback = _TypedClient(
        ModelResponse("capable"), capabilities=ProviderCapabilities(native_tools=True)
    )
    chain = FallbackLLMChain([primary, fallback])

    result = await chain.complete([Message(Role.USER, "hi")], [ToolDefinition("search")])

    assert result.content == "capable"
    assert primary.calls == []
    assert len(fallback.calls) == 1


@pytest.mark.asyncio
async def test_no_compatible_provider_raises_typed_safe_error() -> None:
    chain = FallbackLLMChain([_TypedClient(), _TypedClient()])

    with pytest.raises(NoCompatibleProviderError) as raised:
        await chain.complete([Message(Role.USER, "see", images=("image-data",))])

    assert raised.value.required_capabilities == ("images",)
    assert raised.value.missing_capabilities == ("images",)
    assert raised.value.candidate_count == 2
    assert "image-data" not in str(raised.value)


@pytest.mark.asyncio
async def test_all_compatible_failures_raise_without_raw_errors() -> None:
    chain = FallbackLLMChain(
        [
            _TypedClient(error=RuntimeError("first secret")),
            _TypedClient(error=ValueError("second secret")),
        ]
    )

    with pytest.raises(ProviderFallbackExhausted) as raised:
        await chain.complete([Message(Role.USER, "hi")])

    assert raised.value.attempted_count == 2
    assert raised.value.provider_names == ("_TypedClient", "_TypedClient")
    assert "secret" not in str(raised.value)
    assert "All LLM providers failed" not in str(raised.value)


@pytest.mark.asyncio
async def test_typed_request_values_are_forwarded_unchanged() -> None:
    capabilities = ProviderCapabilities(native_tools=True, images=True, json_mode=True)
    provider = _TypedClient(
        ModelResponse('{"answer": 1}', structured_output={"answer": 1}),
        capabilities=capabilities,
    )
    chain = FallbackLLMChain([provider])
    messages = [Message(Role.USER, "inspect", images=("img",))]
    tools = [ToolDefinition("inspect")]
    contract = _contract()

    await chain.complete(messages, tools, max_tokens=123, response_contract=contract)

    called_messages, called_tools, kwargs = provider.calls[0]
    assert called_messages is messages
    assert called_tools is tools
    assert kwargs == {"max_tokens": 123, "response_contract": contract}


@pytest.mark.asyncio
async def test_combined_requirements_need_one_candidate_not_union_only_match() -> None:
    tools_only = _TypedClient(capabilities=ProviderCapabilities(native_tools=True))
    images_only = _TypedClient(capabilities=ProviderCapabilities(images=True))
    chain = FallbackLLMChain([tools_only, images_only])
    assert chain.capabilities.native_tools is True
    assert chain.capabilities.images is True

    with pytest.raises(NoCompatibleProviderError):
        await chain.complete(
            [Message(Role.USER, "both", images=("img",))], [ToolDefinition("inspect")]
        )

    assert tools_only.calls == images_only.calls == []


@pytest.mark.asyncio
async def test_winner_identity_and_response_metadata_are_preserved() -> None:
    usage = TokenUsage(4, 5, cache_read_input_tokens=3, cache_write_input_tokens=2)
    response = ModelResponse(
        "done",
        usage=usage,
        provider_stop_reason="stop",
        structured_output={"ok": True},
    )
    primary = _TypedClient(error=RuntimeError("down"))
    winner = _TypedClient(response, model="safe-model")

    result = await FallbackLLMChain([primary, winner]).complete([Message(Role.USER, "hi")])

    assert result.actual_provider == "_TypedClient"
    assert result.actual_model == "safe-model"
    assert result.usage is usage
    assert result.provider_stop_reason == "stop"
    assert result.structured_output == {"ok": True}


@pytest.mark.asyncio
async def test_response_identity_is_not_overwritten() -> None:
    response = ModelResponse("done", actual_provider="upstream", actual_model="upstream-model")
    result = await FallbackLLMChain([_TypedClient(response, model="adapter-model")]).complete(
        [Message(Role.USER, "hi")]
    )
    assert result is response


@pytest.mark.asyncio
async def test_contract_and_format_are_mutually_exclusive() -> None:
    chain = FallbackLLMChain([_TypedClient()])
    with pytest.raises(ValueError, match="mutually exclusive"):
        await chain.complete(
            [Message(Role.USER, "hi")],
            response_contract=_contract(),
            response_format="json",
        )


@pytest.mark.asyncio
async def test_legacy_chat_works_with_ollama_like_signature() -> None:
    client = _LegacyOKClient("legacy")
    chain = FallbackLLMChain([client])

    result = await chain.chat(
        [{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}],
        max_tokens=99,
        temperature=0.1,
    )

    assert result == "legacy"
    assert client.calls == [
        ([{"role": "system", "content": "rules"}, {"role": "user", "content": "hi"}], 99)
    ]


@pytest.mark.asyncio
async def test_legacy_chat_forwards_temperature_when_supported() -> None:
    client = _LegacyTemperatureClient()
    messages = [{"role": "user", "content": "hi"}]

    result = await FallbackLLMChain([client]).chat(messages, max_tokens=77, temperature=0.1)

    assert result == "temperature-aware"
    assert client.calls == [(messages, 77, 0.1)]


@pytest.mark.asyncio
async def test_legacy_all_fail_raises_typed_error() -> None:
    with pytest.raises(ProviderFallbackExhausted):
        await FallbackLLMChain([_LegacyFailClient()]).chat([{"role": "user", "content": "hi"}])


def test_factory_returns_plain_client_without_fallbacks() -> None:
    settings = Settings(llm_provider="mock", llm_fallback_providers="")
    client = create_llm_client(settings)
    assert not isinstance(client, FallbackLLMChain)


def test_factory_returns_fallback_chain_with_fallbacks() -> None:
    settings = Settings(llm_provider="mock", llm_fallback_providers="mock,mock")
    client = create_llm_client(settings)
    assert isinstance(client, FallbackLLMChain)
    assert len(client.adapters) == 3


def test_fallback_chain_requires_at_least_one_adapter() -> None:
    with pytest.raises(ValueError, match="At least one adapter"):
        FallbackLLMChain([])
