"""Tests for database models and session management."""

from __future__ import annotations

import pytest

from app.services.db_models import (
    AuditEntryModel,
    ConversationModel,
    DocumentChunkModel,
    DocumentModel,
    MessageModel,
)
from app.services.db_session import get_test_session_factory


class TestDatabaseModels:
    """Model creation and serialization tests."""

    @pytest.mark.unit
    def test_conversation_model(self) -> None:
        conv = ConversationModel(id="c1", title="Test Chat")
        d = conv.to_dict()
        assert d["id"] == "c1"
        assert d["title"] == "Test Chat"

    @pytest.mark.unit
    def test_message_model(self) -> None:
        msg = MessageModel(conversation_id="c1", role="user", content="Hello")
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "Hello"

    @pytest.mark.unit
    def test_audit_entry_model(self) -> None:
        entry = AuditEntryModel(
            timestamp=1234567890.0,
            agent_id="archon",
            action="test",
            resource="r1",
            correlation_id="corr-1",
        )
        d = entry.to_dict()
        assert d["agent_id"] == "archon"
        assert d["correlation_id"] == "corr-1"

    @pytest.mark.unit
    def test_document_model(self) -> None:
        doc = DocumentModel(id="d1", title="Test Doc", source="test.pdf")
        d = doc.to_dict()
        assert d["title"] == "Test Doc"

    @pytest.mark.unit
    def test_document_chunk_model(self) -> None:
        chunk = DocumentChunkModel(
            id="ch1",
            document_id="d1",
            content="Some text",
            chunk_index=0,
            content_hash="abc123",
        )
        d = chunk.to_dict()
        assert d["chunk_index"] == 0
        assert d["content_length"] == 9


class TestDatabaseSession:
    """Database session and table creation tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_create_tables(self) -> None:
        session_factory = await get_test_session_factory()
        async with session_factory() as session:
            # Tables should exist
            assert session is not None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_insert_and_query_conversation(self) -> None:
        session_factory = await get_test_session_factory()
        async with session_factory() as session:
            conv = ConversationModel(id="test-1", title="DB Test")
            session.add(conv)
            await session.commit()

            from sqlalchemy import select

            result = await session.execute(
                select(ConversationModel).where(ConversationModel.id == "test-1")
            )
            row = result.scalar_one()
            assert row.title == "DB Test"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_insert_and_query_message(self) -> None:
        session_factory = await get_test_session_factory()
        async with session_factory() as session:
            msg = MessageModel(conversation_id="c1", role="user", content="Hello DB")
            session.add(msg)
            await session.commit()

            from sqlalchemy import select

            result = await session.execute(
                select(MessageModel).where(MessageModel.conversation_id == "c1")
            )
            row = result.scalar_one()
            assert row.content == "Hello DB"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_insert_audit_entry(self) -> None:
        session_factory = await get_test_session_factory()
        async with session_factory() as session:
            entry = AuditEntryModel(
                timestamp=1000.0,
                agent_id="test",
                action="read",
                resource="file.txt",
            )
            session.add(entry)
            await session.commit()

            from sqlalchemy import select

            result = await session.execute(select(AuditEntryModel))
            row = result.scalar_one()
            assert row.action == "read"
