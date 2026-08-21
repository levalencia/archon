"""FastAPI application with structured lifespan."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import Settings, get_settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = get_settings()

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

    # Health check endpoints
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
