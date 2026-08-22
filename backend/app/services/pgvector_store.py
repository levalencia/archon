"""PostgreSQL vector store with pgvector + BM25 hybrid search.

Replaces in-memory VectorStore for production.
Supports: vector similarity (cosine), keyword search (BM25), hybrid reranking.
"""

from __future__ import annotations

import json
import math

import structlog
from sqlalchemy import Column, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.chunker import DocumentChunk
from app.services.db_store import Base

logger = structlog.get_logger()


class ChunkRow(Base):
    __tablename__ = "vector_chunks"
    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), nullable=False, index=True)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String(16), nullable=True)
    metadata_json = Column(Text, nullable=True)
    embedding_json = Column(Text, nullable=True)  # JSON array of floats


class PgVectorStore:
    """PostgreSQL-backed vector store with hybrid search.

    Uses embedding_json column for cosine similarity.
    Falls back to keyword (BM25-style) search when embeddings unavailable.
    In production with pgvector extension: use VECTOR column + HNSW index.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Store chunks with embeddings."""
        count = 0
        async with self._sf() as session:
            for chunk in chunks:
                if chunk.embedding is None:
                    continue
                row = ChunkRow(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    content_hash=chunk.content_hash,
                    metadata_json=json.dumps(chunk.metadata),
                    embedding_json=json.dumps(chunk.embedding),
                )
                session.add(row)
                count += 1
            await session.commit()
        logger.info("pgvector_chunks_added", count=count)
        return count

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
        document_id: str | None = None,
    ) -> list[dict]:
        """Vector similarity search (cosine) in PostgreSQL."""
        async with self._sf() as session:
            q = select(ChunkRow)
            if document_id:
                q = q.where(ChunkRow.document_id == document_id)

            result = await session.execute(q)
            rows = result.scalars().all()

        # Compute cosine similarity in Python (pgvector extension would do this in SQL)
        scored = []
        for row in rows:
            if not row.embedding_json:
                continue
            emb = json.loads(row.embedding_json)
            score = self._cosine_similarity(query_embedding, emb)
            if score >= min_score:
                chunk = DocumentChunk(
                    id=row.id,
                    document_id=row.document_id,
                    content=row.content,
                    chunk_index=row.chunk_index,
                    metadata=json.loads(row.metadata_json or "{}"),
                    embedding=emb,
                )
                scored.append({"chunk": chunk, "score": round(score, 4), "method": "vector"})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def keyword_search(
        self,
        query: str,
        top_k: int = 5,
        document_id: str | None = None,
    ) -> list[dict]:
        """BM25-style keyword search using SQL LIKE."""
        keywords = [w.lower() for w in query.split() if len(w) > 2]
        if not keywords:
            return []

        async with self._sf() as session:
            q = select(ChunkRow)
            if document_id:
                q = q.where(ChunkRow.document_id == document_id)

            result = await session.execute(q)
            rows = result.scalars().all()

        # Simple BM25-inspired scoring
        scored = []
        for row in rows:
            content_lower = row.content.lower()
            tf_sum = 0
            matched_keywords = 0
            for kw in keywords:
                count = content_lower.count(kw)
                if count > 0:
                    matched_keywords += 1
                    # TF with saturation
                    tf_sum += count / (count + 1.5)

            if matched_keywords == 0:
                continue

            # IDF approximation (proportion of keywords matched)
            idf = matched_keywords / len(keywords)
            score = tf_sum * idf

            chunk = DocumentChunk(
                id=row.id,
                document_id=row.document_id,
                content=row.content,
                chunk_index=row.chunk_index,
                metadata=json.loads(row.metadata_json or "{}"),
            )
            scored.append({"chunk": chunk, "score": round(score, 4), "method": "bm25"})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int = 5,
        vector_weight: float = 0.7,
        keyword_weight: float = 0.3,
        document_id: str | None = None,
    ) -> list[dict]:
        """Hybrid search: combine vector similarity + BM25 keyword scoring.

        Uses Reciprocal Rank Fusion (RRF) to merge results.
        """
        # Get results from both methods
        vector_results = await self.search(
            query_embedding, top_k * 2, min_score=-1.0, document_id=document_id
        )
        keyword_results = await self.keyword_search(query, top_k * 2, document_id=document_id)

        # RRF scoring
        k = 60  # RRF constant
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, dict] = {}

        for rank, result in enumerate(vector_results):
            cid = result["chunk"].id
            rrf_scores[cid] = rrf_scores.get(cid, 0) + vector_weight / (k + rank + 1)
            chunk_map[cid] = result

        for rank, result in enumerate(keyword_results):
            cid = result["chunk"].id
            rrf_scores[cid] = rrf_scores.get(cid, 0) + keyword_weight / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = result

        # Sort by RRF score
        ranked = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        results = []
        for cid, score in ranked[:top_k]:
            entry = chunk_map[cid].copy()
            entry["score"] = round(score, 4)
            entry["method"] = "hybrid"
            results.append(entry)

        logger.info(
            "hybrid_search",
            vector_hits=len(vector_results),
            keyword_hits=len(keyword_results),
            merged=len(results),
        )

        return results

    async def delete_document(self, document_id: str) -> int:
        """Delete all chunks for a document."""
        async with self._sf() as session:
            result = await session.execute(
                select(ChunkRow).where(ChunkRow.document_id == document_id)
            )
            rows = result.scalars().all()
            for row in rows:
                await session.delete(row)
            await session.commit()
            return len(rows)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
