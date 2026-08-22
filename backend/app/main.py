"""Archon: Production AI Agent Webapp — FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.middleware.correlation import CorrelationIdMiddleware
from app.observability.logging import setup_logging
from app.routes.admin import router as admin_router
from app.routes.chat import router as chat_router
from app.routes.conversations import router as conversations_router
from app.routes.documents import router as documents_router

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = get_settings()

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

    # Store settings in app state for dependency injection
    app.state.settings = settings

    yield

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

    # --- Routes ---

    app.include_router(chat_router)
    app.include_router(conversations_router)
    app.include_router(documents_router)
    app.include_router(admin_router)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness probe."""
        return {"status": "alive"}

    @app.get("/readyz")
    async def readyz() -> dict:
        """Readiness probe. TODO: check DB and Redis connectivity."""
        return {"status": "ready"}

    return app


app = create_app()
