"""SQLAlchemy database models for persistent storage.

Tables:
- conversations: conversation metadata
- messages: encrypted conversation messages
- audit_entries: structured audit log
- documents: ingested document metadata
- document_chunks: chunked + embedded document content
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


class ConversationModel(Base):
    """Conversation metadata."""

    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(200), nullable=False, default="New Conversation")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    is_active = Column(Integer, nullable=False, default=1)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
            "is_active": bool(self.is_active),
        }


class MessageModel(Base):
    """Conversation messages (encrypted content)."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)  # encrypted in production
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (Index("idx_messages_conv_created", "conversation_id", "created_at"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class AuditEntryModel(Base):
    """Structured audit log entries."""

    __tablename__ = "audit_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(Float, nullable=False)
    agent_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    resource = Column(String(500), nullable=False)
    parameters = Column(Text, nullable=True)  # JSON
    result = Column(String(50), nullable=False, default="success")
    security_level = Column(String(20), nullable=False, default="info")
    correlation_id = Column(String(36), nullable=True)

    __table_args__ = (
        Index("idx_audit_correlation", "correlation_id"),
        Index("idx_audit_agent_action", "agent_id", "action"),
        Index("idx_audit_timestamp", "timestamp"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "action": self.action,
            "resource": self.resource,
            "parameters": self.parameters,
            "result": self.result,
            "security_level": self.security_level,
            "correlation_id": self.correlation_id,
        }


class DocumentModel(Base):
    """Ingested document metadata."""

    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    source = Column(String(500), nullable=True, default="")
    chunks_count = Column(Integer, nullable=False, default=0)
    total_characters = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "source": self.source,
            "chunks": self.chunks_count,
            "characters": self.total_characters,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class DocumentChunkModel(Base):
    """Document chunks with embeddings for vector search."""

    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), nullable=False, index=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String(16), nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON
    # embedding stored as JSON array (pgvector in production)
    embedding_json = Column(Text, nullable=True)

    __table_args__ = (Index("idx_chunks_document", "document_id"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content_length": len(self.content) if self.content else 0,
            "content_hash": self.content_hash,
        }
