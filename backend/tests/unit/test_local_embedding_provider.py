"""Tests for the local fastembed-based embedding provider.

TDD: these tests were written before the implementation.
Model downloads are monkeypatched to avoid network I/O in unit tests.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.config import Settings
from app.services.chunker import EmbeddingService

# ---------------------------------------------------------------------------
# Helpers: fake fastembed model
# ---------------------------------------------------------------------------

DIMENSIONS = 384  # BAAI/bge-small-en-v1.5


def _fake_embed(texts: list[str], batch_size: int = 256, **kwargs) -> list[np.ndarray]:
    """Return deterministic 384-d unit vectors without downloading a real model."""
    import hashlib

    result = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode()).hexdigest(), 16) % (2**32)
        rng = np.random.RandomState(seed)
        vec = rng.randn(DIMENSIONS).astype(np.float32)
        vec /= np.linalg.norm(vec) + 1e-9
        result.append(vec)
    return result


@pytest.fixture()
def _patch_fastembed(monkeypatch):
    """Monkeypatch fastembed so no model is downloaded."""
    fake_model = MagicMock()
    fake_model.embed.side_effect = _fake_embed

    fake_module = MagicMock()
    fake_class = MagicMock(return_value=fake_model)
    fake_module.TextEmbedding = fake_class

    import sys

    monkeypatch.setitem(sys.modules, "fastembed", fake_module)
    return fake_class, fake_model


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestLocalProviderConstruction:
    """EmbeddingService(provider='local') should construct without errors."""

    def test_local_provider_accepted(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        assert svc.provider == "local"

    def test_local_no_api_key_required(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS, api_key="")
        svc.validate_configuration()  # should not raise

    def test_local_rejects_wrong_dimensions(self, _patch_fastembed) -> None:
        """Local provider with BAAI/bge-small-en-v1.5 must use 384 dimensions."""
        svc = EmbeddingService(provider="local", dimensions=128)
        with pytest.raises(ValueError, match="384"):
            asyncio.get_event_loop().run_until_complete(svc.embed("hello"))

    def test_local_capability(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        cap = svc.capability
        assert cap.provider == "local"
        assert cap.dimensions == DIMENSIONS
        assert cap.mock is False
        assert cap.readiness == "ready"


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class TestLocalProviderEmbed:
    """embed() and embed_batch() produce valid vectors."""

    @pytest.mark.asyncio
    async def test_embed_returns_correct_dimensions(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        vec = await svc.embed("hello world")
        assert len(vec) == DIMENSIONS
        assert all(isinstance(v, float) for v in vec)

    @pytest.mark.asyncio
    async def test_embed_deterministic(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        v1 = await svc.embed("test text")
        v2 = await svc.embed("test text")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_embed_batch(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        results = await svc.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(len(v) == DIMENSIONS for v in results)

    @pytest.mark.asyncio
    async def test_embed_returns_finite_values(self, _patch_fastembed) -> None:
        import math

        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        vec = await svc.embed("some text")
        assert all(math.isfinite(v) for v in vec)

    @pytest.mark.asyncio
    async def test_embed_returns_plain_floats(self, _patch_fastembed) -> None:
        """Output must be plain Python floats, not numpy types."""
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        vec = await svc.embed("hello")
        for v in vec:
            assert type(v) is float  # noqa: E721 — strict type check

    @pytest.mark.asyncio
    async def test_embed_batch_order_preserved(self, _patch_fastembed) -> None:
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        texts = ["alpha", "beta", "gamma"]
        batch_result = await svc.embed_batch(texts)
        individual = [await svc.embed(t) for t in texts]
        assert batch_result == individual


# ---------------------------------------------------------------------------
# Lazy initialization
# ---------------------------------------------------------------------------


class TestLocalProviderLazyInit:
    """Model loading is deferred until first embed call."""

    def test_model_not_loaded_on_construction(self, _patch_fastembed) -> None:
        fake_class, _ = _patch_fastembed
        EmbeddingService(provider="local", dimensions=DIMENSIONS)
        fake_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_model_loaded_on_first_embed(self, _patch_fastembed) -> None:
        fake_class, _ = _patch_fastembed
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        await svc.embed("trigger load")
        fake_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_model_loaded_once_across_calls(self, _patch_fastembed) -> None:
        fake_class, _ = _patch_fastembed
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        await svc.embed("first")
        await svc.embed("second")
        fake_class.assert_called_once()


# ---------------------------------------------------------------------------
# Cache path configuration
# ---------------------------------------------------------------------------


class TestLocalProviderCachePath:
    """Explicit cache_path is forwarded to fastembed."""

    @pytest.mark.asyncio
    async def test_cache_path_forwarded(self, _patch_fastembed) -> None:
        fake_class, _ = _patch_fastembed
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS, cache_path="/opt/models")
        await svc.embed("trigger")
        call_kwargs = fake_class.call_args
        assert call_kwargs.kwargs.get("cache_dir") == "/opt/models"

    @pytest.mark.asyncio
    async def test_no_cache_path_uses_default(self, _patch_fastembed) -> None:
        fake_class, _ = _patch_fastembed
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        await svc.embed("trigger")
        assert "cache_dir" not in fake_class.call_args.kwargs or (
            fake_class.call_args.kwargs.get("cache_dir") is None
        )


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestSettingsLocalProvider:
    """Settings accepts local provider."""

    def test_embedding_provider_local(self) -> None:
        s = Settings(embedding_provider="local", embedding_dimensions=384)
        assert s.embedding_provider == "local"

    def test_embedding_cache_path_default(self) -> None:
        s = Settings()
        assert s.embedding_cache_path == ""

    def test_embedding_cache_path_set(self) -> None:
        s = Settings(embedding_cache_path="/opt/models")
        assert s.embedding_cache_path == "/opt/models"


# ---------------------------------------------------------------------------
# Thread safety: encoding runs off event loop
# ---------------------------------------------------------------------------


class TestLocalProviderThreadSafety:
    """Encoding happens in a thread pool, not blocking the event loop."""

    @pytest.mark.asyncio
    async def test_embed_uses_thread_executor(self, _patch_fastembed) -> None:
        """Verify that the blocking fastembed call runs via asyncio.to_thread."""
        svc = EmbeddingService(provider="local", dimensions=DIMENSIONS)
        with patch("asyncio.to_thread", wraps=asyncio.to_thread) as mock_to_thread:
            await svc.embed("hello")
            assert mock_to_thread.called
