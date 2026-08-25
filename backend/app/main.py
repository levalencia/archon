"""Archon: Production AI Agent Webapp — FastAPI application."""

# ruff: noqa: E402 -- environment must be loaded before importing app configuration/routes.

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from app.config import Settings, get_settings
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.security import CSRFMiddleware, SecurityHeadersMiddleware
from app.observability.logging import setup_logging
from app.observability.otel_exporter import OTLPExporter
from app.research.api import router as research_router
from app.routes.admin import router as admin_router
from app.routes.artifacts import router as artifacts_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.conversations import router as conversations_router
from app.routes.documents import router as documents_router
from app.routes.images import router as images_router
from app.routes.log_stream import install_log_capture
from app.routes.log_stream import router as log_router
from app.routes.red_team import router as red_team_router
from app.routes.security_demo import router as security_router
from app.routes.skills import router as skills_router
from app.routes.memory import router as memory_router
from app.routes.mcp import router as mcp_router
from app.routes.multi_agent import router as multi_agent_router
from app.routes.stream import router as stream_router
from app.security.auth import AuthRepository
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = app.state.settings

    # Configure structured logging
    setup_logging(json_format=not settings.debug, log_level="DEBUG" if settings.debug else "INFO")

    install_log_capture()
    logger.info(
        "archon_starting",
        app=settings.app_name,
        version=settings.app_version,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        debug=settings.debug,
    )

    # Store settings and the unified conversation repository in app state.
    app.state.settings = settings
    repository = ConversationRepository(settings.database_url)
    await repository.initialize()
    app.state.conversations = repository
    auth_store = DatabaseStore(settings.database_url)
    await auth_store.initialize()
    app.state.auth = AuthRepository(auth_store, settings.secret_key, settings.admin_usernames)
    exporter = None
    if settings.otel_endpoint:
        exporter = OTLPExporter(settings.otel_service_name, settings.otel_endpoint)
    app.state.otel_exporter = exporter

    yield

    await repository.close()
    await auth_store.close()
    if exporter:
        exporter.shutdown()
    logger.info("archon_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory. Accepts optional settings for testing."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

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
    app.include_router(memory_router)
    app.include_router(multi_agent_router)
    app.include_router(mcp_router)

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
        dependencies = {"conversation_repository": "up"}
        try:
            await app.state.conversations.check_health()
        except Exception as error:
            dependencies["conversation_repository"] = "down"
            logger.warning(
                "readiness_check_failed", dependency="conversation_repository", error=str(error)
            )
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "dependencies": dependencies},
            )
        return {"status": "ready", "dependencies": dependencies}

    return app


app = create_app()
