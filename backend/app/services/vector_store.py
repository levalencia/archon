"""Portable owner/project-scoped vector-store contract and memory implementation."""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from app.services.chunker import DocumentChunk


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity, rejecting silently truncated vectors."""
    if len(a) != len(b):
        raise ValueError("Embedding dimensions do not match")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return 0.0 if norm_a == 0 or norm_b == 0 else dot / (norm_a * norm_b)


@runtime_checkable
class VectorStoreProtocol(Protocol):
    backend: str

    async def add_chunks(
        self, chunks: list[DocumentChunk], *, owner_id: str, project_id: str
    ) -> int: ...
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
    ) -> list[dict]: ...
    async def delete_document(self, document_id: str, *, owner_id: str, project_id: str) -> int: ...
    async def get_stats(self, *, owner_id: str, project_id: str) -> dict: ...


class MemoryVectorStore:
    """Process-local contract implementation intended only for tests."""

    backend = "memory"

    def __init__(self) -> None:
        self._chunks: dict[tuple[str, str, str], DocumentChunk] = {}

    async def add_chunks(
        self, chunks: list[DocumentChunk], *, owner_id: str = "default", project_id: str = "default"
    ) -> int:
        count = 0
        for chunk in chunks:
            if chunk.embedding is not None:
                self._chunks[(owner_id, project_id, chunk.id)] = chunk
                count += 1
        return count

    async def add_chunk(
        self, chunk: DocumentChunk, *, owner_id: str = "default", project_id: str = "default"
    ) -> None:
        if chunk.embedding is None:
            raise ValueError(f"Chunk {chunk.id} has no embedding")
        await self.add_chunks([chunk], owner_id=owner_id, project_id=project_id)

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
    ) -> list[dict]:
        results: list[dict] = []
        for (owner, project, _), chunk in self._chunks.items():
            if owner != owner_id or project != project_id:
                continue
            if document_id is not None and chunk.document_id != document_id:
                continue
            if document_ids is not None and chunk.document_id not in document_ids:
                continue
            if chunk.embedding is None:
                continue
            score = cosine_similarity(query_embedding, chunk.embedding)
            if score >= min_score:
                results.append({"chunk": chunk, "score": round(score, 4), "method": "cosine"})
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:top_k]

    async def delete_document(
        self, document_id: str, *, owner_id: str = "default", project_id: str = "default"
    ) -> int:
        keys = [
            key
            for key, chunk in self._chunks.items()
            if key[:2] == (owner_id, project_id) and chunk.document_id == document_id
        ]
        for key in keys:
            del self._chunks[key]
        return len(keys)

    async def get_stats(self, *, owner_id: str = "default", project_id: str = "default") -> dict:
        chunks = [
            chunk
            for (owner, project, _), chunk in self._chunks.items()
            if (owner, project) == (owner_id, project_id)
        ]
        return {
            "total_chunks": len(chunks),
            "total_documents": len({chunk.document_id for chunk in chunks}),
            "store_type": self.backend,
        }

    def stats(self) -> dict:
        return {
            "total_chunks": len(self._chunks),
            "total_documents": len({chunk.document_id for chunk in self._chunks.values()}),
            "store_type": self.backend,
        }


# Kept for source compatibility. Product wiring and evidence use the honest name.
VectorStore = MemoryVectorStore
