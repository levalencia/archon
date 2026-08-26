from __future__ import annotations

import asyncio
import base64
import json

import pytest
from sqlalchemy import select, update

from app.memory.scoped import (
    MemoryEncryptionError,
    MemoryLimitError,
    ScopedEncryptedMemoryRepository,
)
from app.runtime.factory import RunContext
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository
from app.services.db_store import DatabaseStore, MemoryFactRow, MemoryScopeRow
from app.tools.memory_tools import create_memory_tool, create_session_search_tool

MASTER_KEY = base64.urlsafe_b64encode(b"2" * 32).decode().rstrip("=")
WRONG_KEY = base64.urlsafe_b64encode(b"3" * 32).decode().rstrip("=")


@pytest.fixture
async def encrypted_memory(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"
    store = DatabaseStore(url)
    await store.initialize()
    repository = ScopedEncryptedMemoryRepository(
        store.session_factory, MASTER_KEY, redactor=PersistenceRedactor()
    )
    yield store, repository, tmp_path / "memory.db"
    await store.close()


async def test_two_users_and_projects_are_isolated_and_raw_db_has_no_plaintext(encrypted_memory):
    store, repository, db_path = encrypted_memory
    provenance = {
        "source_conversation_id": "conversation-secret",
        "source_run_id": "run-secret",
        "source_action": "add",
    }
    await repository.add("alice", "red", "alice-red-secret", provenance=provenance)
    await repository.add("alice", "blue", "alice-blue-secret", provenance=provenance)
    await repository.add("bob", "red", "bob-red-secret", provenance=provenance)

    assert [fact.content for fact in await repository.list("alice", "red")] == ["alice-red-secret"]
    assert [fact.content for fact in await repository.list("alice", "blue")] == [
        "alice-blue-secret"
    ]
    assert [fact.content for fact in await repository.list("bob", "red")] == ["bob-red-secret"]
    raw = db_path.read_bytes()
    for plaintext in (
        b"alice-red-secret",
        b"alice-blue-secret",
        b"bob-red-secret",
        b"conversation-secret",
        b"run-secret",
    ):
        assert plaintext not in raw


async def test_restart_decrypts_and_wrong_key_and_tampering_fail_closed(encrypted_memory):
    store, repository, _ = encrypted_memory
    fact = await repository.add("alice", "red", "durable", provenance={"source_action": "add"})
    restarted = ScopedEncryptedMemoryRepository(
        store.session_factory, MASTER_KEY, redactor=PersistenceRedactor()
    )
    assert (await restarted.list("alice", "red"))[0].content == "durable"

    wrong_key = ScopedEncryptedMemoryRepository(
        store.session_factory, WRONG_KEY, redactor=PersistenceRedactor()
    )
    with pytest.raises(MemoryEncryptionError):
        await wrong_key.list("alice", "red")

    async with store.session_factory() as session:
        row = await session.get(MemoryFactRow, fact.id)
        assert row is not None
        damaged = bytearray(row.ciphertext)
        damaged[-1] ^= 1
        await session.execute(
            update(MemoryFactRow)
            .where(MemoryFactRow.id == fact.id)
            .values(ciphertext=bytes(damaged))
        )
        await session.commit()
    with pytest.raises(MemoryEncryptionError):
        await repository.list("alice", "red")


async def test_ciphertext_cannot_be_swapped_between_rows(encrypted_memory):
    store, repository, _ = encrypted_memory
    first = await repository.add("alice", "red", "first", provenance={"source_action": "add"})
    second = await repository.add("alice", "red", "second", provenance={"source_action": "add"})
    async with store.session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(MemoryFactRow).where(MemoryFactRow.id.in_([first.id, second.id]))
                )
            )
            .scalars()
            .all()
        )
        rows[0].ciphertext, rows[1].ciphertext = rows[1].ciphertext, rows[0].ciphertext
        await session.commit()
    with pytest.raises(MemoryEncryptionError):
        await repository.list("alice", "red")


async def test_export_replace_remove_delete_and_limit(encrypted_memory):
    _, repository, _ = encrypted_memory
    added = await repository.add(
        "alice", "red", "old preference", provenance={"source_action": "add"}
    )
    assert added.provenance["source_action"] == "add"
    replaced = await repository.replace(
        "alice", "red", "old", "new preference", provenance={"source_action": "replace"}
    )
    assert replaced is not None and replaced.content == "new preference"
    assert (await repository.export("alice", "red"))[0].content == "new preference"
    assert await repository.remove("alice", "red", "new") == 1
    await repository.add("alice", "red", "x", provenance={"source_action": "add"})
    assert await repository.delete_all("alice", "red") == 1
    limited = ScopedEncryptedMemoryRepository(
        repository._sessions, MASTER_KEY, max_chars=3, redactor=PersistenceRedactor()
    )
    with pytest.raises(MemoryLimitError):
        await limited.add("alice", "blue", "four", provenance={"source_action": "add"})


