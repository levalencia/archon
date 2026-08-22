"""Tests for RAG pipeline: chunking, embedding, vector search, retrieval."""

from __future__ import annotations

import pytest

from app.agents.mock_llm import MockLLM
from app.services.chunker import Document, DocumentChunk, EmbeddingService, RecursiveChunker
from app.services.rag_pipeline import RAGPipeline
from app.services.vector_store import VectorStore, cosine_similarity


class TestRecursiveChunker:
    """Document chunking tests."""

    @pytest.fixture
    def chunker(self) -> RecursiveChunker:
        return RecursiveChunker(chunk_size=100, chunk_overlap=20)

    @pytest.mark.unit
    def test_short_document_single_chunk(self, chunker: RecursiveChunker) -> None:
        doc = Document(id="d1", title="Short", content="Hello world")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world"

    @pytest.mark.unit
    def test_long_document_multiple_chunks(self) -> None:
        chunker = RecursiveChunker(chunk_size=50, chunk_overlap=10)
        content = "This is a test sentence. " * 20  # ~500 chars
        doc = Document(id="d1", title="Long", content=content)
        chunks = chunker.chunk(doc)
        assert len(chunks) > 1

    @pytest.mark.unit
    def test_chunks_have_metadata(self, chunker: RecursiveChunker) -> None:
        doc = Document(id="d1", title="Test Doc", content="Some content", source="test.pdf")
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata["title"] == "Test Doc"
        assert chunks[0].metadata["source"] == "test.pdf"

    @pytest.mark.unit
    def test_chunks_have_unique_ids(self, chunker: RecursiveChunker) -> None:
        doc = Document(id="d1", title="Test", content="A " * 200)
        chunks = chunker.chunk(doc)
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))  # All unique

    @pytest.mark.unit
    def test_empty_document_no_chunks(self, chunker: RecursiveChunker) -> None:
        doc = Document(id="d1", title="Empty", content="")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 0

    @pytest.mark.unit
    def test_chunk_index_sequential(self, chunker: RecursiveChunker) -> None:
        doc = Document(id="d1", title="Test", content="Word " * 100)
        chunks = chunker.chunk(doc)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i


