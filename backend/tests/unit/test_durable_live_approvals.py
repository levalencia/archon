from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.runtime.factory import RunContext
from app.security.approval_repository import ApprovalRepository, ApprovalStatus
from app.security.approvals import AuthorizationRequest
from app.security.live_approvals import DurableApprovalBroker
from app.security.policy import RiskClass
from app.services.db_store import Base


def context(
    user: str = "alice", run: str = "run-1", conversation: str = "conversation"
) -> RunContext:
    return RunContext(user, conversation, run, f"correlation-{run}")


def request(call_id: str = "call-1", digest: str = "a" * 64) -> AuthorizationRequest:
    return AuthorizationRequest(
        call_id,
        "terminal",
        digest,
        frozenset({RiskClass.EXECUTE}),
        "side_effects_require_approval",
    )


async def brokers(path, *, timeout: float = 1.0, poll: float = 0.01):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    repository = ApprovalRepository(factory)
    return (
        DurableApprovalBroker(repository, timeout_seconds=timeout, poll_interval_seconds=poll),
        DurableApprovalBroker(repository, timeout_seconds=timeout, poll_interval_seconds=poll),
        repository,
        engine,
    )


@pytest.mark.asyncio
async def test_cross_process_prepare_decide_and_poll(tmp_path) -> None:
    first, second, _, engine = await brokers(tmp_path / "cross-process.db")
    owner = context()
    approval = request()
    authorizer = first.authorizer(owner)
    await authorizer.prepare(approval)
    waiter = asyncio.create_task(authorizer.authorize(approval))

    assert await second.decide_for_owner(user_id="alice", tool_call_id="call-1", approved=True)
    outcome = await asyncio.wait_for(waiter, timeout=1)

    assert outcome.approved is True
    assert outcome.reason_code == "user_approved"
    assert await first.pending_count() == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_immediate_decision_and_restart_authorize(tmp_path) -> None:
    first, second, _, engine = await brokers(tmp_path / "restart.db")
    owner = context()
    approval = request("instant")
    await first.authorizer(owner).prepare(approval)

    assert await second.decide_for_owner(user_id="alice", tool_call_id="instant", approved=False)
    outcome = await second.authorizer(owner).authorize(approval)

    assert outcome.approved is False
    assert outcome.reason_code == "user_denied"
    await engine.dispose()


@pytest.mark.asyncio
async def test_exact_cancel_and_run_cancel_are_persisted(tmp_path) -> None:
    broker, _, repository, engine = await brokers(tmp_path / "cancel.db")
    owner = context()
    one = request("one")
    two = request("two", "b" * 64)
    await broker.authorizer(owner).prepare(one)
    await broker.authorizer(owner).prepare(two)

    await broker.cancel(owner, one)
    one_record = await repository.get_exact_binding(
        user_id="alice",
        conversation_id="conversation",
        run_id="run-1",
        tool_call_id="one",
        tool_name="terminal",
        arguments_hash="a" * 64,
    )
    assert one_record is not None and one_record.status is ApprovalStatus.CANCELLED
    assert await broker.pending_count() == 1

    await broker.cancel_run(owner)
    two_record = await repository.get_exact_binding(
        user_id="alice",
        conversation_id="conversation",
        run_id="run-1",
        tool_call_id="two",
        tool_name="terminal",
        arguments_hash="b" * 64,
    )
    assert two_record is not None and two_record.status is ApprovalStatus.CANCELLED
    assert await broker.pending_count() == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_expiry_is_persisted_and_returns_sanitized_denial(tmp_path) -> None:
    broker, _, repository, engine = await brokers(tmp_path / "expiry.db", timeout=0.03, poll=0.005)
    owner = context()
    approval = request("expires")
    authorizer = broker.authorizer(owner)
    await authorizer.prepare(approval)

    outcome = await authorizer.authorize(approval)
    record = await repository.get_exact_binding(
        user_id="alice",
        conversation_id="conversation",
        run_id="run-1",
        tool_call_id="expires",
        tool_name="terminal",
        arguments_hash="a" * 64,
    )
    assert outcome.approved is False
    assert outcome.reason_code == "approval_expired"
    assert record is not None and record.status is ApprovalStatus.EXPIRED
    await engine.dispose()


@pytest.mark.asyncio
async def test_ambiguous_owner_call_fails_closed_and_concurrent_decision_has_one_winner(
    tmp_path,
) -> None:
    broker, second, _, engine = await brokers(tmp_path / "owner.db")
    approval = request("shared")
    await broker.authorizer(context(run="run-a", conversation="a")).prepare(approval)
    await broker.authorizer(context(run="run-b", conversation="b")).prepare(approval)

    assert not await broker.decide_for_owner(user_id="alice", tool_call_id="shared", approved=True)
    await broker.cancel_run(context(run="run-b", conversation="b"))
    results = await asyncio.gather(
        broker.decide_for_owner(user_id="alice", tool_call_id="shared", approved=True),
        second.decide_for_owner(user_id="alice", tool_call_id="shared", approved=False),
    )
    assert sorted(results) == [False, True]
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_schema_has_no_raw_arguments(tmp_path) -> None:
    broker, _, _, engine = await brokers(tmp_path / "no-args.db")
    await broker.authorizer(context()).prepare(request())
    with sqlite3.connect(tmp_path / "no-args.db") as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(approval_requests)")}
    assert "arguments" not in columns
    assert "arguments_json" not in columns
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_waiter_persists_cancelled_receipt(tmp_path) -> None:
    broker, _, repository, engine = await brokers(tmp_path / "waiter-cancel.db")
    owner = context()
    approval = request("cancelled-waiter")
    authorizer = broker.authorizer(owner)
    await authorizer.prepare(approval)
    waiter = asyncio.create_task(authorizer.authorize(approval))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    record = await repository.get_exact_binding(
        user_id="alice",
        conversation_id="conversation",
        run_id="run-1",
        tool_call_id="cancelled-waiter",
        tool_name="terminal",
        arguments_hash="a" * 64,
    )
    assert record is not None
    assert record.status is ApprovalStatus.CANCELLED
    assert record.decision_reason == "approval_cancelled"
    await engine.dispose()
