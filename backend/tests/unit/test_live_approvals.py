from __future__ import annotations

import asyncio

import pytest

from app.runtime.factory import RunContext
from app.security.approvals import AuthorizationRequest
from app.security.live_approvals import ApprovalBroker
from app.security.policy import RiskClass


def context(user: str, run: str, conversation: str = "conversation") -> RunContext:
    return RunContext(user, conversation, run, f"correlation-{run}")


def request(call_id: str = "same-id") -> AuthorizationRequest:
    return AuthorizationRequest(
        call_id,
        "terminal",
        "a" * 64,
        frozenset({RiskClass.EXECUTE}),
        "side_effects_require_approval",
    )


async def start_wait(
    broker: ApprovalBroker,
    owner: RunContext,
    call_id: str = "same-id",
    expected_count: int = 1,
) -> asyncio.Task:
    authorizer = broker.authorizer(owner)
    approval_request = request(call_id)
    await authorizer.prepare(approval_request)
    task = asyncio.create_task(authorizer.authorize(approval_request))
    await asyncio.sleep(0)
    for _ in range(20):
        if await broker.pending_count() >= expected_count:
            break
        await asyncio.sleep(0)
    return task


@pytest.mark.asyncio
async def test_decision_may_arrive_after_reserve_but_before_waiter_starts() -> None:
    broker = ApprovalBroker()
    owner = context("alice", "run-a")
    approval_request = request("instant")
    authorizer = broker.authorizer(owner)

    await authorizer.prepare(approval_request)
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="instant", approved=True
    )
    assert not await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="instant", approved=False
    )

    outcome = await authorizer.authorize(approval_request)
    assert outcome.approved is True
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_wait_requires_exact_prepared_binding_and_cancel_cleans_it() -> None:
    broker = ApprovalBroker()
    owner = context("alice", "run-a")
    authorizer = broker.authorizer(owner)
    reserved = request("bound")
    await authorizer.prepare(reserved)
    mismatched = AuthorizationRequest(
        "bound", "terminal", "b" * 64, reserved.risk_classes, reserved.matched_rule_id
    )

    with pytest.raises(RuntimeError, match="does not match"):
        await authorizer.authorize(mismatched)
    assert await broker.pending_count() == 1
    await authorizer.cancel(reserved)
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_owner_can_approve_or_deny_and_decisions_are_one_shot() -> None:
    broker = ApprovalBroker()
    owner = context("alice", "run-a")

    approved_task = await start_wait(broker, owner, "approve-me")
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="approve-me", approved=True
    )
    approved = await approved_task
    assert approved.approved is True
    assert approved.reason_code == "user_approved"
    assert not await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="approve-me", approved=False
    )

    denied_task = await start_wait(broker, owner, "deny-me")
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="deny-me", approved=False
    )
    denied = await denied_task
    assert denied.approved is False
    assert denied.reason_code == "user_denied"


@pytest.mark.asyncio
async def test_foreign_owner_is_indistinguishable_from_missing() -> None:
    broker = ApprovalBroker()
    task = await start_wait(broker, context("alice", "run-a"))
    assert not await broker.decide_for_owner(
        user_id="bob", run_id="run-a", tool_call_id="same-id", approved=True
    )
    assert not await broker.decide_for_owner(
        user_id="bob", run_id="run-a", tool_call_id="missing", approved=True
    )
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="same-id", approved=False
    )
    assert not (await task).approved


@pytest.mark.asyncio
async def test_same_call_id_across_users_and_runs_does_not_collide() -> None:
    broker = ApprovalBroker()
    alice_a = await start_wait(broker, context("alice", "run-a"))
    bob = await start_wait(broker, context("bob", "run-b"), expected_count=2)
    assert await broker.decide_for_owner(
        user_id="bob", run_id="run-b", tool_call_id="same-id", approved=True
    )
    assert (await bob).approved
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="same-id", approved=False
    )
    assert not (await alice_a).approved


@pytest.mark.asyncio
async def test_same_owner_call_id_is_decided_only_for_exact_run() -> None:
    broker = ApprovalBroker()
    first_context = context("alice", "run-a", "one")
    second_context = context("alice", "run-b", "two")
    first = await start_wait(broker, first_context)
    second = await start_wait(broker, second_context, expected_count=2)

    assert not await broker.decide_for_owner(
        user_id="alice", run_id="wrong-run", tool_call_id="same-id", approved=True
    )
    assert await broker.decide_for_owner(
        user_id="alice", run_id="run-a", tool_call_id="same-id", approved=True
    )
    assert (await first).approved
    await broker.cancel_run(second_context)
    with pytest.raises(asyncio.CancelledError):
        await second
    assert await broker.pending_count() == 0


@pytest.mark.asyncio
async def test_waiter_cancellation_removes_pending_without_storing_arguments() -> None:
    broker = ApprovalBroker()
    task = await start_wait(broker, context("alice", "run-a"), "secret-call")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await broker.pending_count() == 0
    # The service API accepts only the immutable request digest, never raw argument values.
    assert "arguments" not in ApprovalBroker.wait_for_decision.__annotations__
