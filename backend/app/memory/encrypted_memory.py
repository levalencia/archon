"""Encrypted conversation store with per-conversation key derivation.

Each conversation gets its own encryption key derived from a master key
using PBKDF2. Messages are encrypted with AES-GCM (Fernet) before storage.

This fixes the single-key vulnerability found in AIAMastery Day 2:
if one conversation key is compromised, other conversations remain safe.

See: https://github.com/levalencia/production-ai-agents/articles/day-01-anatomy-of-production-agent/
Concept: Layer 4 - Memory with per-conversation encryption
"""

from __future__ import annotations

import base64
import hashlib
import json

import structlog
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = structlog.get_logger()


class EncryptedMemoryStore:
    """Encrypted in-memory store with per-conversation key derivation.

    Each conversation gets its own Fernet key derived from the master key
    via PBKDF2-HMAC-SHA256. Messages are encrypted before storage.

    Satisfies the MemoryStore Protocol.
    """

    def __init__(self, master_key: bytes | str) -> None:
        if isinstance(master_key, str):
            master_key = master_key.encode()
        self._master_key = master_key
        self._conversations: dict[str, list[bytes]] = {}  # encrypted blobs
        self._key_cache: dict[str, Fernet] = {}

    def _derive_key(self, conversation_id: str) -> Fernet:
        """Derive a per-conversation Fernet key from master key + conversation ID."""
        if conversation_id in self._key_cache:
            return self._key_cache[conversation_id]

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=hashlib.sha256(conversation_id.encode()).digest(),
            iterations=100_000,
        )
        derived = base64.urlsafe_b64encode(kdf.derive(self._master_key))
        fernet = Fernet(derived)
        self._key_cache[conversation_id] = fernet
        return fernet

    async def store(self, conversation_id: str, role: str, content: str) -> None:
        """Encrypt and store a message."""
        fernet = self._derive_key(conversation_id)
        message = json.dumps({"role": role, "content": content})
        encrypted = fernet.encrypt(message.encode())

        self._conversations.setdefault(conversation_id, []).append(encrypted)
        logger.debug(
            "encrypted_memory_stored",
            conversation_id=conversation_id,
            role=role,
            content_length=len(content),
            encrypted_length=len(encrypted),
        )

    async def retrieve(self, conversation_id: str, limit: int = 50) -> list[dict[str, str]]:
        """Decrypt and retrieve recent messages."""
        encrypted_messages = self._conversations.get(conversation_id, [])
        fernet = self._derive_key(conversation_id)

        messages: list[dict[str, str]] = []
        for blob in encrypted_messages[-limit:]:
            decrypted = fernet.decrypt(blob)
            msg = json.loads(decrypted.decode())
            messages.append(msg)

        return messages

    async def list_conversations(self) -> list[str]:
        """List all conversation IDs."""
        return list(self._conversations.keys())

    async def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and its cached key."""
        deleted = conversation_id in self._conversations
        self._conversations.pop(conversation_id, None)
        self._key_cache.pop(conversation_id, None)
        return deleted

    async def get_message_count(self, conversation_id: str) -> int:
        """Count messages in a conversation."""
        return len(self._conversations.get(conversation_id, []))
