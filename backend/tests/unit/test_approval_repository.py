from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.security.approval_repository import ApprovalRepository, ApprovalStatus
from app.security.policy import RiskClass
from app.services.db_store import Base


async def repository(path) -> tuple[ApprovalRepository, object]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return ApprovalRepository(factory), engine


async def reserve(repo: ApprovalRepository, **overrides):
    values = {
        "user_id": "alice",
        "conversation_id": "conversation-1",
        "run_id": "run-1",
        "tool_call_id": "call-1",
        "tool_name": "terminal",
        "arguments_hash": "a" * 64,
        "risk_classes": frozenset({RiskClass.EXECUTE}),
        "matched_rule_id": "approval_required",
        "ttl": timedelta(minutes=5),
    }
    values.update(overrides)
    return await repo.reserve(**values)


@pytest.mark.asyncio
async def test_reserve_persists_without_raw_arguments_and_survives_restart(tmp_path) -> None:
    database = tmp_path / "approvals.db"
    first, first_engine = await repository(database)
    record = await reserve(first)
    await first_engine.dispose()

    second_engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    factory = async_sessionmaker(second_engine, class_=AsyncSession, expire_on_commit=False)
    second = ApprovalRepository(factory)
    loaded = await second.get_owner(record.id, "alice")
    assert loaded == record
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(approval_requests)")}
    assert "arguments" not in columns
    assert "arguments_json" not in columns
    await second_engine.dispose()


@pytest.mark.asyncio
async def test_status_read_lazily_expires_and_persists_across_restart(tmp_path) -> None:
    database = tmp_path / "lazy-expiry.db"
    created_at = datetime(2026, 8, 26, 12, tzinfo=UTC)
    deadline = created_at + timedelta(minutes=5)
    first, first_engine = await repository(database)
    record = await reserve(first, now=created_at)

    assert await first.get_status(record.id, "alice", now=deadline) is ApprovalStatus.EXPIRED
    await first_engine.dispose()

    second_engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    factory = async_sessionmaker(second_engine, class_=AsyncSession, expire_on_commit=False)
    second = ApprovalRepository(factory)
    loaded = await second.get_owner(record.id, "alice", now=created_at)
    assert loaded is not None
    assert loaded.status is ApprovalStatus.EXPIRED
    assert loaded.decision_reason == "approval_expired"
    assert loaded.decided_at == deadline
    await second_engine.dispose()


@pytest.mark.asyncio
async def test_pending_lookup_persists_matching_expiry_without_crossing_owners(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "lazy-pending.db")
    created_at = datetime(2026, 8, 26, 12, tzinfo=UTC)
    deadline = created_at + timedelta(minutes=5)
    alice = await reserve(repo, now=created_at, tool_call_id="shared")
    bob = await reserve(
        repo, now=created_at, user_id="bob", run_id="bob-run", tool_call_id="shared"
    )

    assert (
        await repo.find_pending_by_tool_call(user_id="alice", tool_call_id="shared", now=deadline)
        is None
    )
    alice_loaded = await repo.get_owner(alice.id, "alice", now=created_at)
    bob_loaded = await repo.get_owner(bob.id, "bob", now=created_at)
    assert alice_loaded is not None and alice_loaded.status is ApprovalStatus.EXPIRED
    assert bob_loaded is not None and bob_loaded.status is ApprovalStatus.PENDING
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_isolation_expiry_and_one_shot_decision(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "owner.db")
    record = await reserve(repo)
    assert await repo.get_owner(record.id, "bob") is None
    assert not await repo.decide_for_owner(
        approval_id=record.id,
        user_id="bob",
        status=ApprovalStatus.APPROVED,
        reason="user_approved",
    )
    assert await repo.decide_for_owner(
        approval_id=record.id,
        user_id="alice",
        status=ApprovalStatus.APPROVED,
        reason="user_approved",
    )
    assert not await repo.decide_for_owner(
        approval_id=record.id,
        user_id="alice",
        status=ApprovalStatus.DENIED,
        reason="user_denied",
    )
    assert await repo.get_status(record.id, "alice") is ApprovalStatus.APPROVED

    expired = await reserve(repo, run_id="run-expired", ttl=timedelta(microseconds=1))
    await asyncio.sleep(0.01)
    assert not await repo.decide_for_owner(
        approval_id=expired.id,
        user_id="alice",
        status=ApprovalStatus.APPROVED,
        reason="too_late",
    )
    assert await repo.expire_due() == 1
    assert await repo.get_status(expired.id, "alice") is ApprovalStatus.EXPIRED
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_decisions_have_exactly_one_winner(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "concurrent.db")
    record = await reserve(repo)
    results = await asyncio.gather(
        repo.decide_for_owner(
            approval_id=record.id,
            user_id="alice",
            status=ApprovalStatus.APPROVED,
            reason="user_approved",
        ),
        repo.decide_for_owner(
            approval_id=record.id,
            user_id="alice",
            status=ApprovalStatus.DENIED,
            reason="user_denied",
        ),
    )
    assert sorted(results) == [False, True]
    await engine.dispose()


