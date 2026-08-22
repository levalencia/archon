"""Database connection and session management.

Uses SQLAlchemy async engine for PostgreSQL in production,
SQLite for testing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.db_models import Base


async def init_db(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Initialize database: create engine, create tables, return session factory.

    For testing: use 'sqlite+aiosqlite:///:memory:'
    For production: use 'postgresql+asyncpg://user:pass@host/db'
    """
    # SQLite needs check_same_thread=False
    connect_args = {}
    if "sqlite" in database_url:
        connect_args["check_same_thread"] = False

    engine = create_async_engine(
        database_url,
        echo=False,
        connect_args=connect_args,
    )

    # Create tables (in production, use Alembic migrations instead)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    return session_factory


async def get_test_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create an in-memory SQLite session factory for testing."""
    return await init_db("sqlite+aiosqlite:///:memory:")
