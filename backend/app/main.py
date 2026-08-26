"""Archon: Production AI Agent Webapp — FastAPI application."""

# ruff: noqa: E402 -- environment must be loaded before importing app configuration/routes.

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from app.agents.llm_factory import create_llm_client
from app.config import Settings, get_settings
from app.memory.keys import decode_memory_master_key
from app.memory.scoped import ScopedEncryptedMemoryRepository
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.security import CSRFMiddleware, SecurityHeadersMiddleware
from app.observability.log_buffer import OwnerLogBuffer
from app.observability.logging import safe_exception_metadata, setup_logging
from app.observability.otel_exporter import OTLPExporter
from app.research.api import router as research_router
from app.routes.admin import router as admin_router
from app.routes.artifacts import router as artifacts_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.compliance import router as compliance_router
from app.routes.conversations import router as conversations_router
from app.routes.documents import router as documents_router
from app.routes.images import router as images_router
from app.routes.log_stream import router as log_router
from app.routes.mcp import router as mcp_router
from app.routes.memory import router as memory_router
from app.routes.multi_agent import router as multi_agent_router
from app.routes.red_team import router as red_team_router
from app.routes.runs import router as runs_router
from app.routes.security_demo import router as security_router
from app.routes.skills import router as skills_router
from app.routes.stream import router as stream_router
from app.routes.tasks import router as tasks_router
from app.runtime.support import as_model_provider
from app.security.approval_repository import ApprovalRepository
from app.security.audit_logger import StructuredAuditLogger
from app.security.auth import AuthRepository
from app.security.circuit_breaker import CircuitBreaker, CircuitBreakingProvider
from app.security.live_approvals import DurableApprovalBroker
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.artifacts import ArtifactStore
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore
from app.tools.sandbox import DockerSandboxConfig, DockerSandboxExecutor, SandboxExecutor

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = app.state.settings

    # Validate before opening databases or initializing any other application resource.
    if settings.memory_encryption_enabled:
        try:
            memory_master_key = decode_memory_master_key(settings.encryption_master_key)
        except ValueError:
            raise RuntimeError("Encrypted memory startup configuration is invalid") from None
    else:
        memory_master_key = None

    app.state.sandbox_executor = None
    if settings.execution_enabled:
        sandbox_config = DockerSandboxConfig(
            binary=settings.execution_docker_binary,
            image=settings.execution_docker_image,
            platform=settings.execution_docker_platform,
            timeout_seconds=settings.execution_timeout_seconds,
            cpus=settings.execution_cpus,
            memory_mb=settings.execution_memory_mb,
            pids_limit=settings.execution_pids_limit,
            output_bytes=settings.execution_output_bytes,
        )
        executor = app.state.sandbox_executor_factory(sandbox_config)
        await executor.preflight()
        app.state.sandbox_executor = executor

    # Configure structured logging
    setup_logging(json_format=not settings.debug, log_level="DEBUG" if settings.debug else "INFO")

    logger.info(
        "archon_starting",
        app=settings.app_name,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        debug=settings.debug,
    )

    # Store settings and explicitly injected application-scoped services.
    app.state.settings = settings
    redactor = app.state.persistence_redactor_factory()
    app.state.persistence_redactor = redactor
    app.state.log_buffer = OwnerLogBuffer()
    repository = ConversationRepository(settings.database_url, redactor)
    await repository.initialize()
    app.state.conversations = repository
    auth_store = DatabaseStore(settings.database_url)
    await auth_store.initialize()
    app.state.auth = AuthRepository(auth_store, settings.secret_key, settings.admin_usernames)
    if settings.memory_encryption_enabled:
        assert memory_master_key is not None
        app.state.scoped_memory = ScopedEncryptedMemoryRepository(
            auth_store.session_factory, memory_master_key, redactor=redactor
        )
    else:
        app.state.scoped_memory = None
    app.state.approval_broker = DurableApprovalBroker(
        ApprovalRepository(auth_store.session_factory),
        timeout_seconds=settings.approval_timeout_seconds,
        poll_interval_seconds=settings.approval_poll_interval_seconds,
    )
    app.state.artifacts = ArtifactStore(redactor)
    app.state.audit_logger = StructuredAuditLogger(redactor)

    if settings.rate_limit_backend == "redis":
        from redis.asyncio import Redis

        redis = Redis.from_url(settings.redis_url)
        try:
            await redis.ping()
        except Exception as exc:
            await redis.aclose()
            raise RuntimeError("Redis rate limiter is unavailable") from exc
        app.state.rate_limiter = RateLimiter(
            redis,
            settings.rate_limit_requests,
            settings.rate_limit_window,
            owns_redis=True,
        )
    else:
        app.state.rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window,
        )

    breaker = CircuitBreaker(
        settings.circuit_breaker_failure_threshold,
        settings.circuit_breaker_recovery_timeout,
        name=settings.llm_provider,
    )
    app.state.provider_breaker = breaker
    app.state.model_provider = CircuitBreakingProvider(
        as_model_provider(app.state.model_provider_factory(settings)), breaker
    )
    exporter = None
    if settings.otel_endpoint:
        exporter = OTLPExporter(settings.otel_service_name, settings.otel_endpoint)
    app.state.otel_exporter = exporter

    yield

    await repository.close()
    await auth_store.close()
    await app.state.rate_limiter.close()
    if exporter:
        exporter.shutdown()
    logger.info("archon_shutdown")


