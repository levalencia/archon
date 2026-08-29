"""LLM adapter factory. Creates the right adapter from settings."""

from __future__ import annotations

import structlog

from app.agents.fallback_chain import FallbackLLMChain
from app.agents.mock_llm import MockLLM
from app.agents.protocols import LLMClient
from app.config import Settings

logger = structlog.get_logger()


def _create_single_client(provider: str, settings: Settings) -> LLMClient:
    """Create a single LLM client for the given provider name."""
    provider = provider.strip().lower()

    if provider == "mock":
        return MockLLM()

    if provider == "openai":
        from app.agents.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url or None,
            native_tools_enabled=settings.openai_native_tools_enabled,
            images_enabled=settings.openai_images_enabled,
            json_mode_enabled=settings.openai_json_mode_enabled,
            json_schema_enabled=settings.openai_json_schema_enabled,
            cache_usage_enabled=settings.openai_cache_usage_enabled,
        )

    if provider == "anthropic":
        from app.agents.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            prompt_caching_enabled=settings.prompt_caching_enabled,
        )

    if provider == "foundry":
        from app.agents.foundry_adapter import FoundryAdapter

        return FoundryAdapter(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            prompt_caching_enabled=settings.prompt_caching_enabled,
        )

    if provider == "ollama":
        from app.agents.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=settings.llm_model,
            base_url=settings.llm_base_url or "http://localhost:11434",
            native_tools_enabled=settings.ollama_native_tools_enabled,
            vision_model=settings.ollama_vision_model or None,
            vision_native_tools_enabled=settings.ollama_vision_native_tools_enabled,
            json_mode_enabled=settings.ollama_json_mode_enabled,
            json_schema_enabled=settings.ollama_json_schema_enabled,
        )

    msg = f"Unknown LLM provider: {provider}. Use: mock, openai, anthropic, foundry, ollama"
    raise ValueError(msg)


def create_llm_client(settings: Settings) -> LLMClient:
    """Create an LLM client based on settings.llm_provider.

    If llm_fallback_providers is set, wraps the primary client with
    FallbackLLMChain for graceful degradation.

    Supported providers: mock, openai, anthropic, foundry, ollama.
    The core agent code never imports a specific SDK.
    """
    primary = _create_single_client(settings.llm_provider, settings)

    fallback_str = settings.llm_fallback_providers.strip()
    if not fallback_str:
        return primary

    # Build fallback chain: primary first, then each fallback provider
    fallback_names = [p.strip() for p in fallback_str.split(",") if p.strip()]
    if not fallback_names:
        return primary

    adapters: list[LLMClient] = [primary]
    for name in fallback_names:
        try:
            adapters.append(_create_single_client(name, settings))
        except ValueError:
            logger.warning("llm_fallback_provider_unknown", provider=name)

    if len(adapters) < 2:
        return primary

    logger.info(
        "llm_fallback_chain_created",
        primary=settings.llm_provider,
        fallbacks=fallback_names,
    )
    return FallbackLLMChain(adapters)
