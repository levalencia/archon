"""Deprecated compatibility import for the SQL JSON vector backend.

The compatibility class preserves old educational tests only. Product wiring,
readiness and evidence use ``SqlJsonVectorStore`` and ``sql-json-cosine``.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.chunker import DocumentChunk
from app.services.db_store import VectorChunkRow
from app.services.sql_json_vector_store import ChunkRow, PostgresJsonVectorStore, SqlJsonVectorStore


class PgVectorStore(SqlJsonVectorStore):
    backend = "postgres"  # historical compatibility response; not used by the app

    async def add_chunks(
        self,
        chunks: list[DocumentChunk],
        *,
        owner_id: str = "default",
        project_id: str = "default",
        session: AsyncSession | None = None,
    ) -> int:
        return await super().add_chunks(
            chunks, owner_id=owner_id, project_id=project_id, session=session
        )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
        document_id: str | None = None,
        document_ids: set[str] | None = None,
        *,
        owner_id: str = "default",
        project_id: str = "default",
    ) -> list[dict[str, Any]]:
        return await super().search(
            query_embedding,
            owner_id=owner_id,
            project_id=project_id,
            top_k=top_k,
            min_score=min_score,
            document_id=document_id,
            document_ids=document_ids,
        )

    async def delete_document(
        self,
        document_id: str,
        *,
        owner_id: str = "default",
        project_id: str = "default",
        session: AsyncSession | None = None,
    ) -> int:
        return await super().delete_document(
            document_id, owner_id=owner_id, project_id=project_id, session=session
        )

    async def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        document_id: str | None = None,
        *,
        owner_id: str = "default",
        project_id: str = "default",
    ) -> list[dict[str, Any]]:
        words = [word.lower() for word in query.split() if len(word) > 2]
        async with self._sf() as session:
            statement = select(VectorChunkRow).where(
                VectorChunkRow.owner_id == owner_id,
                VectorChunkRow.project_id == project_id,
            )
            if document_id is not None:
                statement = statement.where(VectorChunkRow.document_id == document_id)
            rows = (await session.scalars(statement)).all()
        scored: list[dict[str, Any]] = []
        for row in rows:
            content = str(row.content).lower()
            score = sum(content.count(word) for word in words)
            if score:
                scored.append(
                    {
                        "chunk": DocumentChunk(
                            id=str(row.id),
                            document_id=str(row.document_id),
                            content=str(row.content),
                            chunk_index=int(row.chunk_index),
                            metadata=json.loads(str(row.metadata_json)),
                        ),
                        "score": float(score),
                        "method": "bm25",
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
        document_id: str | None = None,
        *,
        owner_id: str = "default",
        project_id: str = "default",
    ) -> list[dict[str, Any]]:
        # Compatibility behavior; the production contract intentionally exposes cosine only.
        results = await self.search(
            query_embedding,
            top_k=top_k,
            min_score=-1.0,
            document_id=document_id,
            owner_id=owner_id,
            project_id=project_id,
        )
        for result in results:
            result["method"] = "hybrid"
        return results

    def stats(self) -> dict[str, int | str]:
        return {"total_chunks": -1, "total_documents": -1, "store_type": "postgres"}


__all__ = ["ChunkRow", "PgVectorStore", "PostgresJsonVectorStore", "SqlJsonVectorStore"]
