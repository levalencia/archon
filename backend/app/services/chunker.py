"""Document chunking service for RAG pipeline.

Splits documents into overlapping chunks for embedding and retrieval.
Supports recursive character splitting with configurable chunk size and overlap.

See: https://github.com/levalencia/production-ai-agents/
Concept: RAG Pipeline — document ingestion (chunk → embed → store)
Course reference: Advanced Architectures L19-L21
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class DocumentChunk:
    """A chunk of a document with metadata."""

    id: str
    document_id: str
    content: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()[:16]


@dataclass
class Document:
    """A document to be chunked and indexed."""

    id: str
    title: str
    content: str
    source: str = ""
    metadata: dict = field(default_factory=dict)


class RecursiveChunker:
    """Recursive character text splitter with overlap.

    Splits on paragraph boundaries first, then sentences, then words.
    Each chunk overlaps with the next for context continuity.
    """

    SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.SEPARATORS

    def chunk(self, document: Document) -> list[DocumentChunk]:
        """Split a document into overlapping chunks."""
        text = document.content.strip()
        if not text:
            return []

        raw_chunks = self._split_text(text, self.separators)

        # Merge small chunks and enforce overlap
        merged = self._merge_with_overlap(raw_chunks)

        chunks = []
        for i, content in enumerate(merged):
            chunks.append(
                DocumentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document.id,
                    content=content,
                    chunk_index=i,
                    metadata={
                        "title": document.title,
                        "source": document.source,
                        "chunk_size": len(content),
                        **document.metadata,
                    },
                )
            )

        logger.info(
            "document_chunked",
            document_id=document.id,
            title=document.title,
            original_length=len(text),
            chunks=len(chunks),
            avg_chunk_size=sum(len(c.content) for c in chunks) // max(len(chunks), 1),
        )

        return chunks

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using separators in order of preference."""
        if len(text) <= self.chunk_size:
            return [text]

        # Find the best separator that actually exists in the text
        separator = ""
        for sep in separators:
            if sep in text:
                separator = sep
                break

        if not separator:
            # Force split at chunk_size
            result = []
            for i in range(0, len(text), self.chunk_size):
                result.append(text[i : i + self.chunk_size])
            return result

        # Split and recursively process pieces that are still too large
        parts = text.split(separator)
        result = []
        current = ""

        for part in parts:
            candidate = current + separator + part if current else part

            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    result.append(current)
                if len(part) > self.chunk_size:
                    # Recursively split with next separator level
                    remaining_seps = separators[separators.index(separator) + 1 :]
                    result.extend(self._split_text(part, remaining_seps or [""]))
                    current = ""
                else:
                    current = part

        if current:
            result.append(current)

        return result

    def _merge_with_overlap(self, chunks: list[str]) -> list[str]:
        """Merge chunks and add overlap between adjacent chunks."""
        if len(chunks) <= 1:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            if i > 0 and self.chunk_overlap > 0:
                # Prepend overlap from previous chunk
                prev = chunks[i - 1]
                overlap_text = prev[-self.chunk_overlap :]
                chunk = overlap_text + " " + chunk

            result.append(chunk.strip())

        return result


class EmbeddingService:
    """Embedding generation service. Uses LLM adapters or mock for testing.

    In production: calls OpenAI text-embedding-3-small or local model.
    In testing: generates deterministic fake embeddings.
    """

    def __init__(
        self,
        provider: str = "mock",
        model: str = "text-embedding-3-small",
        api_key: str = "",
        dimensions: int = 256,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        if self.provider == "mock":
            return self._mock_embed(text)

        # TODO: Real embedding providers (OpenAI, local)
        msg = f"Embedding provider '{self.provider}' not yet implemented"
        raise NotImplementedError(msg)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return [await self.embed(text) for text in texts]

    def _mock_embed(self, text: str) -> list[float]:
        """Deterministic mock embedding based on text hash.

        Same text always produces same embedding (useful for testing).
        """
        text_hash = hashlib.md5(text.encode()).hexdigest()  # noqa: S324
        values = []
        for i in range(0, min(len(text_hash) * 2, self.dimensions * 2), 2):
            idx = i % len(text_hash)
            byte_val = int(text_hash[idx : idx + 2], 16)
            values.append((byte_val / 255.0) * 2 - 1)  # Normalize to [-1, 1]

        # Pad or truncate to exact dimensions
        while len(values) < self.dimensions:
            values.append(0.0)
        return values[: self.dimensions]
