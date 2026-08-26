"""Document chunking service for RAG pipeline.

Splits documents into overlapping chunks for embedding and retrieval.
Supports recursive character splitting with configurable chunk size and overlap.

See: https://github.com/levalencia/production-ai-agents/
Concept: RAG Pipeline — document ingestion (chunk → embed → store)
Course reference: Advanced Architectures L19-L21
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import socket
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import structlog

from app.observability.logging import safe_value_metadata

logger = structlog.get_logger()


def validate_embedding(
    vector: object, dimensions: int, *, source: str = "embedding"
) -> list[float]:
    """Return a normalized vector only when every value is finite, numeric and exact-size."""
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise ValueError(f"{source} must contain exactly {dimensions} values")
    normalized: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{source} contains a non-numeric value")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{source} contains a non-finite value")
        normalized.append(number)
    return normalized


def validate_embedding_endpoint(
    base_url: str, *, allowed_hosts: set[str], allow_private: bool
) -> str:
    """Validate an embedding endpoint before credentials can be sent to it."""
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Embedding base URL must use HTTPS and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Embedding base URL must not contain credentials, query, or fragment")
    host = parsed.hostname.rstrip(".").lower()
    normalized_allowed = {item.rstrip(".").lower() for item in allowed_hosts if item}
    if host not in normalized_allowed:
        raise ValueError("Embedding endpoint host is not explicitly allowed")
    if (host == "localhost" or host.endswith(".localhost")) and not allow_private:
        raise ValueError("Private embedding endpoints require explicit opt-in")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not allow_private:
            raise ValueError("IP-literal embedding endpoints require explicit opt-in")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("Embedding endpoint host could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global and not allow_private:
            raise ValueError("Private embedding endpoints require explicit opt-in")
    return base_url.rstrip("/")


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


@dataclass(frozen=True, slots=True)
class EmbeddingCapability:
    provider: str
    model: str
    dimensions: int
    mock: bool
    readiness: str


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
            **safe_value_metadata("title", document.title),
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
        base_url: str = "https://api.openai.com/v1",
        allowed_hosts: str = "api.openai.com",
        allow_private_endpoint: bool = False,
    ) -> None:
        if provider not in {"mock", "openai"}:
            raise ValueError(f"Unsupported embedding provider: {provider}")
        if not 1 <= dimensions <= 4096:
            raise ValueError("Embedding dimensions must be between 1 and 4096")
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.dimensions = dimensions
        self.base_url = validate_embedding_endpoint(
            base_url,
            allowed_hosts={host.strip() for host in allowed_hosts.split(",")},
            allow_private=allow_private_endpoint,
        )

    def validate_configuration(self) -> None:
        """Fail startup for a configured real provider without credentials."""
        if self.provider != "mock" and not self.api_key:
            raise ValueError("Configured embedding provider requires an API key")

    @property
    def capability(self) -> EmbeddingCapability:
        is_mock = self.provider == "mock"
        return EmbeddingCapability(
            provider=self.provider,
            model=self.model,
            dimensions=self.dimensions,
            mock=is_mock,
            readiness="non-production" if is_mock else "ready",
        )

    async def close(self) -> None:
        """Lifecycle hook; HTTP clients are request-bounded."""

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        if self.provider == "mock":
            return self._mock_embed(text)
        if self.provider == "openai":
            results = await self._openai_embed([text])
            return results[0]

        msg = f"Embedding provider '{self.provider}' not yet implemented"
        raise NotImplementedError(msg)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if self.provider == "openai":
            return await self._openai_embed(texts)
        return [await self.embed(text) for text in texts]

    async def _openai_embed(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embeddings API via httpx."""
        import httpx

        if not self.api_key:
            msg = (
                "OpenAI embedding provider requires an API key "
                "(set embedding_api_key or llm_api_key)"
            )
            raise ValueError(msg)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": self.model,
                    "dimensions": self.dimensions,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("Embedding provider returned an invalid payload")
        raw_items = data["data"]
        indexed_items: list[tuple[int, dict[str, object]]] = []
        for position, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ValueError("Embedding provider returned invalid items")
            index = item.get("index", position)
            if isinstance(index, bool) or not isinstance(index, int):
                raise ValueError("Embedding provider returned invalid indexes")
            indexed_items.append((index, item))
        indexed_items.sort(key=lambda pair: pair[0])
        if [index for index, _ in indexed_items] != list(range(len(texts))):
            raise ValueError("Embedding provider returned invalid indexes")
        embeddings = [
            validate_embedding(item.get("embedding"), self.dimensions, source="provider embedding")
            for _, item in indexed_items
        ]
        if len(embeddings) != len(texts):
            raise ValueError("Embedding provider returned an unexpected response count")
        return embeddings

    def _mock_embed(self, text: str) -> list[float]:
        """Deterministic mock embedding based on text hash.

        Same text always produces same embedding (useful for testing).
        """
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        values = []
        for i in range(0, min(len(text_hash) * 2, self.dimensions * 2), 2):
            idx = i % len(text_hash)
            byte_val = int(text_hash[idx : idx + 2], 16)
            values.append((byte_val / 255.0) * 2 - 1)  # Normalize to [-1, 1]

        # Pad or truncate to exact dimensions
        while len(values) < self.dimensions:
            values.append(0.0)
        return values[: self.dimensions]
