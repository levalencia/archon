"""Focused security tests for embedding trust boundaries and vector validation."""

from __future__ import annotations

import math
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.chunker import (
    EmbeddingService,
    validate_embedding,
    validate_embedding_endpoint,
)
from app.services.vector_store import MemoryVectorStore


@pytest.mark.parametrize("dimensions", [0, 4097])
def test_embedding_dimension_setting_is_bounded(dimensions: int) -> None:
    with pytest.raises(ValidationError):
        Settings(embedding_dimensions=dimensions)


@pytest.mark.parametrize(
    "vector",
    [[1.0, True], [1.0, math.nan], [1.0, math.inf], [1.0], "not-a-vector"],
)
def test_embedding_validation_is_strict(vector: object) -> None:
    with pytest.raises(ValueError):
        validate_embedding(vector, 2)


def test_endpoint_rejects_untrusted_url_components() -> None:
    for url in (
        "http://api.openai.com/v1",
        "https://user:pass@api.openai.com/v1",
        "https://api.openai.com/v1?key=secret",
        "https://api.openai.com/v1#fragment",
        "https://evil.example/v1",
    ):
        with pytest.raises(ValueError):
            validate_embedding_endpoint(url, allowed_hosts={"api.openai.com"}, allow_private=False)


def test_private_endpoint_requires_opt_in_even_when_allowlisted(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(ValueError, match="explicit opt-in"):
        validate_embedding_endpoint(
            "https://internal.example/v1",
            allowed_hosts={"internal.example"},
            allow_private=False,
        )
    assert (
        validate_embedding_endpoint(
            "https://internal.example/v1",
            allowed_hosts={"internal.example"},
            allow_private=True,
        )
        == "https://internal.example/v1"
    )


@pytest.mark.asyncio
async def test_provider_rejects_non_finite_vector_and_disables_redirects() -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": [{"index": 0, "embedding": [0.1, math.nan]}]}
    service = EmbeddingService(provider="openai", api_key="test-key", dimensions=2)
    with patch("httpx.AsyncClient") as client_class:
        client = AsyncMock()
        client.post.return_value = response
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client_class.return_value = client
        with pytest.raises(ValueError, match="non-finite"):
            await service.embed("hello")
    assert client_class.call_args.kwargs["follow_redirects"] is False


@pytest.mark.asyncio
async def test_memory_store_validates_query_persistence_and_skips_corruption(capsys) -> None:
    from app.services.chunker import DocumentChunk

    store = MemoryVectorStore(dimensions=2, candidate_limit=2)
    good = DocumentChunk("good", "doc", "good", 0, embedding=[1.0, 0.0])
    await store.add_chunks([good], owner_id="owner", project_id="project")
    with pytest.raises(ValueError):
        await store.add_chunks(
            [DocumentChunk("bad", "doc", "bad", 1, embedding=[True, 0.0])],
            owner_id="owner",
            project_id="project",
        )
    with pytest.raises(ValueError):
        await store.search([math.inf, 0.0], owner_id="owner", project_id="project")
    good.embedding = [1.0]
    assert await store.search([1.0, 0.0], owner_id="owner", project_id="project") == []
    assert "corrupt_vector_row_skipped" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_sql_store_bounds_candidates_and_skips_corrupt_rows() -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.services.chunker import DocumentChunk
    from app.services.db_store import Base, VectorChunkRow
    from app.services.sql_json_vector_store import SqlJsonVectorStore

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = SqlJsonVectorStore(sessions, dimensions=2, candidate_limit=2)
    chunks = [
        DocumentChunk("a", "doc", "first", 0, embedding=[1.0, 0.0]),
        DocumentChunk("b", "doc", "second", 1, embedding=[1.0, 0.0]),
    ]
    await store.add_chunks(chunks, owner_id="owner", project_id="project")
    async with sessions.begin() as session:
        await session.execute(
            update(VectorChunkRow)
            .where(VectorChunkRow.id == "a")
            .values(embedding_json="[NaN, 0.0]", metadata_json="not-json")
        )
    results = await store.search([1.0, 0.0], owner_id="owner", project_id="project", top_k=10)
    assert [result["chunk"].id for result in results] == ["b"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_candidate_bound_is_deterministic_and_scope_local() -> None:
    from app.services.chunker import DocumentChunk

    store = MemoryVectorStore(dimensions=2, candidate_limit=1)
    await store.add_chunks(
        [DocumentChunk("z", "doc", "other", 0, embedding=[1.0, 0.0])],
        owner_id="another-owner",
        project_id="project",
    )
    await store.add_chunks(
        [
            DocumentChunk("b", "doc", "second", 1, embedding=[1.0, 0.0]),
            DocumentChunk("a", "doc", "first", 0, embedding=[1.0, 0.0]),
        ],
        owner_id="owner",
        project_id="project",
    )
    results = await store.search([1.0, 0.0], owner_id="owner", project_id="project", top_k=10)
    assert [result["chunk"].id for result in results] == ["a"]
