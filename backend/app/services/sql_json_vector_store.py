"""Owner-scoped SQL JSON vector retrieval.

Embeddings are JSON arrays and cosine similarity is computed in Python. This
backend intentionally never describes itself as pgvector.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.chunker import DocumentChunk
from app.services.db_store import VectorChunkRow
from app.services.vector_store import cosine_similarity


class SqlJsonVectorStore:
    """Portable SQLite/PostgreSQL JSON storage with mandatory scope predicates."""

    backend = "sql-json-cosine"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

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
            count = 0
            for chunk in chunks:
                if chunk.embedding is None:
                    continue
                db.add(
                    VectorChunkRow(
                        id=chunk.id,
                        owner_id=owner_id,
                        project_id=project_id,
                        document_id=chunk.document_id,
                        content=chunk.content,
                        chunk_index=chunk.chunk_index,
                        content_hash=chunk.content_hash,
                        metadata_json=json.dumps(chunk.metadata, sort_keys=True),
                        embedding_json=json.dumps(chunk.embedding),
                    )
                )
                count += 1
            if session is None:
                await db.commit()
            return count

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
            rows = (await session.scalars(query)).all()
        scored: list[dict[str, Any]] = []
        for row in rows:
            embedding = json.loads(str(row.embedding_json))
            score = cosine_similarity(query_embedding, embedding)
            if score >= min_score:
                scored.append(
                    {
                        "chunk": DocumentChunk(
                            id=str(row.id),
                            document_id=str(row.document_id),
                            content=str(row.content),
                            chunk_index=int(row.chunk_index),
                            metadata=json.loads(str(row.metadata_json)),
                            embedding=embedding,
                        ),
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
