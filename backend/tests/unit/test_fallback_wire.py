"""Tests for LLM fallback chain wiring in llm_factory."""

from __future__ import annotations

import pytest

from app.agents.fallback_chain import FallbackLLMChain
from app.agents.llm_factory import create_llm_client
from app.config import Settings


class _FakeOKClient:
    """Mock LLM client that always succeeds."""

    def __init__(self, response: str = "ok") -> None:
        self._response = response
        self.calls = 0

    async def chat(self, messages, max_tokens=4096, temperature=0.7):
        self.calls += 1
        return self._response


class _FakeFailClient:
    """Mock LLM client that always raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, max_tokens=4096, temperature=0.7):
        self.calls += 1
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_fallback_chain_uses_primary_when_healthy():
    """Primary adapter succeeds — fallback is never called."""
    primary = _FakeOKClient("primary-response")
    fallback = _FakeOKClient("fallback-response")
    chain = FallbackLLMChain([primary, fallback])

    result = await chain.chat([{"role": "user", "content": "hi"}])
    assert result == "primary-response"
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_fallback_chain_falls_through_on_failure():
    """Primary fails — fallback responds successfully."""
    primary = _FakeFailClient()
    fallback = _FakeOKClient("fallback-response")
    chain = FallbackLLMChain([primary, fallback])

    result = await chain.chat([{"role": "user", "content": "hi"}])
    assert result == "fallback-response"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_fallback_chain_all_fail_returns_error_message():
    """All adapters fail — returns error summary string."""
    chain = FallbackLLMChain([_FakeFailClient(), _FakeFailClient()])
    result = await chain.chat([{"role": "user", "content": "hi"}])
    assert "All LLM providers failed" in result


def test_factory_returns_plain_client_without_fallbacks():
    """No fallback providers → returns plain MockLLM."""
    settings = Settings(llm_provider="mock", llm_fallback_providers="")
    client = create_llm_client(settings)
    assert not isinstance(client, FallbackLLMChain)


def test_factory_returns_fallback_chain_with_fallbacks():
    """Fallback providers set → returns FallbackLLMChain."""
    settings = Settings(llm_provider="mock", llm_fallback_providers="mock,mock")
    client = create_llm_client(settings)
    assert isinstance(client, FallbackLLMChain)
    assert len(client.adapters) == 3  # primary + 2 fallbacks


def test_fallback_chain_requires_at_least_one_adapter():
    """FallbackLLMChain raises ValueError with empty list."""
    with pytest.raises(ValueError, match="At least one adapter"):
        FallbackLLMChain([])
