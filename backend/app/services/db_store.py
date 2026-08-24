"""PostgreSQL-backed conversation and message store.

Replaces InMemoryStore for production. Uses SQLAlchemy async with
asyncpg driver. Falls back to aiosqlite for testing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from sqlalchemy import Column, DateTime, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = structlog.get_logger()


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True)
    title = Column(String(200), nullable=False, default="New Conversation")
    user_id = Column(String(36), nullable=False, default="default")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        onupdate=lambda: datetime.now(tz=UTC),
    )
    is_active = Column(Integer, default=1)


class MessageRow(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))


class AuditRow(Base):
    __tablename__ = "audit_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String(30), nullable=False)
    agent_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    resource = Column(String(500), nullable=False)
    parameters = Column(Text, nullable=True)
    result = Column(String(50), default="success")
    security_level = Column(String(20), default="info")
    correlation_id = Column(String(36), nullable=True, index=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    message_id = Column(String(36), nullable=True)
    title = Column(String(200), nullable=False)
    artifact_type = Column(String(20), nullable=False)
    language = Column(String(20), nullable=True)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))


class DatabaseStore:
    """PostgreSQL-backed store for conversations, messages, audit, artifacts.

    Usage:
        store = DatabaseStore("postgresql+asyncpg://user:pass@localhost/archon")
        await store.initialize()
        await store.store("conv-1", {"role": "user", "content": "hello"})
    """

    def __init__(self, database_url: str) -> None:
        connect_args = {}
        if "sqlite" in database_url:
            connect_args["check_same_thread"] = False

        self._engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def initialize(self) -> None:
        """Create all tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database_initialized", tables=len(Base.metadata.tables))

    async def close(self) -> None:
        await self._engine.dispose()

    # --- Memory Store interface (for agent) ---

    async def store(self, conversation_id: str, message: dict) -> None:
        """Store a message in a conversation."""
        await self.store_message(conversation_id, message["role"], message["content"])

    async def store_message(self, conversation_id: str, role: str, content: str) -> None:
        """Store a message and ensure its conversation metadata exists."""
        async with self._session_factory() as session:
            conversation = await session.get(ConversationRow, conversation_id)
            now = datetime.now(tz=UTC)
            if conversation is None:
                conversation = ConversationRow(id=conversation_id, title="New Conversation")
                session.add(conversation)
            else:
                conversation.is_active = 1
                conversation.updated_at = now
            row = MessageRow(
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=now,
            )
            session.add(row)
            await session.commit()

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict]:
        """Retrieve messages for a conversation."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .order_by(MessageRow.id)
                .limit(limit)
            )
            rows = result.scalars().all()
            return [{"role": r.role, "content": r.content} for r in rows]

    async def get_message_count(self, conversation_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(MessageRow.id)).where(
                    MessageRow.conversation_id == conversation_id
                )
            )
            return result.scalar_one()

    # --- Conversation CRUD ---

    async def create_conversation(self, conv_id: str, title: str, user_id: str = "default") -> dict:
        async with self._session_factory() as session:
            row = ConversationRow(id=conv_id, title=title, user_id=user_id)
            session.add(row)
            await session.commit()
            return {"id": conv_id, "title": title, "user_id": user_id}

    async def list_conversations(self, user_id: str = "default") -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow, func.count(MessageRow.id))
                .outerjoin(MessageRow, MessageRow.conversation_id == ConversationRow.id)
                .where(ConversationRow.user_id == user_id)
                .where(ConversationRow.is_active == 1)
                .group_by(ConversationRow.id)
                .order_by(ConversationRow.updated_at.desc())
            )
            rows = result.all()
            return [
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "created_at": conversation.created_at.isoformat(),
                    "message_count": message_count,
                }
                for conversation, message_count in rows
            ]

    async def get_conversation(self, conv_id: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow).where(ConversationRow.id == conv_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat()}

    async def delete_conversation(self, conv_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow).where(ConversationRow.id == conv_id)
            )
            row = result.scalar_one_or_none()
            if row:
                await session.execute(
                    delete(MessageRow).where(MessageRow.conversation_id == conv_id)
                )
                await session.delete(row)
                await session.commit()
                return True
            return False

    # --- Audit ---

    async def log_audit(self, entry: dict) -> None:
        async with self._session_factory() as session:
            row = AuditRow(
                timestamp=entry.get("timestamp", ""),
                agent_id=entry.get("agent_id", ""),
                action=entry.get("action", ""),
                resource=entry.get("resource", ""),
                parameters=json.dumps(entry.get("parameters", {})),
                result=entry.get("result", "success"),
                security_level=entry.get("security_level", "info"),
                correlation_id=entry.get("correlation_id", ""),
            )
            session.add(row)
            await session.commit()

    async def get_audit_entries(self, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
            )
            rows = result.scalars().all()
            return [
                {
                    "timestamp": r.timestamp,
                    "agent_id": r.agent_id,
                    "action": r.action,
                    "resource": r.resource,
                    "result": r.result,
                    "security_level": r.security_level,
                    "correlation_id": r.correlation_id,
                }
                for r in rows
            ]

    # --- Artifacts ---

    async def save_artifact(self, artifact: dict) -> dict:
        async with self._session_factory() as session:
            row = ArtifactRow(
                id=artifact["id"],
                conversation_id=artifact.get("conversation_id", ""),
                message_id=artifact.get("message_id", ""),
                title=artifact["title"],
                artifact_type=artifact["type"],
                language=artifact.get("language", ""),
                content=artifact["content"],
                version=artifact.get("version", 1),
            )
            session.add(row)
            await session.commit()
            return artifact

    async def get_artifact(self, artifact_id: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(ArtifactRow).where(ArtifactRow.id == artifact_id))
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "title": row.title,
                "type": row.artifact_type,
                "language": row.language,
                "content": row.content,
                "version": row.version,
            }

    async def list_artifacts(self, conversation_id: str = "") -> list[dict]:
        async with self._session_factory() as session:
            q = select(ArtifactRow)
            if conversation_id:
                q = q.where(ArtifactRow.conversation_id == conversation_id)
            q = q.order_by(ArtifactRow.created_at.desc())
            result = await session.execute(q)
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "conversation_id": r.conversation_id,
                    "title": r.title,
                    "type": r.artifact_type,
                    "language": r.language,
                    "content_length": len(r.content),
                    "version": r.version,
                }
                for r in rows
            ]
