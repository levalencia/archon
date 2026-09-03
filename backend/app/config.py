"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    llm_fallback_providers: str = ""  # comma-separated list e.g. "openai,ollama"
    # OpenAI-compatible endpoints vary; opt in only to capabilities verified for the endpoint.
    openai_native_tools_enabled: bool = False
    openai_images_enabled: bool = False
    openai_json_mode_enabled: bool = False
    openai_json_schema_enabled: bool = False
    openai_cache_usage_enabled: bool = False
    # Ollama features vary by installed model/version and are opt-in.
    ollama_native_tools_enabled: bool = False
    ollama_vision_model: str = ""
    # Tool support on the text model does not imply support on the vision model.
    ollama_vision_native_tools_enabled: bool = False
    ollama_json_mode_enabled: bool = False
    ollama_json_schema_enabled: bool = False

    # Isolated evidence verifier (uses the application model provider, without tools)
    verifier_enabled: bool = False
    verifier_model: str = Field(
        default="verifier-model",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    verifier_input_tokens: int = Field(default=8_192, ge=1, le=32_768)
    verifier_output_tokens: int = Field(default=1_024, ge=1, le=8_192)
    verifier_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)
    verifier_retries: int = Field(default=0, ge=0, le=1)

    # Optional final-answer reflection (distinct from tool-error feedback and verification)
    reflection_enabled: bool = False
    reflection_rubric_id: str = Field(
        default="final-answer-quality", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    reflection_rubric_version: str = Field(
        default="1", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
    )
    reflection_max_revisions: int = Field(default=1, ge=0, le=1)
    reflection_input_tokens: int = Field(default=8_192, ge=1, le=65_536)
    reflection_output_tokens: int = Field(default=2_048, ge=1, le=16_384)
    reflection_timeout_seconds: float = Field(default=10.0, ge=0.05, le=60.0)
    reflection_max_cost_usd: Decimal = Field(default=Decimal("0.05"), ge=0)
    reflection_input_cost_per_million_usd: Decimal = Field(default=Decimal("0"), ge=0)
    reflection_output_cost_per_million_usd: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_reflection_pricing(self) -> Settings:
        if (
            self.reflection_enabled
            and self.reflection_max_cost_usd > 0
            and self.reflection_input_cost_per_million_usd == 0
            and self.reflection_output_cost_per_million_usd == 0
        ):
            raise ValueError("enabled reflection requires pricing for a positive cost cap")
        return self

    # Embeddings
    embedding_provider: str = "mock"  # mock | openai | foundry
    embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str = ""  # falls back to llm_api_key if empty
    embedding_dimensions: int = Field(default=256, ge=1, le=4096)
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_allowed_hosts: str = "api.openai.com"
    embedding_allow_private_endpoint: bool = False
    embedding_api_version: str = Field(
        default="2024-05-01-preview",
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-preview)?$",
    )

    # Bounded document/vector resources
    document_max_characters: int = Field(default=1_000_000, ge=1, le=20_000_000)
    documents_max_per_owner_project: int = Field(default=1_000, ge=1, le=100_000)
    document_max_chunks: int = Field(default=4_096, ge=1, le=100_000)
    vector_search_candidate_limit: int = Field(default=10_000, ge=1, le=100_000)

    # Skills
    skills_top_k: int = 3
    skills_allowed_repositories: str = ""
    # Optional metadata-only external catalog. The source must resolve below the fixed root.
    skill_catalog_enabled: bool = False
    skill_catalog_allowlisted_root: str = ""
    skill_catalog_executable: str = ""
    skill_catalog_json_index: str = ""
    skill_catalog_timeout_seconds: float = Field(default=2.0, ge=0.05, le=30.0)
    skill_catalog_max_stdout_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    skill_catalog_max_results: int = Field(default=50, ge=1, le=100)
    project_workspace_root: str = ""
    mcp_profiles_json: SecretStr = SecretStr("")
    image_gen_provider: str = "mock"  # mock | together | openai
    image_gen_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///archon.db"
    vector_store_backend: Literal["sql-json"] = "sql-json"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    memory_backend: str = "file"  # file | redis

    # Observability
    otel_endpoint: str = ""
    otel_service_name: str = "archon"

    # Security
    secret_key: str = "dev-secret-change-in-production"
    encryption_master_key: SecretStr = SecretStr("")
    memory_keyring_json: SecretStr = SecretStr("")
    memory_active_key_version: int = Field(default=1, ge=1, le=255)
    memory_encryption_enabled: bool = True
    delegation_signing_key: SecretStr = SecretStr("")
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
    execution_runner_socket: str = Field(
        default="/run/archon-sandbox/runner.sock", pattern=r"^/[A-Za-z0-9_./-]+$"
    )
    # Legacy settings remain parseable for developer tooling, but the live backend
    # never invokes Docker.
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
    def validate_execution_runner(self) -> Settings:
        if self.execution_enabled and not self.execution_runner_socket.startswith("/"):
            raise ValueError("execution_runner_socket must be absolute")
        return self

    @model_validator(mode="after")
    def validate_delegation_signing_key(self) -> Settings:
        if self.verifier_enabled:
            value = self.delegation_signing_key.get_secret_value().encode("utf-8")
            if len(value) < 32:
                raise ValueError("delegation signing key must contain at least 32 UTF-8 bytes")
        return self

    @model_validator(mode="after")
    def validate_openai_capabilities(self) -> Settings:
        """JSON Schema support also satisfies the less specific JSON-mode capability."""
        if self.openai_json_schema_enabled:
            self.openai_json_mode_enabled = True
        return self

    @model_validator(mode="after")
    def validate_ollama_capabilities(self) -> Settings:
        """JSON Schema support also satisfies Ollama's general JSON mode."""
        if self.ollama_json_schema_enabled:
            self.ollama_json_mode_enabled = True
        return self

    # Agent
    agent_max_iterations: int = 5
    agent_token_budget: int = 64_000
    agent_deadline_seconds: float = Field(default=300.0, ge=1.0, le=600.0)
    rag_deadline_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    structured_output_retries: int = Field(default=1, ge=0, le=2)
    durable_monetary_budget_enabled: bool = False
    durable_effect_ledger_enabled: bool = False
    effect_identity_secret: SecretStr = SecretStr("")
    agent_run_budget_usd: Decimal = Field(default=Decimal("50.00"), ge=0, le=1_000_000)
    agent_project_budget_usd: Decimal = Field(default=Decimal("500.00"), ge=0, le=1_000_000)
    agent_model_input_reservation_tokens: int = Field(default=64_000, ge=1, le=10_000_000)

    @field_validator("agent_run_budget_usd", "agent_project_budget_usd")
    @classmethod
    def validate_budget_decimal_scale(cls, value: Decimal) -> Decimal:
        scaled = value * Decimal(1_000_000_000)
        if scaled != scaled.to_integral_value():
            raise ValueError("budget USD values support at most nine decimal places")
        return value

    @model_validator(mode="after")
    def validate_effect_identity_secret(self) -> Settings:
        if self.durable_effect_ledger_enabled:
            secret = self.effect_identity_secret.get_secret_value().encode("utf-8")
            if len(secret) < 32:
                raise ValueError("effect identity secret must contain at least 32 UTF-8 bytes")
        return self

    approval_timeout_seconds: float = Field(default=30.0, gt=0)
    approval_poll_interval_seconds: float = Field(default=0.05, gt=0)
    context_length: int = 200000  # Claude Opus: 200K, Sonnet: 200K, llama3.1: 128K
    prompt_caching_enabled: bool = True

    model_config = {"env_prefix": "ARCHON_", "env_file": ".env", "extra": "ignore"}


def get_settings() -> Settings:
    """Factory for settings singleton."""
    return Settings()