async def test_independent_engines_serialize_concurrent_adds_at_limit(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}"
    first_store, second_store = DatabaseStore(url), DatabaseStore(url)
    await first_store.initialize()
    await second_store.initialize()
    first = ScopedEncryptedMemoryRepository(
        first_store.session_factory, MASTER_KEY, max_chars=5, redactor=PersistenceRedactor()
    )
    second = ScopedEncryptedMemoryRepository(
        second_store.session_factory, MASTER_KEY, max_chars=5, redactor=PersistenceRedactor()
    )

    results = await asyncio.gather(
        first.add("alice", "red", "aaa", provenance={}),
        second.add("alice", "red", "bbb", provenance={}),
        return_exceptions=True,
    )
    assert sum(isinstance(result, MemoryLimitError) for result in results) == 1
    facts = await first.list("alice", "red")
    assert sum(len(fact.content) for fact in facts) == 3
    async with first_store.session_factory() as session:
        scope = await session.get(MemoryScopeRow, ("alice", "red"))
        assert scope is not None and scope.chars_used == 3 and scope.version == 1
    await first_store.close()
    await second_store.close()


async def test_concurrent_replace_delete_add_preserves_aggregate_and_restart(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'mutations.db'}"
    first_store, second_store = DatabaseStore(url), DatabaseStore(url)
    await first_store.initialize()
    await second_store.initialize()
    first = ScopedEncryptedMemoryRepository(
        first_store.session_factory, MASTER_KEY, max_chars=20, redactor=PersistenceRedactor()
    )
    second = ScopedEncryptedMemoryRepository(
        second_store.session_factory, MASTER_KEY, max_chars=20, redactor=PersistenceRedactor()
    )
    await first.add("alice", "red", "old-one", provenance={})
    await first.add("alice", "red", "remove-me", provenance={})

    await asyncio.gather(
        first.replace("alice", "red", "old", "new", provenance={}),
        second.remove("alice", "red", "remove"),
        second.add("alice", "red", "plus", provenance={}),
    )
    facts = await first.list("alice", "red")
    async with second_store.session_factory() as session:
        scope = await session.get(MemoryScopeRow, ("alice", "red"))
        assert scope is not None
        assert scope.chars_used == sum(len(fact.content) for fact in facts)
        version = scope.version

    restarted = ScopedEncryptedMemoryRepository(
        second_store.session_factory,
        MASTER_KEY,
        max_chars=20,
        redactor=PersistenceRedactor(),
    )
    assert (
        sum(len(fact.content) for fact in await restarted.list("alice", "red")) == scope.chars_used
    )
    assert await restarted.delete_all("alice", "red") == len(facts)
    async with second_store.session_factory() as session:
        emptied = await session.get(MemoryScopeRow, ("alice", "red"))
        assert emptied is not None and emptied.chars_used == 0 and emptied.version == version + 1
    await first_store.close()
    await second_store.close()


async def test_bound_tools_and_conversation_search_are_owner_scoped(encrypted_memory, tmp_path):
    _, repository, _ = encrypted_memory
    conversation_url = f"sqlite+aiosqlite:///{tmp_path / 'conversations.db'}"
    conversations = ConversationRepository(conversation_url, PersistenceRedactor())
    await conversations.initialize()
    await conversations.create("alice-conv", "Alice", "alice")
    await conversations.store("alice-conv", "user", "private telescope notes", "alice")
    await conversations.create("bob-conv", "Bob", "bob")
    await conversations.store("bob-conv", "user", "private telescope notes", "bob")

    alice = RunContext("alice", "alice-conv", "run-a", "corr-a", "red")
    bob = RunContext("bob", "bob-conv", "run-b", "corr-b", "red")
    alice_memory = create_memory_tool(repository, alice)
    bob_memory = create_memory_tool(repository, bob)
    await asyncio.gather(
        alice_memory(action="add", content="alice fact"),
        bob_memory(action="add", content="bob fact"),
    )
    assert "alice fact" in await alice_memory(action="list")
    assert "bob fact" not in await alice_memory(action="list")

    alice_search = json.loads(await create_session_search_tool(conversations, alice)("telescope"))
    assert [result["conversation_id"] for result in alice_search["results"]] == ["alice-conv"]
    await conversations.close()