@pytest.mark.asyncio
async def test_exact_decision_cannot_cross_runs_and_has_one_winner(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "exact-concurrent.db")
    first = await reserve(repo, run_id="run-a", tool_call_id="shared")
    second = await reserve(repo, run_id="run-b", tool_call_id="shared")

    assert not await repo.decide_exact_for_owner(
        user_id="alice",
        run_id="wrong-run",
        tool_call_id="shared",
        status=ApprovalStatus.APPROVED,
        reason="user_approved",
    )
    results = await asyncio.gather(
        repo.decide_exact_for_owner(
            user_id="alice",
            run_id="run-a",
            tool_call_id="shared",
            status=ApprovalStatus.APPROVED,
            reason="user_approved",
        ),
        repo.decide_exact_for_owner(
            user_id="alice",
            run_id="run-a",
            tool_call_id="shared",
            status=ApprovalStatus.DENIED,
            reason="user_denied",
        ),
    )
    assert sorted(results) == [False, True]
    assert await repo.get_status(first.id, "alice") in {
        ApprovalStatus.APPROVED,
        ApprovalStatus.DENIED,
    }
    assert await repo.get_status(second.id, "alice") is ApprovalStatus.PENDING
    await engine.dispose()


@pytest.mark.asyncio
async def test_lazy_expiry_and_decision_race_respects_deadline(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "expiry-race.db")
    created_at = datetime(2026, 8, 26, 12, tzinfo=UTC)
    deadline = created_at + timedelta(minutes=5)
    record = await reserve(repo, now=created_at)

    status, approved = await asyncio.gather(
        repo.get_status(record.id, "alice", now=deadline),
        repo.decide_for_owner(
            approval_id=record.id,
            user_id="alice",
            status=ApprovalStatus.APPROVED,
            reason="user_approved",
            now=deadline,
        ),
    )
    assert status is ApprovalStatus.EXPIRED
    assert not approved
    loaded = await repo.get_owner(record.id, "alice", now=created_at)
    assert loaded is not None
    assert loaded.status is ApprovalStatus.EXPIRED
    assert loaded.decision_reason == "approval_expired"
    await engine.dispose()


@pytest.mark.asyncio
async def test_ambiguous_pending_call_fails_closed_and_cancel_run(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "ambiguous.db")
    await reserve(repo, run_id="run-a", tool_call_id="same")
    await reserve(repo, run_id="run-b", tool_call_id="same")
    await reserve(repo, user_id="bob", run_id="run-b", tool_call_id="same")
    assert await repo.find_pending_by_tool_call(user_id="alice", tool_call_id="same") is None
    assert (await repo.find_pending_by_tool_call(user_id="bob", tool_call_id="same")) is not None
    assert await repo.cancel_run(user_id="alice", run_id="run-a") == 1
    remaining = await repo.find_pending_by_tool_call(user_id="alice", tool_call_id="same")
    assert remaining is not None and remaining.run_id == "run-b"
    await engine.dispose()


@pytest.mark.asyncio
async def test_strict_validation(tmp_path) -> None:
    repo, engine = await repository(tmp_path / "validation.db")
    with pytest.raises(ValueError, match="canonical"):
        await reserve(repo, tool_name=" Terminal ")
    with pytest.raises(ValueError, match="SHA-256"):
        await reserve(repo, arguments_hash="raw arguments")
    with pytest.raises(ValueError, match="ttl"):
        await reserve(repo, ttl=timedelta(0))
    await engine.dispose()
