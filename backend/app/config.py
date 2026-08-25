"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Archon configuration. All values can be overridden via environment variables."""

    # App
    app_name: str = "Archon"
    app_version: str = "0.1.0"
    debug: bool = False

    # LLM Provider (vendor-neutral)
    llm_provider: str = "mock"  # mock | openai | anthropic | foundry | ollama
    llm_model: str = "mock-model"
    llm_api_key: str = ""
    llm_base_url: str = ""

    # Embeddings
    embedding_provider: str = "mock"  # mock | openai
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""  # falls back to llm_api_key if empty
    embedding_dimensions: int = 256

    # Skills
    skills_top_k: int = 3
    image_gen_provider: str = "mock"  # mock | together | openai
    image_gen_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///archon.db"
    vector_store_backend: str = "memory"  # memory | postgres

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Observability
    otel_endpoint: str = ""
    otel_service_name: str = "archon"

    # Security
    secret_key: str = "dev-secret-change-in-production"
    encryption_master_key: str = ""
    admin_usernames: list[str] = ["admin"]

    # Rate Limiting
    rate_limit_requests: int = 60
    rate_limit_window: int = 60

    # Agent
    agent_max_iterations: int = 5
    agent_token_budget: int = 64_000
    context_length: int = 200000  # Claude Opus: 200K, Sonnet: 200K, llama3.1: 128K

    model_config = {"env_prefix": "ARCHON_", "env_file": ".env", "extra": "ignore"}


def get_settings() -> Settings:
    """Factory for settings singleton."""
    return Settings()
