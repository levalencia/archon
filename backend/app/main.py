"""Archon: Production AI Agent Webapp — FastAPI application."""

# ruff: noqa: E402 -- environment must be loaded before importing app configuration/routes.

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from app.agents.llm_factory import create_llm_client
from app.capabilities.index import CapabilityIndex
from app.capabilities.models import CapabilityDescriptor
from app.capabilities.persistence import CapabilityPreferenceRepository
from app.config import Settings, get_settings
from app.delegation import (
    DelegationEnvelopeService,
    EvidenceVerifierSpecialist,
    derive_delegation_hmac_key,
)
from app.eval.candidates import OptimizationCandidateService
from app.eval.drift import DriftService
from app.eval.persistence import EvaluationRepository
from app.eval.service import EvaluationService
from app.mcp.client import CredentialProvider, create_mcp_client
from app.mcp.config import load_mcp_profiles
from app.mcp.inventory import MCPInventoryService
from app.mcp.models import MCPServerProfile
from app.mcp.repository import MCPRepository
from app.mcp.runtime import MCPRuntimeToolProvider
from app.memory.keys import load_memory_keyring
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
from app.routes.capabilities import router as capabilities_router
from app.routes.chat import router as chat_router
from app.routes.compliance import router as compliance_router
from app.routes.conversations import router as conversations_router
from app.routes.documents import router as documents_router
from app.routes.evaluations import router as evaluations_router
from app.routes.images import router as images_router
from app.routes.log_stream import router as log_router
from app.routes.mcp import router as mcp_router
from app.routes.memory import router as memory_router
from app.routes.multi_agent import router as multi_agent_router
from app.routes.project_instructions import router as project_instructions_router
from app.routes.red_team import router as red_team_router
from app.routes.runs import router as runs_router
from app.routes.sandbox import router as sandbox_router
from app.routes.security_demo import router as security_router
from app.routes.shares import router as shares_router
from app.routes.skills import router as skills_router
from app.routes.stream import router as stream_router
from app.routes.tasks import router as tasks_router
from app.runtime.factory import budget_model_provider
from app.runtime.images import ImageAttachmentStore
from app.runtime.support import as_model_provider
from app.security.approval_repository import ApprovalRepository
from app.security.audit_logger import StructuredAuditLogger
from app.security.auth import AuthRepository
from app.security.circuit_breaker import CircuitBreaker, CircuitBreakingProvider
from app.security.compliance import MandatoryComplianceService
from app.security.live_approvals import DurableApprovalBroker
from app.security.persistence_redactor import PersistenceRedactor
from app.security.rate_limiter import RateLimiter
from app.services.artifacts import ArtifactStore
from app.services.chunker import EmbeddingService
from app.services.context_snapshots import ContextSnapshotRepository
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore
from app.services.documents import DocumentRepository
from app.services.key_rotation import MemoryKeyRotationService
from app.services.request_context import RequestContextPreparationService
from app.services.run_exports import RunExportService
from app.services.sql_json_vector_store import SqlJsonVectorStore
from app.services.task_queue import ClaimedJob, DurableJobQueue
from app.skills.bootstrap import BundledSkillBootstrap
from app.skills.bundled import bundled_skills
from app.skills.catalog import create_skill_catalog_provider
from app.skills.context import EffectiveContextEnrichmentService
from app.skills.discovery import SkillDiscoveryService
from app.skills.installer import HttpSkillFetcher, SkillInstallationService, SkillSourcePolicy
from app.skills.persistence import ProjectInstructionRepository, SkillRepository
from app.tools.sandbox import SandboxExecutor
from app.tools.sandbox_client import SandboxClientConfig, SandboxRunnerClient
from app.workers.jobs import JobWorker, PermanentJobError, echo_handler

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = app.state.settings
    app.state.image_attachments = ImageAttachmentStore()

    # Validate embedding capability before opening any application resources.
    app.state.embedding_service = EmbeddingService(
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key or settings.llm_api_key,
        dimensions=settings.embedding_dimensions,
        base_url=settings.embedding_base_url,
        allowed_hosts=settings.embedding_allowed_hosts,
        allow_private_endpoint=settings.embedding_allow_private_endpoint,
        api_version=settings.embedding_api_version,
    )
    app.state.embedding_service.validate_configuration()

    # Validate before opening databases or initializing any other application resource.
    if settings.memory_encryption_enabled:
        try:
            memory_keyring = load_memory_keyring(
                settings.memory_keyring_json.get_secret_value(),
                active_version=settings.memory_active_key_version,
                legacy_master_key=settings.encryption_master_key.get_secret_value(),
            )
        except ValueError:
            raise RuntimeError("Encrypted memory startup configuration is invalid") from None
    else:
        memory_keyring = None

    app.state.sandbox_executor = None
    if settings.execution_enabled:
        sandbox_config = SandboxClientConfig(
            socket_path=settings.execution_runner_socket,
            timeout_seconds=settings.execution_timeout_seconds,
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
    app.state.compliance = MandatoryComplianceService()
    app.state.log_buffer = OwnerLogBuffer()
    repository = ConversationRepository(settings.database_url, redactor)
    await repository.initialize()
    app.state.conversations = repository
    app.state.mcp_repository = MCPRepository(repository.session_factory)
    app.state.skill_repository = SkillRepository(repository.session_factory)
    app.state.instruction_repository = ProjectInstructionRepository(repository.session_factory)
    await BundledSkillBootstrap(app.state.skill_repository).install()
    app.state.skill_catalog_provider = create_skill_catalog_provider(
        enabled=settings.skill_catalog_enabled,
        allowlisted_root=settings.skill_catalog_allowlisted_root,
        executable=settings.skill_catalog_executable,
        json_index=settings.skill_catalog_json_index,
        timeout_seconds=settings.skill_catalog_timeout_seconds,
        max_stdout_bytes=settings.skill_catalog_max_stdout_bytes,
        max_results=settings.skill_catalog_max_results,
    )
    app.state.skill_discovery = SkillDiscoveryService(
        app.state.skill_repository, catalog_provider=app.state.skill_catalog_provider
    )
    app.state.context_enrichment = EffectiveContextEnrichmentService(
        app.state.skill_repository, app.state.instruction_repository
    )
    app.state.context_snapshots = ContextSnapshotRepository(repository.session_factory)
    app.state.skill_installer = SkillInstallationService(
        app.state.skill_repository,
        SkillSourcePolicy(
            allowed_repositories=frozenset(
                x.strip() for x in settings.skills_allowed_repositories.split(",") if x.strip()
            )
        ),
        HttpSkillFetcher(),
    )
    app.state.capability_preferences = CapabilityPreferenceRepository(repository.session_factory)
    app.state.request_context_preparer = RequestContextPreparationService(
        app.state.skill_discovery,
        app.state.context_enrichment,
        app.state.context_snapshots,
        app.state.capability_preferences,
    )
    # Build the searchable inventory from the same bundled packages and live native
    # registry used by requests; executable schemas remain outside this compact index.
    from app.routes.chat import get_tool_registry

    skill_descriptors = tuple(
        CapabilityDescriptor(
            id=f"archon.{item.parsed.name}",
            kind="skill",
            name=item.parsed.name,
            description=item.parsed.description,
            triggers=item.parsed.triggers,
            negative_triggers=item.parsed.negative_triggers,
            tags=item.parsed.tags,
            context_cost=item.parsed.context_cost,
            version=item.parsed.version,
            content_hash=item.parsed.content_hash,
        )
        for item in bundled_skills()
    )
    native_descriptors = get_tool_registry(
        sandbox_executor=app.state.sandbox_executor
    ).capability_descriptors()
    app.state.capability_index = CapabilityIndex((*skill_descriptors, *native_descriptors))

    def mcp_client_factory(profile: MCPServerProfile) -> Any:
        return create_mcp_client(profile, credential_provider=app.state.mcp_credential_provider)

    app.state.mcp_inventory = MCPInventoryService(
        app.state.mcp_repository, client_factory=mcp_client_factory, profiles=app.state.mcp_profiles
    )
    app.state.mcp_runtime_tools = MCPRuntimeToolProvider(
        app.state.mcp_repository, client_factory=mcp_client_factory, profiles=app.state.mcp_profiles
    )
    app.state.evaluation_repository = EvaluationRepository(repository.session_factory)
    app.state.evaluation_service = EvaluationService(
        repository.runs, app.state.evaluation_repository
    )
    app.state.drift_service = DriftService(
        repository.session_factory, app.state.evaluation_repository
    )
    app.state.run_exports = RunExportService(
        repository.session_factory, repository.runs, token_pepper=settings.secret_key
    )
    app.state.job_queue = DurableJobQueue(repository.session_factory)
    app.state.delegation_envelopes = None
    if settings.verifier_enabled:
        app.state.delegation_envelopes = DelegationEnvelopeService(
            repository.session_factory,
            {1: derive_delegation_hmac_key(settings.delegation_signing_key.get_secret_value(), 1)},
            active_key_version=1,
        )

    async def run_export_job(job: ClaimedJob) -> dict[str, Any]:
        run_id = str(job.payload["run_id"])
        run = await repository.runs.get(job.owner_id, run_id)
        if run is None or run.project_id != job.project_id:
            raise PermanentJobError("run_scope_unavailable")
        exported = await app.state.run_exports.create_export(job.owner_id, run_id)
        if exported is None:
            raise PermanentJobError("run_scope_unavailable")
        return {
            "export_id": exported.export_id,
            "run_id": exported.run_id,
            "schema_version": exported.schema_version,
            "content_checksum": exported.content_checksum,
        }

    job_worker = JobWorker(
        app.state.job_queue,
        f"web-{uuid.uuid4()}",
        handlers={"echo": echo_handler, "run_export": run_export_job},
    )
    auth_store = DatabaseStore(settings.database_url)
    await auth_store.initialize()
    app.state.auth = AuthRepository(auth_store, settings.secret_key, settings.admin_usernames)
    app.state.vector_store = SqlJsonVectorStore(
        auth_store.session_factory,
        dimensions=settings.embedding_dimensions,
        candidate_limit=settings.vector_search_candidate_limit,
        max_chunks_per_document=settings.document_max_chunks,
    )
    app.state.documents = DocumentRepository(
        auth_store.session_factory,
        app.state.vector_store,
        app.state.embedding_service,
        redactor,
        max_characters=settings.document_max_characters,
        max_documents_per_scope=settings.documents_max_per_owner_project,
        max_chunks_per_document=settings.document_max_chunks,
    )
    logger.info("vector_store_initialized", backend="sql-json-cosine")
    if settings.memory_encryption_enabled:
        assert memory_keyring is not None
        app.state.scoped_memory = ScopedEncryptedMemoryRepository(
            auth_store.session_factory, memory_keyring, redactor=redactor
        )
        await app.state.scoped_memory.activate_key_version()
        await app.state.scoped_memory.validate_key_versions()
        app.state.memory_key_rotation = MemoryKeyRotationService(app.state.scoped_memory)
    else:
        app.state.scoped_memory = None
        app.state.memory_key_rotation = None
    app.state.approval_repository = ApprovalRepository(auth_store.session_factory)
    app.state.approval_broker = DurableApprovalBroker(
        app.state.approval_repository,
        timeout_seconds=settings.approval_timeout_seconds,
        poll_interval_seconds=settings.approval_poll_interval_seconds,
    )
    app.state.optimization_candidates = OptimizationCandidateService(
        repository.session_factory, app.state.approval_repository
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
    app.state.evidence_verifier = (
        EvidenceVerifierSpecialist(
            app.state.model_provider,
            repository.runs,
            redactor,
            app.state.delegation_envelopes,
            provider_factory=lambda request: budget_model_provider(
                app.state.model_provider,
                settings=settings,
                repository=repository,
                user_id=request.user_id,
                project_id=request.project_id,
                run_id=request.child_id,
            ),
        )
        if settings.verifier_enabled
        else None
    )
    exporter = None
    if settings.otel_endpoint:
        exporter = OTLPExporter(settings.otel_service_name, settings.otel_endpoint)
    app.state.otel_exporter = exporter
    job_worker_task = asyncio.create_task(job_worker.run_forever())
    app.state.job_worker = job_worker
    app.state.job_worker_task = job_worker_task

    try:
        yield
    finally:
        job_worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await job_worker_task
        await repository.close()
        await auth_store.close()
        await app.state.rate_limiter.close()
        await app.state.embedding_service.close()
        if exporter:
            exporter.shutdown()
        logger.info("archon_shutdown")


def create_app(
    settings: Settings | None = None,
    *,
    mcp_profiles: Mapping[str, MCPServerProfile] | None = None,
    persistence_redactor_factory: Callable[[], PersistenceRedactor] = PersistenceRedactor,
    model_provider_factory: Callable[[Settings], object] = create_llm_client,
    sandbox_executor_factory: Callable[
        [SandboxClientConfig], SandboxExecutor
    ] = SandboxRunnerClient,
    mcp_credential_provider: CredentialProvider | None = None,
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
    app.state.mcp_credential_provider = mcp_credential_provider
    configured_profiles = load_mcp_profiles(settings.mcp_profiles_json.get_secret_value())
    app.state.mcp_profiles = dict(configured_profiles if mcp_profiles is None else mcp_profiles)
    app.state.persistence_redactor_factory = persistence_redactor_factory
    app.state.model_provider_factory = model_provider_factory
    app.state.sandbox_executor_factory = sandbox_executor_factory
    app.state.sandbox_executor = None
    app.state.evidence_verifier = None

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
    app.include_router(project_instructions_router)
    app.include_router(capabilities_router)
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
    app.include_router(sandbox_router)
    app.include_router(runs_router)
    app.include_router(shares_router)
    app.include_router(evaluations_router)

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
        """Report readiness based on live dependencies and durable-worker health."""
        worker_task = getattr(app.state, "job_worker_task", None)
        worker = getattr(app.state, "job_worker", None)
        worker_ready = (
            worker_task is not None
            and not worker_task.done()
            and worker is not None
            and worker.last_error_code is None
        )
        dependencies = {
            "conversation_repository": "up",
            "rate_limiter": {
                "backend": app.state.settings.rate_limit_backend,
                "status": "up",
            },
            "telemetry": (
                {"backend": "otlp-grpc", "status": "up"}
                if app.state.otel_exporter is not None and app.state.otel_exporter.is_active
                else {"backend": "otlp-grpc", "status": "down"}
                if app.state.otel_exporter is not None
                else {"backend": "disabled", "status": "disabled"}
            ),
            "model_provider_circuit": app.state.provider_breaker.state.value,
            "background_job_worker": (
                "up"
                if worker_ready
                else worker.last_error_code
                if worker is not None and worker.last_error_code
                else "down"
            ),
            "vector_store": app.state.vector_store.backend,
            "evidence_verifier": (
                "enabled" if app.state.evidence_verifier is not None else "disabled"
            ),
            "skill_catalog": app.state.skill_catalog_provider.health_code,
            "runtime_controls": {
                "durable_monetary_budget": (
                    "enabled" if app.state.settings.durable_monetary_budget_enabled else "disabled"
                ),
                "durable_effect_ledger": (
                    "enabled" if app.state.settings.durable_effect_ledger_enabled else "disabled"
                ),
                "agent_deadline_seconds": app.state.settings.agent_deadline_seconds,
                "rag_deadline_seconds": app.state.settings.rag_deadline_seconds,
            },
            "embeddings": {
                "provider": app.state.embedding_service.capability.provider,
                "model": app.state.embedding_service.capability.model,
                "dimensions": app.state.embedding_service.capability.dimensions,
                "mock": app.state.embedding_service.capability.mock,
                "readiness": app.state.embedding_service.capability.readiness,
            },
        }
        ready = worker_ready and (
            app.state.otel_exporter is None or app.state.otel_exporter.is_active
        )
        try:
            await app.state.conversations.check_health()
        except Exception as error:
            ready = False
            dependencies["conversation_repository"] = "down"
            logger.warning(
                "readiness_check_failed",
                dependency="conversation_repository",
                **safe_exception_metadata(error, "health_check_failed"),
            )
        try:
            await app.state.rate_limiter.check_health()
        except Exception as error:
            ready = False
            dependencies["rate_limiter"]["status"] = "down"
            logger.warning(
                "readiness_check_failed",
                dependency="rate_limiter",
                **safe_exception_metadata(error, "health_check_failed"),
            )
        if not ready:
            return JSONResponse(
                status_code=503, content={"status": "degraded", "dependencies": dependencies}
            )
        return {"status": "ready", "dependencies": dependencies}

    return app


app = create_app()
