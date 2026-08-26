"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from app.tools.sandbox import is_immutable_image_reference


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
    llm_fallback_providers: str = ""  # comma-separated list e.g. "openai,ollama"

    # Embeddings
    embedding_provider: str = "mock"  # mock | openai
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""  # falls back to llm_api_key if empty
    embedding_dimensions: int = 256
    embedding_base_url: str = "https://api.openai.com/v1"

    # Skills
    skills_top_k: int = 3
    image_gen_provider: str = "mock"  # mock | together | openai
    image_gen_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///archon.db"
    vector_store_backend: Literal["sql-json", "postgres", "memory"] = "sql-json"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    memory_backend: str = "file"  # file | redis

    # Observability
    otel_endpoint: str = ""
    otel_service_name: str = "archon"

    # Security
    secret_key: str = "dev-secret-change-in-production"
    encryption_master_key: str = ""
    memory_encryption_enabled: bool = True
    admin_usernames: list[str] = ["admin"]

    # Rate Limiting
    rate_limit_requests: int = Field(default=60, gt=0)
    rate_limit_window: int = Field(default=60, gt=0)
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_auth_requests: int | None = Field(default=None, gt=0)
    rate_limit_chat_requests: int | None = Field(default=None, gt=0)
    rate_limit_task_requests: int | None = Field(default=None, gt=0)
    rate_limit_mcp_requests: int | None = Field(default=None, gt=0)

    # Model provider circuit breaker
    circuit_breaker_failure_threshold: int = Field(default=5, gt=0)
    circuit_breaker_recovery_timeout: float = Field(default=30.0, gt=0)

    # Isolated execution (disabled and absent from the live registry by default)
    execution_enabled: bool = False
    execution_docker_binary: str = Field(default="docker", pattern=r"^[A-Za-z0-9_./-]+$")
    execution_docker_image: str = Field(
        default="archon-sandbox:local", pattern=r"^[A-Za-z0-9][A-Za-z0-9._/@:-]+$"
    )
    execution_docker_platform: str = Field(default="linux/amd64", pattern=r"^linux/(amd64|arm64)$")
    execution_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    execution_cpus: float = Field(default=0.5, ge=0.1, le=8.0)
    execution_memory_mb: int = Field(default=128, ge=32, le=4096)
    execution_pids_limit: int = Field(default=64, ge=16, le=512)
    execution_output_bytes: int = Field(default=65536, ge=1024, le=1048576)

    @model_validator(mode="after")
    def validate_execution_image(self) -> Settings:
        if self.execution_enabled and not is_immutable_image_reference(self.execution_docker_image):
            raise ValueError(
                "execution_docker_image must be an immutable sha256 registry digest "
                "or local image ID"
            )
        return self

    # Agent
    agent_max_iterations: int = 5
    agent_token_budget: int = 64_000
    approval_timeout_seconds: float = Field(default=30.0, gt=0)
    approval_poll_interval_seconds: float = Field(default=0.05, gt=0)
    context_length: int = 200000  # Claude Opus: 200K, Sonnet: 200K, llama3.1: 128K
    prompt_caching_enabled: bool = True

    model_config = {"env_prefix": "ARCHON_", "env_file": ".env", "extra": "ignore"}


def get_settings() -> Settings:
    """Factory for settings singleton."""
    return Settings()
