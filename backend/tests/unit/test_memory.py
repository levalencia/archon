"""Tests for conversation memory stores (encrypted)."""

from __future__ import annotations

import base64

import pytest

from app.agents.protocols import MemoryStore
from app.memory.encrypted_memory import EncryptedMemoryStore


class TestEncryptedMemoryStore:
    """Encrypted memory store tests."""

    @pytest.fixture
    def store(self) -> EncryptedMemoryStore:
        key = base64.urlsafe_b64encode(b"4" * 32).decode().rstrip("=")
        return EncryptedMemoryStore(master_key=key)

    @pytest.mark.unit
    def test_satisfies_protocol(self, store: EncryptedMemoryStore) -> None:
        assert isinstance(store, MemoryStore)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, store: EncryptedMemoryStore) -> None:
        await store.store("conv-1", "user", "Secret message")
        await store.store("conv-1", "assistant", "Secret reply")

        messages = await store.retrieve("conv-1")
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Secret message"}
        assert messages[1] == {"role": "assistant", "content": "Secret reply"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_data_is_actually_encrypted(self, store: EncryptedMemoryStore) -> None:
        """Raw stored data should not contain plaintext."""
        await store.store("conv-1", "user", "My secret password is 12345")

        raw = store._conversations["conv-1"][0]
        assert isinstance(raw, bytes)
        assert b"My secret password" not in raw
        assert b"12345" not in raw

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_per_conversation_keys(self, store: EncryptedMemoryStore) -> None:
        """Different conversations use different encryption keys."""
        key1 = store._derive_key("conv-1")
        key2 = store._derive_key("conv-2")
        # Fernet objects with different keys
        assert key1._signing_key != key2._signing_key

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_wrong_key_cannot_decrypt(self) -> None:
        """Messages encrypted with one key cannot be decrypted with another."""
        store1 = EncryptedMemoryStore(
            master_key=base64.urlsafe_b64encode(b"5" * 32).decode().rstrip("=")
        )
        store2 = EncryptedMemoryStore(
            master_key=base64.urlsafe_b64encode(b"6" * 32).decode().rstrip("=")
        )

        await store1.store("conv-1", "user", "Secret")

        # Copy encrypted data to store2
        store2._conversations["conv-1"] = store1._conversations["conv-1"]

        # Should fail to decrypt
        from cryptography.fernet import InvalidToken

        with pytest.raises(InvalidToken):
            await store2.retrieve("conv-1")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_conversation_isolation(self, store: EncryptedMemoryStore) -> None:
        await store.store("conv-1", "user", "For conv 1")
        await store.store("conv-2", "user", "For conv 2")

        msg1 = await store.retrieve("conv-1")
        msg2 = await store.retrieve("conv-2")
        assert msg1[0]["content"] == "For conv 1"
        assert msg2[0]["content"] == "For conv 2"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_clears_key_cache(self, store: EncryptedMemoryStore) -> None:
        await store.store("conv-1", "user", "data")
        assert "conv-1" in store._key_cache
        await store.delete_conversation("conv-1")
        assert "conv-1" not in store._key_cache
