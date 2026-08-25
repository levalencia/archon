"""Tests for embedding configuration and EmbeddingService providers."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.chunker import EmbeddingService
from app.services.vector_store import VectorStore


class TestSettingsEmbeddingDefaults:
    """Verify new embedding fields in Settings have correct defaults."""

    def test_embedding_provider_default(self) -> None:
        s = Settings()
        assert s.embedding_provider == "mock"

    def test_embedding_model_default(self) -> None:
        s = Settings()
        assert s.embedding_model == "text-embedding-3-small"

    def test_embedding_api_key_default(self) -> None:
        s = Settings()
        assert s.embedding_api_key == ""

    def test_embedding_dimensions_default(self) -> None:
        s = Settings()
        assert s.embedding_dimensions == 256


class TestEmbeddingServiceMock:
    """Ensure mock provider still works correctly."""

    @pytest.mark.asyncio
    async def test_mock_embed_returns_correct_dimensions(self) -> None:
        svc = EmbeddingService(provider="mock", dimensions=128)
        vec = await svc.embed("hello world")
        assert len(vec) == 128
        assert all(isinstance(v, float) for v in vec)

    @pytest.mark.asyncio
    async def test_mock_embed_deterministic(self) -> None:
        svc = EmbeddingService(provider="mock", dimensions=64)
        v1 = await svc.embed("test text")
        v2 = await svc.embed("test text")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_mock_embed_batch(self) -> None:
        svc = EmbeddingService(provider="mock", dimensions=32)
        results = await svc.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(len(v) == 32 for v in results)


class TestEmbeddingServiceOpenAI:
    """Test OpenAI provider error handling."""

    @pytest.mark.asyncio
    async def test_openai_no_api_key_raises(self) -> None:
        svc = EmbeddingService(provider="openai", api_key="")
        with pytest.raises(ValueError, match="requires an API key"):
            await svc.embed("test")

    @pytest.mark.asyncio
    async def test_openai_batch_no_api_key_raises(self) -> None:
        svc = EmbeddingService(provider="openai", api_key="")
        with pytest.raises(ValueError, match="requires an API key"):
            await svc.embed_batch(["a", "b"])

    @pytest.mark.asyncio
    async def test_openai_embed_calls_api(self) -> None:
        """Mock the httpx call to verify correct request structure."""
        from unittest.mock import AsyncMock, MagicMock, patch

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json.return_value = {
            "data": [{"embedding": [0.1, 0.2, 0.3]}],
        }

        svc = EmbeddingService(provider="openai", api_key="sk-test", dimensions=3)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = fake_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await svc.embed("hello")

        assert result == [0.1, 0.2, 0.3]
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "api.openai.com" in call_kwargs.args[0]
        assert call_kwargs.kwargs["json"]["model"] == "text-embedding-3-small"


class TestVectorStoreStats:
    """Test the new stats() method."""

    def test_stats_empty_store(self) -> None:
        store = VectorStore()
        s = store.stats()
        assert s == {"total_chunks": 0, "total_documents": 0, "store_type": "memory"}

    @pytest.mark.asyncio
    async def test_stats_after_add(self) -> None:
        from app.services.chunker import DocumentChunk

        store = VectorStore()
        chunk = DocumentChunk(
            id="c1",
            document_id="d1",
            content="test",
            chunk_index=0,
            embedding=[0.1] * 10,
        )
        await store.add_chunk(chunk)
        s = store.stats()
        assert s["total_chunks"] == 1
        assert s["total_documents"] == 1
        assert s["store_type"] == "memory"
