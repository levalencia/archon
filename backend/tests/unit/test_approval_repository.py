from __future__ import annotations

import asyncio
import sqlite3
from datetime import timedelta

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