class TestEmbeddingService:
    """Embedding service tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mock_embedding_dimensions(self) -> None:
        service = EmbeddingService(provider="mock", dimensions=128)
        embedding = await service.embed("test text")
        assert len(embedding) == 128

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mock_embedding_deterministic(self) -> None:
        service = EmbeddingService(provider="mock")
        e1 = await service.embed("same text")
        e2 = await service.embed("same text")
        assert e1 == e2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_different_texts_different_embeddings(self) -> None:
        service = EmbeddingService(provider="mock")
        e1 = await service.embed("text one")
        e2 = await service.embed("text two")
        assert e1 != e2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_batch_embedding(self) -> None:
        service = EmbeddingService(provider="mock", dimensions=64)
        embeddings = await service.embed_batch(["a", "b", "c"])
        assert len(embeddings) == 3
        assert all(len(e) == 64 for e in embeddings)


class TestVectorStore:
    """Vector store tests."""

    @pytest.fixture
    def store(self) -> VectorStore:
        return VectorStore()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_add_and_search(self, store: VectorStore) -> None:
        chunk = DocumentChunk(
            id="c1",
            document_id="d1",
            content="Python programming",
            chunk_index=0,
            embedding=[1.0, 0.0, 0.0],
        )
        await store.add_chunk(chunk)

        results = await store.search([1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["chunk"].id == "c1"
        assert results[0]["score"] == 1.0  # Exact match

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_ranking(self, store: VectorStore) -> None:
        c1 = DocumentChunk(
            id="c1",
            document_id="d1",
            content="Python",
            chunk_index=0,
            embedding=[1.0, 0.0, 0.0],
        )
        c2 = DocumentChunk(
            id="c2",
            document_id="d1",
            content="Java",
            chunk_index=1,
            embedding=[0.0, 1.0, 0.0],
        )
        await store.add_chunk(c1)
        await store.add_chunk(c2)

        results = await store.search([0.9, 0.1, 0.0], top_k=2)
        assert results[0]["chunk"].id == "c1"  # More similar

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_search_with_min_score(self, store: VectorStore) -> None:
        chunk = DocumentChunk(
            id="c1",
            document_id="d1",
            content="test",
            chunk_index=0,
            embedding=[1.0, 0.0, 0.0],
        )
        await store.add_chunk(chunk)

        results = await store.search([0.0, 1.0, 0.0], top_k=5, min_score=0.5)
        assert len(results) == 0  # Orthogonal vectors = 0 similarity

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_document(self, store: VectorStore) -> None:
        for i in range(3):
            chunk = DocumentChunk(
                id=f"c{i}",
                document_id="d1",
                content=f"chunk {i}",
                chunk_index=i,
                embedding=[float(i), 0.0, 0.0],
            )
            await store.add_chunk(chunk)

        deleted = await store.delete_document("d1")
        assert deleted == 3

        stats = await store.get_stats()
        assert stats["total_chunks"] == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_filter_by_document(self, store: VectorStore) -> None:
        c1 = DocumentChunk(
            id="c1",
            document_id="d1",
            content="Doc 1",
            chunk_index=0,
            embedding=[1.0, 0.0],
        )
        c2 = DocumentChunk(
            id="c2",
            document_id="d2",
            content="Doc 2",
            chunk_index=0,
            embedding=[1.0, 0.0],
        )
        await store.add_chunk(c1)
        await store.add_chunk(c2)

        results = await store.search([1.0, 0.0], document_id="d1")
        assert len(results) == 1
        assert results[0]["chunk"].document_id == "d1"

    @pytest.mark.unit
    def test_cosine_similarity_identical(self) -> None:
        assert cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0

    @pytest.mark.unit
    def test_cosine_similarity_orthogonal(self) -> None:
        assert cosine_similarity([1, 0, 0], [0, 1, 0]) == 0.0


class TestRAGPipeline:
    """End-to-end RAG pipeline tests."""

    @pytest.fixture
    async def pipeline(self) -> RAGPipeline:
        store = VectorStore()
        embedding = EmbeddingService(provider="mock", dimensions=16)
        llm = MockLLM(
            responses=["Based on the context, Python is a programming language. [Source 1]"]
        )
        return RAGPipeline(
            vector_store=store,
            embedding_service=embedding,
            llm=llm,
            top_k=3,
            min_score=-1.0,  # Accept all results in tests (mock embeddings are hash-based)
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_ingest_document(self, pipeline: RAGPipeline) -> None:
        result = await pipeline.ingest_document(
            document_id="doc-1",
            title="Python Guide",
            content="Python is a programming language. Used for web dev, data science, AI.",
            source="guide.pdf",
        )
        assert result["document_id"] == "doc-1"
        assert result["chunks_created"] >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_query_with_results(self, pipeline: RAGPipeline) -> None:
        await pipeline.ingest_document(
            document_id="doc-1",
            title="Python Guide",
            content="Python is a versatile programming language used in many fields.",
        )

        result = await pipeline.query("What is Python?")
        assert "answer" in result
        assert result["chunks_retrieved"] >= 1
        assert len(result["sources"]) >= 1

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_query_no_documents(self, pipeline: RAGPipeline) -> None:
        result = await pipeline.query("What is quantum computing?")
        assert result["chunks_retrieved"] == 0
        assert "could not find" in result["answer"].lower()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_sources_have_metadata(self, pipeline: RAGPipeline) -> None:
        await pipeline.ingest_document(
            document_id="doc-1",
            title="Test Doc",
            content="Important information about testing practices in software.",
            source="testing.pdf",
        )

        result = await pipeline.query("testing practices")
        if result["sources"]:
            source = result["sources"][0]
            assert "chunk_id" in source
            assert "document_id" in source
            assert "score" in source
            assert "excerpt" in source
