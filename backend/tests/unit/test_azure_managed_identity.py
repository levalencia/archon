"""Unit tests for Azure Managed Identity auth in the OpenAI adapter.

No live Azure or provider calls — all credentials and HTTP are faked.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.agents.azure_credential import DEFAULT_SCOPE, AzureTokenProvider
from app.agents.openai_adapter import OpenAIAdapter
from app.observability.cost_tracker import price_model_usage_nusd, validated_pricing_pair

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeAccessToken:
    token: str
    expires_on: int


class FakeCredential:
    """Deterministic async credential that records calls and returns controlled tokens."""

    def __init__(self, tokens: list[FakeAccessToken]) -> None:
        self._tokens = list(tokens)
        self._idx = 0
        self.calls: list[tuple[str, ...]] = []
        self.closed = False

    async def get_token(self, *scopes: str) -> FakeAccessToken:
        self.calls.append(scopes)
        tok = self._tokens[min(self._idx, len(self._tokens) - 1)]
        self._idx += 1
        return tok

    async def close(self) -> None:
        self.closed = True


def _ok_completion(content: str = "ok") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }


def _make_adapter_with_transport(
    handler,
    *,
    token_provider: AzureTokenProvider | None = None,
    api_key: str = "static-key",
) -> OpenAIAdapter:
    adapter = OpenAIAdapter(
        api_key=api_key,
        model="deepseek-r1",
        base_url="https://foundry.example.com/v1",
        token_provider=token_provider,
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://foundry.example.com/v1",
        headers=dict(adapter._client.headers),
    )
    return adapter


# ---------------------------------------------------------------------------
# Tests: factory selects managed identity
# ---------------------------------------------------------------------------


class TestFactorySelectsManagedIdentity:
    @pytest.mark.unit
    def test_api_key_mode_is_default(self) -> None:
        from app.config import Settings

        s = Settings(llm_provider="mock")
        assert s.llm_auth_mode == "api_key"

    @pytest.mark.unit
    def test_azure_identity_mode_accepted(self) -> None:
        from app.config import Settings

        s = Settings(llm_provider="mock", llm_auth_mode="azure_identity")
        assert s.llm_auth_mode == "azure_identity"

    @pytest.mark.unit
    def test_factory_creates_token_provider_for_azure_identity(self, monkeypatch) -> None:
        """Factory should pass a token_provider when auth_mode is azure_identity."""
        from app.agents import llm_factory
        from app.config import Settings

        # Fake out azure.identity.aio.DefaultAzureCredential
        class FakeDefaultCredential:
            def __init__(self, **kwargs) -> None:
                self.kwargs = kwargs

        fake_module = type("mod", (), {"DefaultAzureCredential": FakeDefaultCredential})()
        monkeypatch.setitem(
            __import__("sys").modules,
            "azure.identity.aio",
            fake_module,
        )

        settings = Settings(
            llm_provider="openai",
            llm_auth_mode="azure_identity",
            llm_base_url="https://foundry.example.com/v1",
            llm_model="deepseek-r1",
        )
        client = llm_factory._create_single_client("openai", settings)
        assert isinstance(client, OpenAIAdapter)
        assert client._token_provider is not None

    @pytest.mark.unit
    def test_factory_no_token_provider_for_api_key_mode(self) -> None:
        from app.agents import llm_factory
        from app.config import Settings

        settings = Settings(
            llm_provider="openai",
            llm_auth_mode="api_key",
            llm_api_key="sk-test",
            llm_model="gpt-4o",
        )
        client = llm_factory._create_single_client("openai", settings)
        assert isinstance(client, OpenAIAdapter)
        assert client._token_provider is None


@pytest.mark.unit
def test_deepseek_v4_flash_has_exact_foundry_pricing() -> None:
    assert validated_pricing_pair("DeepSeek-V4-Flash", "openai") == (
        "openai",
        "DeepSeek-V4-Flash",
    )
    assert (
        price_model_usage_nusd("DeepSeek-V4-Flash", "openai", 1_000_000, 1_000_000) == 700_000_000
    )
    assert (
        price_model_usage_nusd("DeepSeek-V4-Flash", "openai", 1_000_000, 0, cache_read=1_000_000)
        == 28_000_000
    )


# ---------------------------------------------------------------------------
# Tests: token refresh and caching
# ---------------------------------------------------------------------------


class TestTokenRefreshAndCaching:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_first_call_fetches_token(self) -> None:
        cred = FakeCredential([FakeAccessToken("tok-1", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        token = await provider.get_bearer_token()

        assert token == "tok-1"
        assert len(cred.calls) == 1
        assert cred.calls[0] == (DEFAULT_SCOPE,)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cached_token_reused(self) -> None:
        cred = FakeCredential([FakeAccessToken("tok-1", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        first = await provider.get_bearer_token()
        second = await provider.get_bearer_token()

        assert first == second == "tok-1"
        assert len(cred.calls) == 1  # only one credential call

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_expired_token_refreshes(self) -> None:
        # First token already expired (expires_on in the past).
        cred = FakeCredential(
            [
                FakeAccessToken("tok-old", int(time.time()) - 100),
                FakeAccessToken("tok-new", int(time.time()) + 3600),
            ]
        )
        provider = AzureTokenProvider(cred)

        first = await provider.get_bearer_token()
        assert first == "tok-old"
        # Force expiry by manipulating internal deadline.
        provider._expires_on = 0
        second = await provider.get_bearer_token()
        assert second == "tok-new"
        assert len(cred.calls) == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_close_delegates_to_credential(self) -> None:
        cred = FakeCredential([FakeAccessToken("tok", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)
        await provider.close()
        assert cred.closed

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_custom_scope(self) -> None:
        cred = FakeCredential([FakeAccessToken("tok-s", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred, scope="https://custom/.default")
        await provider.get_bearer_token()
        assert cred.calls[0] == ("https://custom/.default",)


# ---------------------------------------------------------------------------
# Tests: Authorization header per request
# ---------------------------------------------------------------------------


class TestAuthorizationHeaderPerRequest:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_managed_identity_sets_bearer_per_request(self) -> None:
        cred = FakeCredential([FakeAccessToken("mi-token-1", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        captured_requests: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_requests.append(req)
            return httpx.Response(200, json=_ok_completion())

        adapter = _make_adapter_with_transport(handler, token_provider=provider)
        await adapter.chat([{"role": "user", "content": "hi"}])

        assert len(captured_requests) == 1
        assert captured_requests[0].headers["authorization"] == "Bearer mi-token-1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_api_key_mode_uses_static_bearer(self) -> None:
        captured_requests: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_requests.append(req)
            return httpx.Response(200, json=_ok_completion())

        adapter = _make_adapter_with_transport(handler, api_key="sk-static")
        await adapter.chat([{"role": "user", "content": "hi"}])

        assert captured_requests[0].headers["authorization"] == "Bearer sk-static"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_refreshed_token_appears_in_subsequent_request(self) -> None:
        cred = FakeCredential(
            [
                FakeAccessToken("tok-a", int(time.time()) + 3600),
                FakeAccessToken("tok-b", int(time.time()) + 3600),
            ]
        )
        provider = AzureTokenProvider(cred)

        captured_auth: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_auth.append(req.headers["authorization"])
            return httpx.Response(200, json=_ok_completion())

        adapter = _make_adapter_with_transport(handler, token_provider=provider)

        await adapter.chat([{"role": "user", "content": "1"}])
        # Force token refresh
        provider._expires_on = 0
        await adapter.chat([{"role": "user", "content": "2"}])

        assert captured_auth[0] == "Bearer tok-a"
        assert captured_auth[1] == "Bearer tok-b"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_complete_endpoint_also_uses_managed_identity(self) -> None:
        """The typed ``complete()`` path must also inject the token."""
        from app.runtime.models import Message, Role

        cred = FakeCredential([FakeAccessToken("typed-tok", int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        captured_requests: list[httpx.Request] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured_requests.append(req)
            return httpx.Response(200, json=_ok_completion("typed answer"))

        adapter = _make_adapter_with_transport(handler, token_provider=provider)
        result = await adapter.complete([Message(Role.USER, "hello")])

        assert result.content == "typed answer"
        assert captured_requests[0].headers["authorization"] == "Bearer typed-tok"


# ---------------------------------------------------------------------------
# Tests: no token in logs/errors
# ---------------------------------------------------------------------------


class TestNoTokenInLogs:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_not_logged(self, caplog) -> None:
        """Bearer token value must never appear in log output."""
        secret = "SUPER_SECRET_AZURE_TOKEN_12345"
        cred = FakeCredential([FakeAccessToken(secret, int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_completion())

        adapter = _make_adapter_with_transport(handler, token_provider=provider)

        with caplog.at_level(logging.DEBUG):
            await adapter.chat([{"role": "user", "content": "hi"}])

        full_log = caplog.text
        assert secret not in full_log, "Token was leaked into logs!"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_token_not_in_error_message(self) -> None:
        """If the adapter raises, the token must not appear in the exception."""
        secret = "ANOTHER_SECRET_TOKEN_67890"
        cred = FakeCredential([FakeAccessToken(secret, int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        adapter = _make_adapter_with_transport(handler, token_provider=provider)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await adapter.chat([{"role": "user", "content": "hi"}])

        assert secret not in str(exc_info.value)
        assert secret not in repr(exc_info.value)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_adapter_init_log_does_not_contain_token(self, caplog) -> None:
        """Construction log entry must not leak credentials."""
        secret = "INIT_SECRET_TOKEN_99999"
        cred = FakeCredential([FakeAccessToken(secret, int(time.time()) + 3600)])
        provider = AzureTokenProvider(cred)

        with caplog.at_level(logging.DEBUG):
            OpenAIAdapter(
                api_key="unused",
                model="deepseek-r1",
                base_url="https://foundry.example.com/v1",
                token_provider=provider,
            )

        assert secret not in caplog.text
