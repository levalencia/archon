"""Owner-scoped SQL JSON vector retrieval.

Embeddings are JSON arrays and cosine similarity is computed in Python. This
backend intentionally never describes itself as pgvector.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.chunker import DocumentChunk, canonical_content_hash, validate_embedding
from app.services.db_store import VectorChunkRow
from app.services.vector_store import cosine_similarity

logger = logging.getLogger(__name__)
_CONTENT_HASH = re.compile(r"^[0-9a-f]{16}$")


class SqlJsonVectorStore:
    """Portable SQLite/PostgreSQL JSON storage with mandatory scope predicates."""

    backend = "sql-json-cosine"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        dimensions: int | None = None,
        candidate_limit: int = 10_000,
        max_chunks_per_document: int = 4_096,
    ) -> None:
        self._sf = session_factory
        self.dimensions = dimensions
        self.candidate_limit = candidate_limit
        self.max_chunks_per_document = max_chunks_per_document

    @asynccontextmanager
    async def _session(self, supplied: AsyncSession | None = None) -> AsyncIterator[AsyncSession]:
        if supplied is not None:
            yield supplied
        else:
            async with self._sf() as session:
                yield session

    async def add_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        owner_id: str,
        project_id: str,
        session: AsyncSession | None = None,
    ) -> int:
        async with self._session(session) as db:
            if len(chunks) > self.max_chunks_per_document:
                raise ValueError("Chunk batch exceeds configured per-document limit")
            validated: list[tuple[DocumentChunk, list[float]]] = []
            for chunk in chunks:
                if chunk.embedding is None:
                    raise ValueError(f"Chunk {chunk.id} has no embedding")
                dimensions = self.dimensions or len(chunk.embedding)
                embedding = validate_embedding(
                    chunk.embedding, dimensions, source="stored embedding"
                )
                validated.append((chunk, embedding))
            for chunk, embedding in validated:
                db.add(
                    VectorChunkRow(
                        id=chunk.id,
                        owner_id=owner_id,
                        project_id=project_id,
                        document_id=chunk.document_id,
                        content=chunk.content,
                        chunk_index=chunk.chunk_index,
                        content_hash=canonical_content_hash(chunk.content),
                        metadata_json=json.dumps(chunk.metadata, sort_keys=True),
                        embedding_json=json.dumps(embedding, allow_nan=False),
                    )
                )
            if session is None:
                await db.commit()
            return len(validated)

    async def search(
        self,
        query_embedding: list[float],
        *,
        owner_id: str,
        project_id: str,
        top_k: int = 5,
        min_score: float = 0.0,
        document_id: str | None = None,
        document_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        dimensions = self.dimensions or len(query_embedding)
        query_embedding = validate_embedding(query_embedding, dimensions, source="query embedding")
        async with self._sf() as session:
            query = select(VectorChunkRow).where(
                VectorChunkRow.owner_id == owner_id,
                VectorChunkRow.project_id == project_id,
            )
            if document_id is not None:
                query = query.where(VectorChunkRow.document_id == document_id)
            if document_ids is not None:
                if not document_ids:
                    return []
                query = query.where(VectorChunkRow.document_id.in_(document_ids))
            query = query.order_by(VectorChunkRow.id).limit(self.candidate_limit)
            rows = (await session.scalars(query)).all()
        scored: list[dict[str, Any]] = []
        for row in rows:
            try:
                content = row.content
                persisted_hash = row.content_hash
                if not isinstance(content, str):
                    raise ValueError("content is not text")
                if not isinstance(persisted_hash, str) or not _CONTENT_HASH.fullmatch(
                    persisted_hash
                ):
                    raise ValueError("content hash has an invalid format")
                computed_hash = canonical_content_hash(content)
                if not hmac.compare_digest(persisted_hash, computed_hash):
                    raise ValueError("content hash does not match content")
                embedding = validate_embedding(
                    json.loads(str(row.embedding_json)), dimensions, source="stored embedding"
                )
                metadata = json.loads(str(row.metadata_json))
                if not isinstance(metadata, dict):
                    raise ValueError("metadata is not an object")
                score = cosine_similarity(query_embedding, embedding)
                chunk = DocumentChunk(
                    id=str(row.id),
                    document_id=str(row.document_id),
                    content=content,
                    chunk_index=int(row.chunk_index),
                    metadata=metadata,
                    embedding=embedding,
                    persisted_content_hash=persisted_hash,
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                logger.warning("corrupt_vector_row_skipped")
                continue
            if score >= min_score:
                scored.append(
                    {
                        "chunk": chunk,
                        "score": round(score, 4),
                        "method": "sql-json-cosine",
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    async def delete_document(
        self,
        document_id: str,
        *,
        owner_id: str,
        project_id: str,
        session: AsyncSession | None = None,
    ) -> int:
        async with self._session(session) as db:
            result = cast(
                CursorResult[Any],
                await db.execute(
                    delete(VectorChunkRow).where(
                        VectorChunkRow.owner_id == owner_id,
                        VectorChunkRow.project_id == project_id,
                        VectorChunkRow.document_id == document_id,
                    )
                ),
            )
            if session is None:
                await db.commit()
            return int(result.rowcount or 0)

    async def get_stats(self, *, owner_id: str, project_id: str) -> dict[str, int | str]:
        async with self._sf() as session:
            total_chunks = await session.scalar(
                select(func.count())
                .select_from(VectorChunkRow)
                .where(VectorChunkRow.owner_id == owner_id, VectorChunkRow.project_id == project_id)
            )
            total_documents = await session.scalar(
                select(func.count(func.distinct(VectorChunkRow.document_id))).where(
                    VectorChunkRow.owner_id == owner_id, VectorChunkRow.project_id == project_id
                )
            )
        return {
            "total_chunks": total_chunks or 0,
            "total_documents": total_documents or 0,
            "store_type": self.backend,
        }


PostgresJsonVectorStore = SqlJsonVectorStore
# Import compatibility only. New code, UI, logs and readiness must use SqlJsonVectorStore.
PgVectorStore = SqlJsonVectorStore
ChunkRow = VectorChunkRow
