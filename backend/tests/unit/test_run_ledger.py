"""Sprint 2A acceptance tests for the durable run ledger."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore, RunRow, RuntimeEventRow
from app.services.run_ledger import LedgerDataError, RunRepository


def _event(run_id: str, *, user_id: str = "owner", kind: str = "run_started", iteration: int = 0):
    return {
        "run_id": run_id,
        "user_id": user_id,
        "project_id": "project",
        "conversation_id": "conversation",
        "correlation_id": "correlation",
        "provider": "mock",
        "model": "test-model",
        "kind": kind,
        "iteration": iteration,
        "payload": {},
    }


@pytest.fixture
async def ledger(tmp_path):
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'ledger.db'}")
    await store.initialize()
    yield store, RunRepository(store.session_factory, PersistenceRedactor())
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_append_is_unique_contiguous_and_restart_safe(ledger) -> None:
    store, repository = ledger
    await repository.ensure_run(
        run_id="run",
        user_id="owner",
        project_id="project",
        conversation_id="conversation",
        correlation_id="correlation",
        provider="mock",
        model="model",
    )
    await asyncio.gather(
        *(
            repository.append(**_event("run", kind="iteration_started", iteration=index))
            for index in range(1, 31)
        )
    )
    restarted = RunRepository(store.session_factory, PersistenceRedactor())
    page = await restarted.events("owner", "run", limit=100)
    assert page is not None
    assert [event.sequence for event in page.items] == list(range(1, 31))
    assert {event.iteration for event in page.items} == set(range(1, 31))


@pytest.mark.asyncio
async def test_owner_scoping_pagination_and_foreign_id_indistinguishable(ledger) -> None:
    _, repository = ledger
    await repository.append(**_event("owned", user_id="alice"))
    await repository.append(**_event("foreign", user_id="bob"))
    assert (await repository.list("alice", limit=1)).items[0].run_id == "owned"
    assert await repository.get("alice", "foreign") is None
    assert await repository.events("alice", "foreign") is None
    with pytest.raises(ValueError):
        await repository.list("alice", limit=201)


@pytest.mark.asyncio
async def test_redaction_and_allowlist_leave_no_raw_sensitive_payload(ledger) -> None:
    store, repository = ledger
    values = _event("private", kind="tool_call_completed")
    values["payload"] = {
        "id": "call",
        "name": "reader",
        "arguments": {"email": "person@example.com", "password": "raw-secret"},
        "result": "person@example.com raw-secret",
        "status": "success",
    }
    await repository.append(**values)
    async with store.session_factory() as session:
        raw = await session.scalar(select(RuntimeEventRow.payload))
    assert "person@example.com" not in raw
    assert "raw-secret" not in raw
    assert "arguments" not in raw
    assert "result" not in raw


@pytest.mark.asyncio
async def test_stop_finalizes_metrics_and_retention_removes_whole_completed_run(ledger) -> None:
    store, repository = ledger
    await repository.append(**_event("done"))
    stopped = _event("done", kind="run_stopped", iteration=3)
    stopped["payload"] = {"reason": "completed", "error": None}
    stopped.update(input_tokens=2, output_tokens=3, total_tokens=5)
    await repository.append(**stopped)
    run = await repository.get("owner", "done")
    assert run is not None
    assert (run.status, run.iterations, run.total_tokens) == ("completed", 3, 5)

    old = datetime.now(tz=UTC) - timedelta(days=2)
    async with store.session_factory() as session:
        await session.execute(
            update(RunRow).where(RunRow.run_id == "done").values(completed_at=old)
        )
        await session.commit()
    assert (
        await repository.prune_completed(
            "owner", completed_before=datetime.now(tz=UTC) - timedelta(days=1)
        )
        == 1
    )
    assert await repository.get("owner", "done") is None
    assert await repository.events("owner", "done") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_append_after_terminal_status_is_rejected_without_allocating_sequence(
    ledger, status: str
) -> None:
    store, repository = ledger
    await repository.append(**_event("terminal"))
    completed_at = datetime.now(tz=UTC)
    async with store.session_factory() as session:
        await session.execute(
            update(RunRow)
            .where(RunRow.run_id == "terminal")
            .values(status=status, completed_at=completed_at)
        )
        await session.commit()

    with pytest.raises(ValueError, match="run is not running"):
        await repository.append(**_event("terminal", kind="iteration_started", iteration=1))

    async with store.session_factory() as session:
        run = await session.scalar(select(RunRow).where(RunRow.run_id == "terminal"))
        events = (
            await session.scalars(
                select(RuntimeEventRow)
                .where(RuntimeEventRow.run_id == "terminal")
                .order_by(RuntimeEventRow.sequence)
            )
        ).all()
    assert run is not None
    assert (run.status, run.next_sequence) == (status, 2)
    assert run.completed_at is not None
    assert [event.sequence for event in events] == [1]


@pytest.mark.asyncio
async def test_concurrent_append_racing_finalize_is_linearizable(ledger) -> None:
    store, repository = ledger
    await repository.ensure_run(
        run_id="race",
        user_id="owner",
        project_id="project",
        conversation_id="conversation",
        correlation_id="correlation",
        provider="mock",
        model="test-model",
    )
    stopped = _event("race", kind="run_stopped", iteration=1)
    stopped["payload"] = {"reason": "completed", "error": None}
    results = await asyncio.gather(
        repository.append(**_event("race", kind="iteration_started", iteration=1)),
        repository.append(**stopped),
        return_exceptions=True,
    )

    page = await repository.events("owner", "race", limit=100)
    run = await repository.get("owner", "race")
    assert page is not None
    assert run is not None
    assert run.status == "completed"
    assert page.items[-1].kind == "run_stopped"
    assert [event.sequence for event in page.items] == list(range(1, len(page.items) + 1))
    assert len(page.items) in {1, 2}
    assert sum(isinstance(result, ValueError) for result in results) == 2 - len(page.items)
    async with store.session_factory() as session:
        next_sequence = await session.scalar(
            select(RunRow.next_sequence).where(RunRow.run_id == "race")
        )
    assert next_sequence == len(page.items) + 1


@pytest.mark.asyncio
async def test_finalize_is_idempotent_and_cannot_overwrite_terminal_run(ledger) -> None:
    _, repository = ledger
    stopped = _event("once", kind="run_stopped", iteration=2)
    stopped["payload"] = {"reason": "completed", "error": None}
    stopped.update(input_tokens=2, output_tokens=3, total_tokens=5)
    assert await repository.append(**stopped) == 1

    overwrite = _event("once", kind="run_stopped", iteration=9)
    overwrite["payload"] = {"reason": "failed", "error": True}
    overwrite.update(input_tokens=20, output_tokens=30, total_tokens=50)
    with pytest.raises(ValueError, match="run is not running"):
        await repository.append(**overwrite)

    run = await repository.get("owner", "once")
    page = await repository.events("owner", "once")
    assert run is not None
    assert page is not None
    assert (run.status, run.stop_reason, run.iterations, run.total_tokens) == (
        "completed",
        "completed",
        2,
        5,
    )
    assert [(event.sequence, event.kind) for event in page.items] == [(1, "run_stopped")]


@pytest.mark.asyncio
async def test_malformed_payload_and_unknown_version_fail_closed(ledger) -> None:
    store, repository = ledger
    await repository.append(**_event("broken"))
    async with store.session_factory() as session:
        await session.execute(
            update(RuntimeEventRow)
            .where(RuntimeEventRow.run_id == "broken")
            .values(payload="not-json")
        )
        await session.commit()
    with pytest.raises(LedgerDataError):
        await repository.events("owner", "broken")

    async with store.session_factory() as session:
        await session.execute(
            update(RunRow).where(RunRow.run_id == "broken").values(schema_version=999)
        )
        await session.commit()
    with pytest.raises(LedgerDataError):
        await repository.get("owner", "broken")
