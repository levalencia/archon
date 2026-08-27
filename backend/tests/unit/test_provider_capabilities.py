"""Provider capability and usage contract tests."""

from __future__ import annotations

import inspect

import pytest

from app.agents.anthropic_adapter import AnthropicAdapter
from app.agents.foundry_adapter import FoundryAdapter
from app.agents.mock_llm import MockLLM
from app.runtime.capabilities import (
    TEXT_ONLY_CAPABILITIES,
    ProviderCapabilities,
    UnsupportedProviderCapability,
    get_provider_capabilities,
)
from app.runtime.models import Message, ModelResponse, Role, TokenUsage
from app.runtime.ports import ModelProvider
from app.runtime.structured_output import ResponseContract
from app.runtime.support import JsonModeProvider, TextOnlyProvider
from app.security.circuit_breaker import CircuitBreaker, CircuitBreakingProvider


@pytest.mark.unit
def test_missing_capabilities_are_stable_and_ordered() -> None:
    available = ProviderCapabilities(native_tools=True, usage=True)
    required = ProviderCapabilities(native_tools=True, images=True, json_schema=True, usage=True)

    assert available.missing(required) == ("images", "json_schema")


@pytest.mark.unit
def test_capability_values_must_be_strict_booleans() -> None:
    with pytest.raises(TypeError, match="images must be bool"):
        ProviderCapabilities(images="yes")  # type: ignore[arg-type]


@pytest.mark.unit
def test_undeclared_provider_is_conservatively_text_only_without_invocation() -> None:
    class Undeclared:
        calls = 0

        async def complete(self, *args: object, **kwargs: object) -> ModelResponse:
            self.calls += 1
            return ModelResponse("unused")

    provider = Undeclared()
    assert get_provider_capabilities(provider) is TEXT_ONLY_CAPABILITIES
    assert provider.calls == 0


@pytest.mark.unit
def test_unsupported_capability_error_carries_provider_and_missing_names() -> None:
    error = UnsupportedProviderCapability("acme/model-1", ("images", "json_schema"))

    assert error.provider_identity == "acme/model-1"
    assert error.missing_capabilities == ("images", "json_schema")
    assert "acme/model-1" in str(error)


@pytest.mark.unit
def test_token_cache_usage_unknown_zero_and_addition_semantics() -> None:
    unknown = TokenUsage(1, 2)
    explicit_zero = TokenUsage(3, 4, cache_read_input_tokens=0, cache_write_input_tokens=0)
    reported = TokenUsage(5, 6, cache_read_input_tokens=7)

    assert unknown.cache_read_input_tokens is None
    assert (unknown + TokenUsage()).cache_read_input_tokens is None
    assert (unknown + explicit_zero).cache_read_input_tokens == 0
    assert (unknown + reported).cache_read_input_tokens == 7
    assert (reported + TokenUsage(cache_read_input_tokens=2)).cache_read_input_tokens == 9
    with pytest.raises(ValueError):
        TokenUsage(cache_write_input_tokens=-1)


@pytest.mark.unit
def test_wrappers_preserve_declared_capabilities() -> None:
    delegate = MockLLM()
    breaker_wrapper = CircuitBreakingProvider(delegate, CircuitBreaker())
    json_wrapper = JsonModeProvider(delegate)

    assert get_provider_capabilities(breaker_wrapper) == get_provider_capabilities(delegate)
    assert get_provider_capabilities(json_wrapper) == get_provider_capabilities(delegate)
    assert get_provider_capabilities(json_wrapper).native_tools


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composite_wrappers_copy_marker_and_forward_explicit_requirements() -> None:
    required = ProviderCapabilities(usage=True, stop_reason=True)

    class RoutedDelegate:
        routes_capabilities = True
        capabilities = required

        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        async def complete(self, messages, tools=(), **kwargs):
            del messages, tools
            self.kwargs = kwargs
            return ModelResponse("ok")

    delegate = RoutedDelegate()
    breaker_wrapper = CircuitBreakingProvider(delegate, CircuitBreaker())
    json_wrapper = JsonModeProvider(breaker_wrapper)

    assert inspect.getattr_static(breaker_wrapper, "routes_capabilities") is True
    assert inspect.getattr_static(json_wrapper, "routes_capabilities") is True
    await json_wrapper.complete([Message(Role.USER, "go")], required_capabilities=required)
    assert delegate.kwargs["required_capabilities"] is required


@pytest.mark.unit
@pytest.mark.asyncio
async def test_composite_wrappers_do_not_forward_capabilities_to_legacy_delegate() -> None:
    class LegacyDelegate:
        async def complete(self, messages, tools=(), *, max_tokens=4096, response_format=None):
            del messages, tools, max_tokens, response_format
            return ModelResponse("ok")

    breaker_wrapper = CircuitBreakingProvider(LegacyDelegate(), CircuitBreaker())
    json_wrapper = JsonModeProvider(breaker_wrapper)

    assert inspect.getattr_static(breaker_wrapper, "routes_capabilities") is False
    assert inspect.getattr_static(json_wrapper, "routes_capabilities") is False
    assert inspect.getattr_static(TextOnlyProvider(object()), "routes_capabilities") is False
    await json_wrapper.complete(
        [Message(Role.USER, "go")],
        required_capabilities=ProviderCapabilities(usage=True),
    )


@pytest.mark.unit
def test_json_wrapper_does_not_invent_delegate_capability() -> None:
    class LegacyClient:
        async def chat(self, messages: object, *, max_tokens: int) -> str:
            del messages, max_tokens
            return "plain text"

    wrapped = JsonModeProvider(TextOnlyProvider(LegacyClient()))

    assert not get_provider_capabilities(wrapped).json_mode


@pytest.mark.unit
def test_text_only_provider_declares_conservative_capabilities() -> None:
    assert get_provider_capabilities(TextOnlyProvider(object())) is TEXT_ONLY_CAPABILITIES


@pytest.mark.unit
def test_anthropic_adapters_declare_only_observed_typed_features() -> None:
    anthropic = get_provider_capabilities(AnthropicAdapter("test"))
    foundry = get_provider_capabilities(FoundryAdapter("test", "https://example.com"))

    for capabilities in (anthropic, foundry):
        assert capabilities.native_tools
        assert capabilities.images
        assert capabilities.json_mode
        assert capabilities.prompt_caching
        assert capabilities.usage
        assert capabilities.stop_reason
        assert not capabilities.json_schema
        assert not capabilities.cache_usage
        assert not capabilities.streaming


@pytest.mark.unit
def test_response_contract_is_part_of_provider_signature() -> None:
    parameter = inspect.signature(ModelProvider.complete).parameters["response_contract"]
    assert parameter.default is None
    assert "ResponseContract" in str(parameter.annotation)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_response_contract_and_legacy_format_are_mutually_exclusive() -> None:
    contract = ResponseContract("answer", "1", {"type": "object"}, lambda value: value)
    with pytest.raises(ValueError, match="mutually exclusive"):
        await MockLLM().complete(
            [Message(Role.USER, "hello")],
            response_contract=contract,
            response_format="json",
        )


@pytest.mark.unit
def test_structured_output_does_not_weaken_model_response_invariant() -> None:
    with pytest.raises(ValueError, match="content or at least one tool call"):
        ModelResponse(structured_output={"answer": "yes"})

    response = ModelResponse(
        "raw",
        structured_output={"answer": "yes"},
        actual_provider="anthropic",
        actual_model="claude-test",
    )
    assert response.actual_provider == "anthropic"
    assert response.actual_model == "claude-test"
