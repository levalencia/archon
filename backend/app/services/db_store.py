"""PostgreSQL-backed conversation and message store.

Replaces InMemoryStore for production. Uses SQLAlchemy async with
asyncpg driver. Falls back to aiosqlite for testing.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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


class UserRow(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(320), nullable=False, default="")
    password_hash = Column(Text, nullable=False)
    is_admin = Column(Integer, nullable=False, default=0)


class DocumentRow(Base):
    """Durable owner/project-scoped metadata for a redacted document."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_project_created", "owner_id", "project_id", "created_at"),
        CheckConstraint("status IN ('processing','ready','failed')", name="ck_documents_status"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    title = Column(String(500), nullable=False)
    source = Column(String(1000), nullable=False, default="")
    content_hash = Column(String(64), nullable=False)
    characters = Column(Integer, nullable=False)
    chunks = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="processing")
    embedding_provider = Column(String(100), nullable=False)
    embedding_model = Column(String(255), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class VectorChunkRow(Base):
    """Redacted chunk and JSON embedding; this is not a pgvector column."""

    __tablename__ = "vector_chunks"
    __table_args__ = (
        Index("ix_vector_chunks_scope_document", "owner_id", "project_id", "document_id"),
        UniqueConstraint("document_id", "chunk_index", name="uq_vector_chunk_index"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    embedding_json = Column(Text, nullable=False)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"
    id = Column(String(36), primary_key=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(100), nullable=False)


class RuntimeEventRow(Base):
    __tablename__ = "runtime_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_runtime_events_run_sequence"),
        Index("ix_runtime_events_owner_run", "user_id", "run_id"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    conversation_id = Column(String(255), nullable=False, index=True)
    correlation_id = Column(String(100), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False)
    kind = Column(String(40), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    iteration = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False, default="{}")


class RunRow(Base):
    """Durable owner-scoped runtime invocation and atomic event sequence allocator."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled')", name="ck_runs_status"
        ),
        CheckConstraint("next_sequence >= 1", name="ck_runs_next_sequence"),
        Index("ix_runs_owner_started", "user_id", "started_at"),
        Index("ix_runs_owner_project_started", "user_id", "project_id", "started_at"),
        Index("ix_runs_conversation", "conversation_id"),
    )

    run_id = Column(String(36), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    conversation_id = Column(String(255), nullable=False)
    correlation_id = Column(String(100), nullable=False)
    parent_run_id = Column(String(36), nullable=True)
    fork_source_sequence = Column(Integer, nullable=True)
    provider = Column(String(100), nullable=False, default="unknown")
    model = Column(String(255), nullable=False, default="unknown")
    schema_version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    stop_reason = Column(String(100), nullable=True)
    answer_summary = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    iterations = Column(Integer, nullable=False, default=0)
    next_sequence = Column(Integer, nullable=False, default=1)


class RunCheckpointRow(Base):
    """Privacy-safe immutable checkpoint used to create a conversation fork."""

    __tablename__ = "run_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_run_id", "source_sequence", name="uq_checkpoint_source"
        ),
        Index("ix_checkpoints_owner_project", "user_id", "project_id"),
    )
    checkpoint_id = Column(String(36), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    source_run_id = Column(
        String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    source_sequence = Column(Integer, nullable=False)
    conversation_snapshot = Column(Text, nullable=False)
    policy_profile = Column(String(100), nullable=False, default="default")
    selected_memory_ids = Column(Text, nullable=False, default="[]")
    workspace_restoration = Column(String(20), nullable=False, default="none")
    created_at = Column(DateTime(timezone=True), nullable=False)


class ForkDraftRow(Base):
    """Durable ancestry from a checkpoint to its target conversation."""

    __tablename__ = "fork_drafts"
    __table_args__ = (Index("ix_fork_drafts_owner_target", "user_id", "target_conversation_id"),)
    id = Column(String(36), primary_key=True)
    checkpoint_id = Column(
        String(36), ForeignKey("run_checkpoints.checkpoint_id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    source_run_id = Column(String(36), nullable=False)
    source_sequence = Column(Integer, nullable=False)
    target_conversation_id = Column(String(36), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ApprovalRequestRow(Base):
    """Durable exact-binding approval state; raw tool arguments are never persisted."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','denied','expired','cancelled')",
            name="ck_approval_requests_status",
        ),
        UniqueConstraint(
            "user_id", "run_id", "tool_call_id", name="uq_approval_requests_owner_run_call"
        ),
        Index("ix_approval_requests_owner", "user_id"),
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_run", "run_id"),
        Index("ix_approval_requests_call", "tool_call_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_classes: Mapped[str] = mapped_column(Text, nullable=False)
    matched_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryScopeRow(Base):
    """Transactionally serialized character accounting for one owner/project scope."""

    __tablename__ = "memory_scopes"
    __table_args__ = (
        CheckConstraint("chars_used >= 0", name="ck_memory_scopes_chars_nonnegative"),
        CheckConstraint("version >= 0", name="ck_memory_scopes_version_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    chars_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MemoryFactRow(Base):
    """Encrypted memory fact; content and provenance exist only inside ciphertext."""

    __tablename__ = "memory_facts"
    __table_args__ = (
        Index("ix_memory_facts_owner_project", "user_id", "project_id"),
        Index("ix_memory_facts_owner", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def ensure_private_sqlite_file(database_url: str) -> None:
    """Restrict an on-disk SQLite database to its owner, where applicable."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    if os.path.exists(url.database):
        os.chmod(url.database, 0o600)


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
        ensure_private_sqlite_file(str(self._engine.url))
        logger.info("database_initialized", tables=len(Base.metadata.tables))

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the supported session-factory integration point for repositories."""
        return self._session_factory

    async def close(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> None:
        """Verify that the configured database can execute a query."""
        async with self._session_factory() as session:
            await session.execute(select(1))

    async def append_runtime_event(self, event: dict[str, Any], *, max_events: int = 1000) -> None:
        """Deprecated compatibility adapter; new code uses ``RunRepository.append``."""
        from app.security.persistence_redactor import PersistenceRedactor
        from app.services.run_ledger import RunRepository

        repository = RunRepository(self._session_factory, PersistenceRedactor())
        await repository.append(
            run_id=str(event["run_id"]),
            user_id=str(event.get("user_id", "default")),
            project_id=str(event.get("project_id", "default")),
            conversation_id=str(event["conversation_id"]),
            correlation_id=str(event["correlation_id"]),
            provider=str(event.get("provider", "unknown")),
            model=str(event.get("model", "unknown")),
            kind=str(event["kind"]),
            iteration=int(event["iteration"]),
            payload=event.get("data", {}),
        )
        # Preserve the historical diagnostic bound without truncating trajectories.
        # Active runs are retained even when they temporarily exceed the budget.
        await repository.prune_terminal_to_event_budget(max_events)

    async def recent_runtime_events(
        self, *, run_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Deprecated unscoped diagnostics retained for existing internal callers."""
        async with self._session_factory() as session:
            query = select(RuntimeEventRow)
            if run_id:
                query = query.where(RuntimeEventRow.run_id == run_id)
            result = await session.execute(query.order_by(RuntimeEventRow.id.desc()).limit(limit))
            return [
                {
                    "run_id": row.run_id,
                    "conversation_id": row.conversation_id,
                    "correlation_id": row.correlation_id,
                    "kind": row.kind,
                    "iteration": row.iteration,
                    "data": json.loads(cast(str, row.payload)),
                }
                for row in reversed(result.scalars().all())
            ]

    # --- Authentication ---

    async def create_user(
        self, username: str, password_hash: str, email: str = "", *, is_admin: bool = False
    ) -> dict:
        user_id = str(uuid.uuid4())
        async with self._session_factory() as session:
            row = UserRow(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                is_admin=int(is_admin),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                msg = f"Username '{username}' already exists"
                raise ValueError(msg) from exc
        return {"user_id": user_id, "username": username, "is_admin": is_admin}

    async def get_user_by_username(self, username: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(UserRow).where(UserRow.username == username))
            row = result.scalar_one_or_none()
            return self._user_dict(row) if row is not None else None

    async def get_user(self, user_id: str) -> dict | None:
        async with self._session_factory() as session:
            row = await session.get(UserRow, user_id)
            return self._user_dict(row) if row is not None else None

    @staticmethod
    def _user_dict(row: UserRow) -> dict:
        return {
            "user_id": row.id,
            "username": row.username,
            "email": row.email,
            "password_hash": row.password_hash,
            "is_admin": bool(row.is_admin),
        }

    async def create_api_key(self, key_id: str, key_hash: str, user_id: str, name: str) -> None:
        async with self._session_factory() as session:
            session.add(ApiKeyRow(id=key_id, key_hash=key_hash, user_id=user_id, name=name))
            await session.commit()

    async def find_api_key_by_hash(self, key_hash: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash))
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {"user_id": row.user_id, "name": row.name}

    # --- Memory Store interface (for agent) ---

    async def store(self, conversation_id: str, message: dict) -> None:
        """Store a message in a conversation."""
        await self.store_message(conversation_id, message["role"], message["content"])

    async def store_message(
        self, conversation_id: str, role: str, content: str, user_id: str = "default"
    ) -> None:
        """Store a message and ensure its conversation metadata exists."""
        async with self._session_factory() as session:
            conversation = await session.get(ConversationRow, conversation_id)
            now = datetime.now(tz=UTC)
            if conversation is None:
                conversation = ConversationRow(
                    id=conversation_id, title="New Conversation", user_id=user_id
                )
                session.add(conversation)
            else:
                if conversation.user_id != user_id:
                    return
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

    async def retrieve(
        self, conversation_id: str, limit: int = 50, user_id: str | None = None
    ) -> list[dict]:
        """Retrieve messages for a conversation, optionally constrained to its owner."""
        async with self._session_factory() as session:
            query = select(MessageRow).where(MessageRow.conversation_id == conversation_id)
            if user_id is not None:
                query = query.join(
                    ConversationRow, ConversationRow.id == MessageRow.conversation_id
                ).where(ConversationRow.user_id == user_id)
            result = await session.execute(query.order_by(MessageRow.id).limit(limit))
            rows = result.scalars().all()
            return [{"role": r.role, "content": r.content} for r in rows]

    async def retrieve_through(
        self,
        conversation_id: str,
        through: datetime,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve an owner's messages at or before a timestamp in stable order."""
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(MessageRow)
                    .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
                    .where(
                        MessageRow.conversation_id == conversation_id,
                        ConversationRow.user_id == user_id,
                        MessageRow.created_at <= through,
                    )
                    .order_by(MessageRow.created_at, MessageRow.id)
                    .limit(limit)
                )
            ).all()
            return [{"role": row.role, "content": row.content} for row in rows]

    async def get_message_count(self, conversation_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(MessageRow.id)).where(
                    MessageRow.conversation_id == conversation_id
                )
            )
            return result.scalar_one()

    async def search_conversations(self, user_id: str, query: str, *, limit: int = 3) -> list[dict]:
        """Search only conversations owned by ``user_id`` using persisted DB messages."""
        terms = tuple(dict.fromkeys(word.casefold() for word in query.split() if len(word) > 2))
        if not terms:
            return []
        predicates = [
            func.lower(ConversationRow.title).contains(term)
            | func.lower(MessageRow.content).contains(term)
            for term in terms
        ]
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow, MessageRow)
                .join(MessageRow, MessageRow.conversation_id == ConversationRow.id)
                .where(ConversationRow.user_id == user_id)
                .where(*predicates)
                .order_by(ConversationRow.updated_at.desc(), MessageRow.id)
                .limit(min(max(limit, 1), 20) * 20)
            )
            grouped: dict[str, dict] = {}
            for conversation, message in result.all():
                item = grouped.setdefault(
                    conversation.id,
                    {
                        "conversation_id": conversation.id,
                        "title": conversation.title,
                        "saved_at": conversation.updated_at.isoformat(),
                        "message_count": 0,
                        "snippets": [],
                    },
                )
                item["message_count"] += 1
                item["snippets"].append(f"[{message.role}] {message.content}")
            return [
                {
                    "conversation_id": item["conversation_id"],
                    "title": item["title"],
                    "saved_at": item["saved_at"],
                    "message_count": item["message_count"],
                    "snippet": "\n".join(item["snippets"])[:300],
                }
                for item in list(grouped.values())[:limit]
            ]

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

    async def get_conversation(self, conv_id: str, user_id: str | None = None) -> dict | None:
        async with self._session_factory() as session:
            query = select(ConversationRow).where(ConversationRow.id == conv_id)
            if user_id is not None:
                query = query.where(ConversationRow.user_id == user_id)
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat()}

    async def delete_conversation(self, conv_id: str, user_id: str | None = None) -> bool:
        async with self._session_factory() as session:
            query = select(ConversationRow).where(ConversationRow.id == conv_id)
            if user_id is not None:
                query = query.where(ConversationRow.user_id == user_id)
            result = await session.execute(query)
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
