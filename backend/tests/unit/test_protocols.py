"""Unit tests for Protocol definitions and MockLLM."""

from __future__ import annotations

import pytest

from app.agents.llm_factory import create_llm_client
from app.agents.mock_llm import MockLLM
from app.agents.protocols import LLMClient
from app.config import Settings


class TestProtocolCompliance:
    """Verify implementations satisfy their Protocol contracts."""

    @pytest.mark.unit
    def test_mock_llm_satisfies_llm_client_protocol(self) -> None:
        llm = MockLLM()
        assert isinstance(llm, LLMClient)


class TestMockLLM:
    """MockLLM adapter tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_responses_in_order(self) -> None:
        llm = MockLLM(responses=["first", "second", "third"])
        r1 = await llm.chat([{"role": "user", "content": "a"}])
        r2 = await llm.chat([{"role": "user", "content": "b"}])
        r3 = await llm.chat([{"role": "user", "content": "c"}])
        assert r1 == "first"
        assert r2 == "second"
        assert r3 == "third"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_tracks_call_history(self) -> None:
        llm = MockLLM(responses=["ok"])
        await llm.chat([{"role": "user", "content": "hello"}], max_tokens=100)
        assert len(llm.call_history) == 1
        assert llm.call_history[0]["messages"][0]["content"] == "hello"
        assert llm.call_history[0]["max_tokens"] == 100

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_response_when_exhausted(self) -> None:
        llm = MockLLM(responses=["only one"])
        await llm.chat([{"role": "user", "content": "1"}])
        r2 = await llm.chat([{"role": "user", "content": "2"}])
        assert "don't have more" in r2.lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_default_response_with_no_args(self) -> None:
        llm = MockLLM()
        result = await llm.chat([{"role": "user", "content": "hi"}])
        assert isinstance(result, str)
        assert len(result) > 0


class TestLLMFactory:
    """LLM adapter factory tests."""

    @pytest.mark.unit
    def test_create_mock_provider(self) -> None:
        settings = Settings(llm_provider="mock")
        llm = create_llm_client(settings)
        assert isinstance(llm, MockLLM)
        assert isinstance(llm, LLMClient)

    @pytest.mark.unit
    def test_unknown_provider_raises(self) -> None:
        settings = Settings(llm_provider="nonexistent")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_client(settings)