def create_app(
    settings: Settings | None = None,
    *,
    persistence_redactor_factory: Callable[[], PersistenceRedactor] = PersistenceRedactor,
    model_provider_factory: Callable[[Settings], object] = create_llm_client,
    sandbox_executor_factory: Callable[
        [DockerSandboxConfig], SandboxExecutor
    ] = DockerSandboxExecutor,
) -> FastAPI:
    """Application factory. Accepts optional settings for testing."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.persistence_redactor_factory = persistence_redactor_factory
    app.state.model_provider_factory = model_provider_factory
    app.state.sandbox_executor_factory = sandbox_executor_factory
    app.state.sandbox_executor = None

    # --- Middleware (order matters: last added = first executed) ---

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    # Correlation ID injection
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    # --- Routes ---

    app.include_router(chat_router)
    app.include_router(log_router)
    app.include_router(stream_router)
    app.include_router(conversations_router)
    app.include_router(documents_router)
    app.include_router(admin_router)
    app.include_router(security_router)
    app.include_router(red_team_router)
    app.include_router(skills_router)
    app.include_router(auth_router)
    app.include_router(artifacts_router)
    app.include_router(images_router)
    app.include_router(research_router)
    if settings.memory_encryption_enabled:
        app.include_router(memory_router)
    app.include_router(multi_agent_router)
    app.include_router(compliance_router)
    app.include_router(mcp_router)
    app.include_router(tasks_router)
    app.include_router(runs_router)

    @app.get("/metrics")
    async def prometheus_metrics():
        from starlette.responses import Response

        from app.observability.metrics import get_prometheus_text

        return Response(get_prometheus_text(), media_type="text/plain")

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness probe — also returns model info for the UI."""
        return {
            "status": "alive",
            "llm_model": app.state.settings.llm_model,
            "llm_provider": app.state.settings.llm_provider,
        }

    @app.get("/readyz")
    async def readyz():
        """Report readiness based on a live database query."""
        dependencies = {
            "conversation_repository": "up",
            "model_provider_circuit": app.state.provider_breaker.state.value,
        }
        try:
            await app.state.conversations.check_health()
        except Exception as error:
            dependencies["conversation_repository"] = "down"
            logger.warning(
                "readiness_check_failed",
                dependency="conversation_repository",
                **safe_exception_metadata(error, "health_check_failed"),
            )
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "dependencies": dependencies},
            )
        return {"status": "ready", "dependencies": dependencies}

    return app


app = create_app()
