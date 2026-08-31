"""Adversarial contracts for monotonic hard deadlines."""

from __future__ import annotations

import asyncio

import pytest

from app.runtime.deadline import DeadlineExceededError, await_before_deadline


@pytest.mark.asyncio
async def test_deadline_detaches_cancellation_resistant_coroutine() -> None:
    finished = asyncio.Event()

    async def stubborn() -> str:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
        finished.set()
        return "late-value"

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(DeadlineExceededError, match="^deadline_exceeded$"):
        await await_before_deadline(stubborn(), deadline=started + 0.01, clock=loop.time)
    assert loop.time() - started < 0.04
    await asyncio.wait_for(finished.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_caller_cancellation_detaches_child() -> None:
    finished = asyncio.Event()

    async def stubborn() -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.02)
        finished.set()

    outer = asyncio.create_task(
        await_before_deadline(stubborn(), deadline=asyncio.get_running_loop().time() + 10)
    )
    await asyncio.sleep(0)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer
    await asyncio.wait_for(finished.wait(), timeout=0.2)


def test_already_expired_deadline_closes_unstarted_coroutine() -> None:
    async def never_started() -> None:
        raise AssertionError("must not run")

    operation = never_started()

    async def run() -> None:
        with pytest.raises(DeadlineExceededError):
            await await_before_deadline(operation, deadline=0.0, clock=lambda: 1.0)

    asyncio.run(run())
