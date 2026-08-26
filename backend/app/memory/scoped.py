"""Owner/project-scoped encrypted persistent memory backed by the application database."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.db_store import MemoryFactRow

MAX_MEMORY_CHARS = 2000
_KEY_VERSION = 1
_NONCE_BYTES = 12


class MemoryEncryptionError(RuntimeError):
    """Encrypted memory could not be authenticated or decoded."""


class MemoryLimitError(ValueError):
    """The scoped decrypted-memory character limit would be exceeded."""


@dataclass(frozen=True, slots=True)
class MemoryFact:
    id: str
    content: str
    provenance: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


class ScopedEncryptedMemoryRepository:
    """Encrypt fact content and provenance with keys derived for one owner/project scope."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        master_key: str,
        *,
        max_chars: int = MAX_MEMORY_CHARS,
    ) -> None:
        if not master_key:
            raise ValueError("memory encryption master key is required")
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._sessions = session_factory
        self._master_key = master_key.encode("utf-8")
        self._max_chars = max_chars
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _scope_lock(self, user_id: str, project_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault((user_id, project_id), asyncio.Lock())

    def _key(self, user_id: str, project_id: str, version: int) -> bytes:
        info = b"archon/memory/v1\0" + user_id.encode() + b"\0" + project_id.encode()
        return cast(
            bytes,
            HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"archon-scoped-memory-hkdf-v1",
                info=info + b"\0" + str(version).encode(),
            ).derive(self._master_key),
        )

    @staticmethod
    def _aad(user_id: str, project_id: str, fact_id: str, version: int) -> bytes:
        return b"\0".join(
            (
                b"archon-memory-fact",
                user_id.encode(),
                project_id.encode(),
                fact_id.encode(),
                str(version).encode(),
            )
        )

    def _encrypt(
        self,
        *,
        fact_id: str,
        user_id: str,
        project_id: str,
        content: str,
        provenance: Mapping[str, str],
    ) -> bytes:
        payload = json.dumps(
            {"content": content, "provenance": dict(provenance)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        encrypted = cast(
            bytes,
            AESGCM(self._key(user_id, project_id, _KEY_VERSION)).encrypt(
                nonce, payload, self._aad(user_id, project_id, fact_id, _KEY_VERSION)
            ),
        )
        return bytes([_KEY_VERSION]) + nonce + encrypted

    def _decrypt(self, row: MemoryFactRow) -> MemoryFact:
        envelope = bytes(row.ciphertext)
        if len(envelope) <= 1 + _NONCE_BYTES or envelope[0] != row.key_version:
            raise MemoryEncryptionError("memory ciphertext authentication failed")
        nonce = envelope[1 : 1 + _NONCE_BYTES]
        ciphertext = envelope[1 + _NONCE_BYTES :]
        try:
            cleartext = AESGCM(self._key(row.user_id, row.project_id, row.key_version)).decrypt(
                nonce,
                ciphertext,
                self._aad(row.user_id, row.project_id, row.id, row.key_version),
            )
            payload: Any = json.loads(cleartext)
            content = payload["content"]
            provenance = payload["provenance"]
            if (
                not isinstance(content, str)
                or not isinstance(provenance, dict)
                or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in provenance.items()
                )
            ):
                raise ValueError("invalid payload")
        except (
            InvalidTag,
            UnicodeDecodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise MemoryEncryptionError("memory ciphertext authentication failed") from exc
        return MemoryFact(
            id=row.id,
            content=content,
            provenance=MappingProxyType(dict(provenance)),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list(self, user_id: str, project_id: str) -> tuple[MemoryFact, ...]:
        async with self._sessions() as session:
            result = await session.execute(
                select(MemoryFactRow)
                .where(MemoryFactRow.user_id == user_id, MemoryFactRow.project_id == project_id)
                .order_by(MemoryFactRow.created_at, MemoryFactRow.id)
            )
            return tuple(self._decrypt(row) for row in result.scalars().all())

    async def add(
        self,
        user_id: str,
        project_id: str,
        content: str,
        *,
        provenance: Mapping[str, str],
    ) -> MemoryFact:
        content = content.strip()
        if not content:
            raise ValueError("memory content is required")
        lock = await self._scope_lock(user_id, project_id)
        async with lock:
            current = await self.list(user_id, project_id)
            if sum(len(item.content) for item in current) + len(content) > self._max_chars:
                raise MemoryLimitError("scoped memory character limit exceeded")
            now = datetime.now(tz=UTC)
            fact_id = str(uuid.uuid4())
            row = MemoryFactRow(
                id=fact_id,
                user_id=user_id,
                project_id=project_id,
                ciphertext=self._encrypt(
                    fact_id=fact_id,
                    user_id=user_id,
                    project_id=project_id,
                    content=content,
                    provenance=provenance,
                ),
                key_version=_KEY_VERSION,
                created_at=now,
                updated_at=now,
            )
            async with self._sessions() as session:
                session.add(row)
                await session.commit()
            return self._decrypt(row)

    async def replace(
        self,
        user_id: str,
        project_id: str,
        old_text: str,
        content: str,
        *,
        provenance: Mapping[str, str],
    ) -> MemoryFact | None:
        if not old_text or not content.strip():
            raise ValueError("old_text and content are required")
        lock = await self._scope_lock(user_id, project_id)
        async with lock:
            facts = await self.list(user_id, project_id)
            target = next(
                (fact for fact in facts if old_text.casefold() in fact.content.casefold()), None
            )
            if target is None:
                return None
            total = (
                sum(len(item.content) for item in facts)
                - len(target.content)
                + len(content.strip())
            )
            if total > self._max_chars:
                raise MemoryLimitError("scoped memory character limit exceeded")
            now = datetime.now(tz=UTC)
            async with self._sessions() as session:
                row = await session.get(MemoryFactRow, target.id)
                if row is None or row.user_id != user_id or row.project_id != project_id:
                    return None
                row.ciphertext = self._encrypt(
                    fact_id=row.id,
                    user_id=user_id,
                    project_id=project_id,
                    content=content.strip(),
                    provenance=provenance,
                )
                row.updated_at = now
                await session.commit()
                return self._decrypt(row)

    async def remove(self, user_id: str, project_id: str, substring: str) -> int:
        if not substring:
            return 0
        lock = await self._scope_lock(user_id, project_id)
        async with lock:
            facts = await self.list(user_id, project_id)
            ids = [fact.id for fact in facts if substring.casefold() in fact.content.casefold()]
            if not ids:
                return 0
            async with self._sessions() as session:
                result = await session.execute(
                    delete(MemoryFactRow).where(
                        MemoryFactRow.id.in_(ids),
                        MemoryFactRow.user_id == user_id,
                        MemoryFactRow.project_id == project_id,
                    )
                )
                await session.commit()
                return int(result.rowcount or 0)

    async def delete_all(self, user_id: str, project_id: str) -> int:
        async with self._sessions() as session:
            result = await session.execute(
                delete(MemoryFactRow).where(
                    MemoryFactRow.user_id == user_id, MemoryFactRow.project_id == project_id
                )
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def export(self, user_id: str, project_id: str) -> tuple[MemoryFact, ...]:
        return await self.list(user_id, project_id)

    async def context_text(self, user_id: str, project_id: str) -> str:
        facts = await self.list(user_id, project_id)
        return "\n".join(f"- {fact.content}" for fact in facts)
