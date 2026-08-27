"""Online encrypted-memory key rotation and resumability."""

from __future__ import annotations

import asyncio
import base64

import pytest
from sqlalchemy import select

from app.memory.keys import MemoryKeyring
from app.memory.scoped import (
    MemoryEncryptionError,
    MemoryKeyRetirementBlockedError,
    ScopedEncryptedMemoryRepository,
)
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore, MemoryFactRow
from app.services.key_rotation import MemoryKeyRotationService

KEY_V1 = base64.urlsafe_b64encode(b"1" * 32).decode().rstrip("=")
KEY_V2 = base64.urlsafe_b64encode(b"2" * 32).decode().rstrip("=")
RAW_V1 = b"1" * 32
RAW_V2 = b"2" * 32


@pytest.mark.unit
@pytest.mark.asyncio
async def test_active_writes_previous_reads_and_rotation_resumes_in_batches(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'rotation.db'}")
    await store.initialize()
    redactor = PersistenceRedactor()
    legacy = ScopedEncryptedMemoryRepository(store.session_factory, KEY_V1, redactor=redactor)
    for content in ("first secret", "second secret", "third secret"):
        await legacy.add("alice", "project", content, provenance={"source": "test"})

    rotating = ScopedEncryptedMemoryRepository(
        store.session_factory,
        MemoryKeyring(2, {1: RAW_V1, 2: RAW_V2}),
        redactor=redactor,
    )
    await rotating.validate_key_versions()
    assert [fact.content for fact in await rotating.list("alice", "project")] == [
        "first secret",
        "second secret",
        "third secret",
    ]
    new_fact = await rotating.add("alice", "project", "new active", provenance={})

    first = await rotating.rotate_batch("alice", "project", batch_size=1)
    assert first.rotated == 1 and first.remaining == 2 and not first.complete
    second = await rotating.rotate_batch("alice", "project", batch_size=1)
    assert second.rotated == 1 and second.remaining == 1
    final = await rotating.rotate_batch("alice", "project", batch_size=10)
    assert final.rotated == 1 and final.remaining == 0 and final.complete
    assert final.version_counts == {2: 4}

    async with store.session_factory() as session:
        rows = (await session.scalars(select(MemoryFactRow))).all()
        assert {row.key_version for row in rows} == {2}
        assert all(bytes(row.ciphertext)[0] == 2 for row in rows)
        assert next(row for row in rows if row.id == new_fact.id).key_version == 2
    assert b"secret" not in (tmp_path / "rotation.db").read_bytes()
    await rotating.assert_key_retirable(1)
    await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_interrupted_batch_rolls_back_and_retry_resumes(tmp_path, monkeypatch) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    await store.initialize()
    redactor = PersistenceRedactor()
    legacy = ScopedEncryptedMemoryRepository(store.session_factory, KEY_V1, redactor=redactor)
    for content in ("one", "two"):
        await legacy.add("alice", "project", content, provenance={})
    rotating = ScopedEncryptedMemoryRepository(
        store.session_factory,
        MemoryKeyring(2, {1: RAW_V1, 2: RAW_V2}),
        redactor=redactor,
    )
    original_encrypt = rotating._encrypt
    calls = 0

    def interrupted_encrypt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic interruption")
        return original_encrypt(**kwargs)

    monkeypatch.setattr(rotating, "_encrypt", interrupted_encrypt)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        await rotating.rotate_batch("alice", "project", batch_size=2)
    assert await rotating.key_version_counts("alice", "project") == {1: 2}

    monkeypatch.setattr(rotating, "_encrypt", original_encrypt)
    resumed = await rotating.rotate_batch("alice", "project", batch_size=2)
    assert resumed.complete and resumed.version_counts == {2: 2}
    assert [fact.content for fact in await rotating.list("alice", "project")] == ["one", "two"]
    await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retirement_and_missing_previous_key_fail_closed(tmp_path) -> None:
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'missing.db'}")
    await store.initialize()
    redactor = PersistenceRedactor()
    legacy = ScopedEncryptedMemoryRepository(store.session_factory, KEY_V1, redactor=redactor)
    await legacy.add("alice", "project", "secret", provenance={})

    active_only = ScopedEncryptedMemoryRepository(
        store.session_factory, MemoryKeyring(2, {2: RAW_V2}), redactor=redactor
    )
    with pytest.raises(MemoryEncryptionError, match="version is unavailable"):
        await active_only.validate_key_versions()
    with pytest.raises(MemoryEncryptionError):
        await active_only.list("alice", "project")

    full = ScopedEncryptedMemoryRepository(
        store.session_factory,
        MemoryKeyring(2, {1: RAW_V1, 2: RAW_V2}),
        redactor=redactor,
    )
    with pytest.raises(MemoryKeyRetirementBlockedError):
        await full.assert_key_retirable(1)
    with pytest.raises(MemoryKeyRetirementBlockedError):
        await full.assert_key_retirable(2)
    await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_rotation_workers_remain_idempotent(tmp_path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}"
    first_store, second_store = DatabaseStore(url), DatabaseStore(url)
    await first_store.initialize()
    await second_store.initialize()
    redactor = PersistenceRedactor()
    legacy = ScopedEncryptedMemoryRepository(first_store.session_factory, KEY_V1, redactor=redactor)
    for index in range(6):
        await legacy.add("alice", "project", f"fact-{index}", provenance={})
    keyring = MemoryKeyring(2, {1: RAW_V1, 2: RAW_V2})
    first = ScopedEncryptedMemoryRepository(first_store.session_factory, keyring, redactor=redactor)
    second = ScopedEncryptedMemoryRepository(
        second_store.session_factory, keyring, redactor=redactor
    )

    await asyncio.gather(
        first.rotate_batch("alice", "project", batch_size=3),
        second.rotate_batch("alice", "project", batch_size=3),
    )
    status = await MemoryKeyRotationService(first).status("alice", "project")
    assert status.complete
    assert status.version_counts == {2: 6}
    assert [fact.content for fact in await first.list("alice", "project")] == [
        f"fact-{index}" for index in range(6)
    ]
    await first_store.close()
    await second_store.close()
