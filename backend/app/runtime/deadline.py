"""Cancellation-resistant monotonic deadline enforcement for in-process awaits."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import Any, TypeVar

T = TypeVar("T")
Clock = Callable[[], float]


class DeadlineExceededError(TimeoutError):
    """A bounded operation exceeded its absolute monotonic deadline."""

    code = "deadline_exceeded"

    def __init__(self) -> None:
        super().__init__(self.code)


def consume_detached_task(task: asyncio.Task[Any]) -> None:
    """Retrieve a detached task outcome so late failures never reach the loop handler."""

    with suppress(BaseException):
        task.exception()


async def await_before_deadline(
    operation: Coroutine[Any, Any, T],
    *,
    deadline: float,
    clock: Clock = time.monotonic,
) -> T:
    """Return before ``deadline`` even when the operation suppresses cancellation.

    Cancellation is advisory for Python coroutines. On timeout or caller cancellation,
    detach the child after cancelling it, consume its eventual result, and never allow
    that late result to re-enter caller bookkeeping.
    """

    remaining = deadline - clock()
    if remaining <= 0:
        operation.close()
        raise DeadlineExceededError

    task = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait(
            {task}, timeout=max(0.0, deadline - clock()), return_when=asyncio.FIRST_COMPLETED
        )
        if task not in done or clock() >= deadline:
            task.cancel()
            task.add_done_callback(consume_detached_task)
            raise DeadlineExceededError
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(consume_detached_task)
        raise
