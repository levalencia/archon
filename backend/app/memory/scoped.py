"""Owner/project-scoped encrypted persistent memory backed by the application database."""

from __future__ import annotations

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
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.memory.keys import MemoryKeyring, decode_memory_master_key
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import MemoryFactRow, MemoryKeyStateRow, MemoryScopeRow

MAX_MEMORY_CHARS = 2000
_NONCE_BYTES = 12


class MemoryEncryptionError(RuntimeError):
    """Encrypted memory could not be authenticated or decoded."""


class MemoryLimitError(ValueError):
    """The scoped decrypted-memory character limit would be exceeded."""


class MemoryKeyGenerationMismatchError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("memory_key_generation_mismatch")


class MemoryKeyRetirementBlockedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("memory_key_retirement_blocked")


@dataclass(frozen=True, slots=True)
class MemoryRotationBatch:
    active_version: int
    rotated: int
    remaining: int
    version_counts: Mapping[int, int]

    @property
    def complete(self) -> bool:
        return self.remaining == 0


@dataclass(frozen=True, slots=True)
class MemoryContextBundle:
    text: str
    fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MemoryFact:
    id: str
    content: str
    provenance: Mapping[str, str]
    created_at: datetime
    updated_at: datetime


class ScopedEncryptedMemoryRepository:
    """Encrypt facts and serialize scoped mutations through a database aggregate row."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        master_key: str | bytes | MemoryKeyring,
        *,
        max_chars: int = MAX_MEMORY_CHARS,
        redactor: PersistenceRedactor,
    ) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._sessions = session_factory
        self._keyring = (
            master_key
            if isinstance(master_key, MemoryKeyring)
            else MemoryKeyring(1, {1: decode_memory_master_key(master_key)})
        )
        self._max_chars = max_chars
        self._redactor = redactor

    @property
    def active_key_version(self) -> int:
        return self._keyring.active_version

    def _key(self, user_id: str, project_id: str, version: int) -> bytes:
        info = b"archon/memory/v1\0" + user_id.encode() + b"\0" + project_id.encode()
        try:
            master_key = self._keyring.key(version)
        except ValueError:
            raise MemoryEncryptionError("memory ciphertext key version is unavailable") from None
        derived_key: bytes = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"archon-scoped-memory-hkdf-v1",
            info=info + b"\0" + str(version).encode(),
        ).derive(master_key)
        return derived_key

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
        version = self._keyring.active_version
        encrypted: bytes = AESGCM(self._key(user_id, project_id, version)).encrypt(
            nonce, payload, self._aad(user_id, project_id, fact_id, version)
        )
        return bytes([version]) + nonce + encrypted

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
            decoded: object = json.loads(cleartext)
            if not isinstance(decoded, dict):
                raise ValueError("invalid payload")
            content = decoded.get("content")
            raw_provenance = decoded.get("provenance")
            if not isinstance(content, str) or not isinstance(raw_provenance, dict):
                raise ValueError("invalid payload")
            provenance: dict[str, str] = {}
            for key, value in raw_provenance.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise ValueError("invalid payload")
                provenance[key] = value
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

    async def _facts(
        self, session: AsyncSession, user_id: str, project_id: str
    ) -> tuple[tuple[MemoryFactRow, MemoryFact], ...]:
        result = await session.execute(
            select(MemoryFactRow)
            .where(MemoryFactRow.user_id == user_id, MemoryFactRow.project_id == project_id)
            .order_by(MemoryFactRow.created_at, MemoryFactRow.id)
        )
        return tuple((row, self._decrypt(row)) for row in result.scalars().all())

    async def _version_counts(
        self,
        session: AsyncSession,
        *,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> Mapping[int, int]:
        query = select(MemoryFactRow.key_version, func.count(MemoryFactRow.id))
        if user_id is not None:
            query = query.where(MemoryFactRow.user_id == user_id)
        if project_id is not None:
            query = query.where(MemoryFactRow.project_id == project_id)
        rows = (await session.execute(query.group_by(MemoryFactRow.key_version))).all()
        return MappingProxyType({int(version): int(count) for version, count in rows})

    async def validate_key_versions(self) -> None:
        async with self._sessions() as session:
            counts = await self._version_counts(session)
        if any(version not in self._keyring.keys for version in counts):
            raise MemoryEncryptionError("memory ciphertext key version is unavailable")

    async def key_version_counts(self, user_id: str, project_id: str) -> Mapping[int, int]:
        async with self._sessions() as session:
            return await self._version_counts(session, user_id=user_id, project_id=project_id)

    async def activate_key_version(self) -> int:
        """Atomically publish this process' active generation after validating forward rotation."""
        async with self._sessions() as session, session.begin():
            await self._ensure_key_state(session)
            state = (
                await session.execute(
                    update(MemoryKeyStateRow)
                    .where(MemoryKeyStateRow.singleton_id == "global")
                    .values(generation=MemoryKeyStateRow.generation)
                    .returning(MemoryKeyStateRow)
                )
            ).scalar_one()
            configured = self._keyring.active_version
            if state.active_version == configured:
                return int(state.generation)
            if configured < state.active_version or state.active_version not in self._keyring.keys:
                raise MemoryKeyGenerationMismatchError
            state.active_version = configured
            state.generation += 1
            state.updated_at = datetime.now(tz=UTC)
            await session.flush()
            return int(state.generation)

    async def _ensure_key_state(self, session: AsyncSession) -> None:
        values = {
            "singleton_id": "global",
            "active_version": self._keyring.active_version,
            "generation": 1,
            "updated_at": datetime.now(tz=UTC),
        }
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            await session.execute(
                sqlite_insert(MemoryKeyStateRow).values(**values).on_conflict_do_nothing()
            )
        elif dialect == "postgresql":
            await session.execute(
                postgresql_insert(MemoryKeyStateRow).values(**values).on_conflict_do_nothing()
            )
        else:
            try:
                async with session.begin_nested():
                    session.add(MemoryKeyStateRow(**values))
                    await session.flush()
            except IntegrityError:
                pass

    async def _lock_key_state(self, session: AsyncSession) -> MemoryKeyStateRow:
        await self._ensure_key_state(session)
        state = (
            await session.execute(
                update(MemoryKeyStateRow)
                .where(
                    MemoryKeyStateRow.singleton_id == "global",
                    MemoryKeyStateRow.active_version == self._keyring.active_version,
                )
                .values(generation=MemoryKeyStateRow.generation)
                .returning(MemoryKeyStateRow)
            )
        ).scalar_one_or_none()
        if state is None:
            raise MemoryKeyGenerationMismatchError
        return state

    async def _lock_scope(
        self, session: AsyncSession, user_id: str, project_id: str
    ) -> MemoryScopeRow:
        """Lock global key generation, then one owner/project scope for the transaction."""
        await self._lock_key_state(session)
        values = {"user_id": user_id, "project_id": project_id, "chars_used": 0, "version": 0}
        bind = session.get_bind()
        dialect = bind.dialect.name
        if dialect == "sqlite":
            await session.execute(
                sqlite_insert(MemoryScopeRow).values(**values).on_conflict_do_nothing()
            )
        elif dialect == "postgresql":
            await session.execute(
                postgresql_insert(MemoryScopeRow).values(**values).on_conflict_do_nothing()
            )
        else:
            try:
                async with session.begin_nested():
                    session.add(MemoryScopeRow(**values))
                    await session.flush()
            except IntegrityError:
                pass

        # UPDATE is the portable serialization primitive: SQLite takes its database write
        # lock and PostgreSQL takes a row lock. It remains held until this transaction ends.
        result = await session.execute(
            update(MemoryScopeRow)
            .where(
                MemoryScopeRow.user_id == user_id,
                MemoryScopeRow.project_id == project_id,
            )
            .values(version=MemoryScopeRow.version + 1)
            .returning(MemoryScopeRow)
        )
        return result.scalar_one()

    async def list(self, user_id: str, project_id: str) -> tuple[MemoryFact, ...]:
        async with self._sessions() as session:
            return tuple(fact for _, fact in await self._facts(session, user_id, project_id))

    async def rotate_batch(
        self, user_id: str, project_id: str, *, batch_size: int = 100
    ) -> MemoryRotationBatch:
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("memory rotation batch_size must be between 1 and 1000")
        active = self._keyring.active_version
        async with self._sessions() as session, session.begin():
            await self._lock_scope(session, user_id, project_id)
            rows = (
                await session.scalars(
                    select(MemoryFactRow)
                    .where(
                        MemoryFactRow.user_id == user_id,
                        MemoryFactRow.project_id == project_id,
                        MemoryFactRow.key_version != active,
                    )
                    .order_by(MemoryFactRow.created_at, MemoryFactRow.id)
                    .limit(batch_size)
                )
            ).all()
            for row in rows:
                fact = self._decrypt(row)
                row.ciphertext = self._encrypt(
                    fact_id=row.id,
                    user_id=row.user_id,
                    project_id=row.project_id,
                    content=fact.content,
                    provenance=fact.provenance,
                )
                row.key_version = active
            await session.flush()
            counts = await self._version_counts(session, user_id=user_id, project_id=project_id)
            remaining = sum(count for version, count in counts.items() if version != active)
            return MemoryRotationBatch(
                active_version=active,
                rotated=len(rows),
                remaining=remaining,
                version_counts=counts,
            )

    async def assert_key_retirable(self, version: int) -> None:
        if type(version) is not int or not 1 <= version <= 255:
            raise ValueError("memory key version must be between 1 and 255")
        if version == self._keyring.active_version:
            raise MemoryKeyRetirementBlockedError
        async with self._sessions() as session, session.begin():
            await self._lock_key_state(session)
            referenced = await session.scalar(
                select(func.count(MemoryFactRow.id)).where(MemoryFactRow.key_version == version)
            )
        if int(referenced or 0) > 0:
            raise MemoryKeyRetirementBlockedError

    async def add(
        self,
        user_id: str,
        project_id: str,
        content: str,
        *,
        provenance: Mapping[str, str],
    ) -> MemoryFact:
        content = self._redactor.redact_text(content).text.strip()
        provenance = cast(dict[str, str], self._redactor.redact_value(provenance))
        if not content:
            raise ValueError("memory content is required")
        async with self._sessions() as session, session.begin():
            scope = await self._lock_scope(session, user_id, project_id)
            facts = await self._facts(session, user_id, project_id)
            total = sum(len(fact.content) for _, fact in facts) + len(content)
            if total > self._max_chars:
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
                key_version=self._keyring.active_version,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            scope.chars_used = total
            await session.flush()
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
        old_text = self._redactor.redact_text(old_text).text
        content = self._redactor.redact_text(content).text.strip()
        provenance = cast(dict[str, str], self._redactor.redact_value(provenance))
        if not old_text or not content:
            raise ValueError("old_text and content are required")
        async with self._sessions() as session, session.begin():
            scope = await self._lock_scope(session, user_id, project_id)
            facts = await self._facts(session, user_id, project_id)
            target = next(
                (
                    (row, fact)
                    for row, fact in facts
                    if old_text.casefold() in fact.content.casefold()
                ),
                None,
            )
            if target is None:
                scope.chars_used = sum(len(fact.content) for _, fact in facts)
                return None
            row, fact = target
            total = sum(len(item.content) for _, item in facts) - len(fact.content) + len(content)
            if total > self._max_chars:
                raise MemoryLimitError("scoped memory character limit exceeded")
            row.ciphertext = self._encrypt(
                fact_id=row.id,
                user_id=user_id,
                project_id=project_id,
                content=content,
                provenance=provenance,
            )
            row.key_version = self._keyring.active_version
            row.updated_at = datetime.now(tz=UTC)
            scope.chars_used = total
            await session.flush()
            return self._decrypt(row)

    async def remove(self, user_id: str, project_id: str, substring: str) -> int:
        substring = self._redactor.redact_text(substring).text
        if not substring:
            return 0
        async with self._sessions() as session, session.begin():
            scope = await self._lock_scope(session, user_id, project_id)
            facts = await self._facts(session, user_id, project_id)
            removed = [
                (row, fact)
                for row, fact in facts
                if substring.casefold() in fact.content.casefold()
            ]
            if removed:
                result = await session.execute(
                    delete(MemoryFactRow).where(
                        MemoryFactRow.id.in_([row.id for row, _ in removed]),
                        MemoryFactRow.user_id == user_id,
                        MemoryFactRow.project_id == project_id,
                    )
                )
                count = int(cast(CursorResult[Any], result).rowcount or 0)
            else:
                count = 0
            scope.chars_used = sum(
                len(fact.content)
                for row, fact in facts
                if all(row.id != item.id for item, _ in removed)
            )
            return count

    async def delete_all(self, user_id: str, project_id: str) -> int:
        async with self._sessions() as session, session.begin():
            scope = await self._lock_scope(session, user_id, project_id)
            await self._facts(session, user_id, project_id)
            result = await session.execute(
                delete(MemoryFactRow).where(
                    MemoryFactRow.user_id == user_id, MemoryFactRow.project_id == project_id
                )
            )
            scope.chars_used = 0
            return int(cast(CursorResult[Any], result).rowcount or 0)

    async def export(self, user_id: str, project_id: str) -> tuple[MemoryFact, ...]:
        return await self.list(user_id, project_id)

    async def context_bundle(self, user_id: str, project_id: str) -> MemoryContextBundle:
        facts = await self.list(user_id, project_id)
        return MemoryContextBundle(
            text="\n".join(f"- {fact.content}" for fact in facts),
            fact_ids=tuple(fact.id for fact in facts),
        )

    async def context_text(self, user_id: str, project_id: str) -> str:
        return (await self.context_bundle(user_id, project_id)).text
