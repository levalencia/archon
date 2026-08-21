"""Tests for conversation memory stores (in-memory and encrypted)."""

from __future__ import annotations

import pytest

from app.agents.protocols import MemoryStore
from app.memory.encrypted_memory import EncryptedMemoryStore
from app.memory.in_memory import InMemoryStore


class TestInMemoryStore:
    """In-memory store tests."""

    @pytest.mark.unit
    def test_satisfies_protocol(self) -> None:
        store = InMemoryStore()
        assert isinstance(store, MemoryStore)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_store_and_retrieve(self) -> None:
        store = InMemoryStore()
        await store.store("conv-1", "user", "Hello")
        await store.store("conv-1", "assistant", "Hi there!")

        messages = await store.retrieve("conv-1")
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Hello"}
        assert messages[1] == {"role": "assistant", "content": "Hi there!"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_conversation_isolation(self) -> None:
        store = InMemoryStore()
        await store.store("conv-1", "user", "Message for conv 1")
        await store.store("conv-2", "user", "Message for conv 2")

        msg1 = await store.retrieve("conv-1")
        msg2 = await store.retrieve("conv-2")
        assert len(msg1) == 1
        assert len(msg2) == 1
        assert msg1[0]["content"] == "Message for conv 1"
        assert msg2[0]["content"] == "Message for conv 2"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retrieve_with_limit(self) -> None:
        store = InMemoryStore()
        for i in range(10):
            await store.store("conv-1", "user", f"Message {i}")

        messages = await store.retrieve("conv-1", limit=3)
        assert len(messages) == 3
        assert messages[0]["content"] == "Message 7"  # Last 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_retrieve_empty_conversation(self) -> None:
        store = InMemoryStore()
        messages = await store.retrieve("nonexistent")
        assert messages == []

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_list_conversations(self) -> None:
        store = InMemoryStore()
        await store.store("conv-1", "user", "a")
        await store.store("conv-2", "user", "b")

        convs = await store.list_conversations()
        assert set(convs) == {"conv-1", "conv-2"}

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_delete_conversation(self) -> None:
        store = InMemoryStore()
        await store.store("conv-1", "user", "a")
        assert await store.delete_conversation("conv-1") is True
        assert await store.retrieve("conv-1") == []
        assert await store.delete_conversation("conv-1") is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_message_count(self) -> None:
        store = InMemoryStore()
        assert await store.get_message_count("conv-1") == 0
        await store.store("conv-1", "user", "a")
        await store.store("conv-1", "assistant", "b")
        assert await store.get_message_count("conv-1") == 2


class TestEncryptedMemoryStore:
    """Encrypted memory store tests."""

    @pytest.fixture
    def store(self) -> EncryptedMemoryStore:
        return EncryptedMemoryStore(master_key="test-master-key-for-testing")

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
        store1 = EncryptedMemoryStore(master_key="key-one")
        store2 = EncryptedMemoryStore(master_key="key-two")

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
