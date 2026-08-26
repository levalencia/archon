"""Transactional durable document repository and ingestion service."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.persistence_redactor import PersistenceRedactor
from app.services.chunker import Document, EmbeddingService, RecursiveChunker
from app.services.db_store import DocumentRow
from app.services.sql_json_vector_store import SqlJsonVectorStore


class DocumentRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        vector_store: SqlJsonVectorStore,
        embeddings: EmbeddingService,
        redactor: PersistenceRedactor,
    ) -> None:
        self._sf = session_factory
        self.vector_store = vector_store
        self.embeddings = embeddings
        self.redactor = redactor

    async def ingest(
        self, *, owner_id: str, project_id: str, title: str, source: str, content: str
    ) -> DocumentRow:
        # Redact before chunking, embedding, hashing, metadata creation, or persistence.
        safe_title = self.redactor.redact_text(title).text
        safe_source = self.redactor.redact_text(source).text
        safe_content = self.redactor.redact_text(content).text
        document_id = str(uuid.uuid4())
        chunks = RecursiveChunker().chunk(
            Document(id=document_id, title=safe_title, source=safe_source, content=safe_content)
        )
        embeddings = await self.embeddings.embed_batch([chunk.content for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk.embedding = embedding
        now = datetime.now(tz=UTC)
        capability = self.embeddings.capability
        row = DocumentRow(
            id=document_id,
            owner_id=owner_id,
            project_id=project_id,
            title=safe_title,
            source=safe_source,
            content_hash=hashlib.sha256(safe_content.encode()).hexdigest(),
            characters=len(safe_content),
            chunks=len(chunks),
            status="ready",
            embedding_provider=capability.provider,
            embedding_model=capability.model,
            embedding_dimensions=capability.dimensions,
            created_at=now,
            updated_at=now,
        )
        async with self._sf() as session:
            try:
                async with session.begin():
                    session.add(row)
                    await session.flush()  # Ensure the FK parent exists first.
                    added = await self.vector_store.add_chunks(
                        chunks, owner_id=owner_id, project_id=project_id, session=session
                    )
                    if added != len(chunks):
                        raise RuntimeError("Not every document chunk had an embedding")
            except Exception:
                await session.rollback()
                raise
        return row

    async def get(self, *, owner_id: str, project_id: str, document_id: str) -> DocumentRow | None:
        async with self._sf() as session:
            return cast(
                DocumentRow | None,
                await session.scalar(
                    select(DocumentRow).where(
                        DocumentRow.id == document_id,
                        DocumentRow.owner_id == owner_id,
                        DocumentRow.project_id == project_id,
                    )
                ),
            )

    async def list(self, *, owner_id: str, project_id: str) -> list[DocumentRow]:
        async with self._sf() as session:
            return list(
                (
                    await session.scalars(
                        select(DocumentRow)
                        .where(
                            DocumentRow.owner_id == owner_id,
                            DocumentRow.project_id == project_id,
                        )
                        .order_by(DocumentRow.created_at.desc(), DocumentRow.id)
                    )
                ).all()
            )

    async def owned_ids(self, *, owner_id: str, project_id: str) -> set[str]:
        async with self._sf() as session:
            return set(
                (
                    await session.scalars(
                        select(DocumentRow.id).where(
                            DocumentRow.owner_id == owner_id,
                            DocumentRow.project_id == project_id,
                            DocumentRow.status == "ready",
                        )
                    )
                ).all()
            )

    async def delete(self, *, owner_id: str, project_id: str, document_id: str) -> bool:
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(DocumentRow).where(
                    DocumentRow.id == document_id,
                    DocumentRow.owner_id == owner_id,
                    DocumentRow.project_id == project_id,
                )
            )
            if row is None:
                return False
            # Explicit scoped child delete is portable even when SQLite FK pragmas are off.
            await self.vector_store.delete_document(
                document_id, owner_id=owner_id, project_id=project_id, session=session
            )
            await session.execute(
                delete(DocumentRow).where(
                    DocumentRow.id == document_id,
                    DocumentRow.owner_id == owner_id,
                    DocumentRow.project_id == project_id,
                )
            )
        return True
