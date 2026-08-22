"""Vector store for RAG retrieval. In-memory implementation for testing.

Production uses pgvector; this mock uses cosine similarity on numpy-free vectors.

See: https://github.com/levalencia/production-ai-agents/
Concept: RAG Pipeline — vector search and retrieval
Course reference: Advanced Architectures L20-L23
"""

from __future__ import annotations

import math

import structlog

from app.services.chunker import DocumentChunk

logger = structlog.get_logger()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (no numpy needed)."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """In-memory vector store for RAG retrieval.

    Stores document chunks with their embeddings and supports
    similarity search via cosine distance.

    In production, this would be backed by pgvector or similar.
    """

    def __init__(self) -> None:
        self._chunks: dict[str, DocumentChunk] = {}
        self._documents: dict[str, list[str]] = {}  # doc_id → chunk_ids

    async def add_chunk(self, chunk: DocumentChunk) -> None:
        """Add a chunk with its embedding to the store."""
        if chunk.embedding is None:
            msg = f"Chunk {chunk.id} has no embedding"
            raise ValueError(msg)

        self._chunks[chunk.id] = chunk
        self._documents.setdefault(chunk.document_id, []).append(chunk.id)

    async def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Add multiple chunks. Returns count of successfully added."""
        count = 0
        for chunk in chunks:
            if chunk.embedding is not None:
                await self.add_chunk(chunk)
                count += 1
        logger.info("vector_store_added", chunks_added=count)
        return count

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        min_score: float = 0.0,
        document_id: str | None = None,
    ) -> list[dict]:
        """Search for similar chunks by cosine similarity.

        Returns list of {chunk, score} sorted by descending score.
        """
        results = []

        for chunk in self._chunks.values():
            if document_id and chunk.document_id != document_id:
                continue
            if chunk.embedding is None:
                continue

            score = cosine_similarity(query_embedding, chunk.embedding)
            if score >= min_score:
                results.append(
                    {
                        "chunk": chunk,
                        "score": round(score, 4),
                    }
                )

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    async def delete_document(self, document_id: str) -> int:
        """Delete all chunks for a document. Returns count deleted."""
        chunk_ids = self._documents.pop(document_id, [])
        for cid in chunk_ids:
            self._chunks.pop(cid, None)
        return len(chunk_ids)

    async def get_stats(self) -> dict:
        """Get store statistics."""
        return {
            "total_chunks": len(self._chunks),
            "total_documents": len(self._documents),
            "embedding_dimensions": (
                len(next(iter(self._chunks.values())).embedding)
                if self._chunks and next(iter(self._chunks.values())).embedding
                else 0
            ),
        }
