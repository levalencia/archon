"""Tests for PgVectorStore with in-memory SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.chunker import DocumentChunk
from app.services.db_store import Base
from app.services.pgvector_store import PgVectorStore


@pytest.fixture
async def pg_store():
    """Create a PgVectorStore backed by in-memory SQLite for testing."""
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    store = PgVectorStore(sf)
    yield store
    await engine.dispose()


def _make_chunk(doc_id: str = "doc1", index: int = 0, embedding: list[float] | None = None):
    return DocumentChunk(
        id=f"chunk-{doc_id}-{index}",
        document_id=doc_id,
        content=f"Test content for chunk {index}",
        chunk_index=index,
        embedding=embedding or [0.1 * (index + 1)] * 4,
    )


@pytest.mark.asyncio
async def test_add_and_search(pg_store: PgVectorStore):
    chunks = [_make_chunk(index=i) for i in range(3)]
    added = await pg_store.add_chunks(chunks)
    assert added == 3

    results = await pg_store.search(query_embedding=[0.1, 0.1, 0.1, 0.1], top_k=2)
    assert len(results) == 2
    assert results[0]["score"] > 0


@pytest.mark.asyncio
async def test_keyword_search(pg_store: PgVectorStore):
    chunks = [_make_chunk(index=i) for i in range(3)]
    await pg_store.add_chunks(chunks)

    results = await pg_store.keyword_search("chunk content", top_k=2)
    assert len(results) == 2
    assert results[0]["method"] == "bm25"


@pytest.mark.asyncio
async def test_hybrid_search(pg_store: PgVectorStore):
    chunks = [_make_chunk(index=i) for i in range(3)]
    await pg_store.add_chunks(chunks)

    results = await pg_store.hybrid_search(
        query="chunk content",
        query_embedding=[0.1, 0.1, 0.1, 0.1],
        top_k=2,
    )
    assert len(results) == 2
    assert results[0]["method"] == "hybrid"


@pytest.mark.asyncio
async def test_delete_document(pg_store: PgVectorStore):
    chunks = [_make_chunk("doc1", i) for i in range(2)] + [_make_chunk("doc2", 0)]
    await pg_store.add_chunks(chunks)

    deleted = await pg_store.delete_document("doc1")
    assert deleted == 2

    # doc2 chunks should remain
    results = await pg_store.search([0.1] * 4, top_k=10)
    assert len(results) == 1
    assert results[0]["chunk"].document_id == "doc2"


def test_stats(pg_store):
    """Stats returns store_type postgres."""
    # pg_store is a coroutine here since it's an async fixture, but stats() is sync
    # We can test the class directly
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://")
    sf = async_sessionmaker(engine)
    store = PgVectorStore(sf)
    s = store.stats()
    assert s["store_type"] == "postgres"


@pytest.mark.asyncio
async def test_search_with_document_filter(pg_store: PgVectorStore):
    chunks = [_make_chunk("doc1", 0), _make_chunk("doc2", 0)]
    await pg_store.add_chunks(chunks)

    results = await pg_store.search([0.1] * 4, top_k=10, document_id="doc1")
    assert len(results) == 1
    assert results[0]["chunk"].document_id == "doc1"
