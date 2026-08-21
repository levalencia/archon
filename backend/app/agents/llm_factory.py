"""LLM adapter factory. Creates the right adapter from settings."""

from __future__ import annotations

from app.agents.mock_llm import MockLLM
from app.agents.protocols import LLMClient
from app.config import Settings


def create_llm_client(settings: Settings) -> LLMClient:
    """Create an LLM client based on settings.llm_provider.

    Supported providers: mock, openai, anthropic, foundry, ollama.
    The core agent code never imports a specific SDK.
    """
    provider = settings.llm_provider.lower()

    if provider == "mock":
        return MockLLM()

    if provider == "openai":
        from app.agents.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url or None,
        )

    if provider == "anthropic":
        from app.agents.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )

    if provider == "foundry":
        from app.agents.foundry_adapter import FoundryAdapter

        return FoundryAdapter(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )

    if provider == "ollama":
        from app.agents.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=settings.llm_model,
            base_url=settings.llm_base_url or "http://localhost:11434",
        )

    msg = f"Unknown LLM provider: {provider}. Use: mock, openai, anthropic, foundry, ollama"
    raise ValueError(msg)
