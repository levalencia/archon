"""Background task queue: submit, monitor, and list async tasks.

Uses asyncio.create_task internally. Each task has a lifecycle:
pending -> running -> completed | failed
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskRecord:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    _async_task: asyncio.Task | None = field(default=None, repr=False)


class TaskQueue:
    """In-memory async task queue."""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}

    async def submit_task(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple = (),
        kwargs: dict | None = None,
    ) -> str:
        """Submit an async callable for background execution. Returns task_id."""
        task_id = str(uuid.uuid4())
        record = TaskRecord(task_id=task_id)
        self._tasks[task_id] = record

        async def _run() -> None:
            record.status = TaskStatus.RUNNING
            try:
                record.result = await fn(*args, **(kwargs or {}))
                record.status = TaskStatus.COMPLETED
            except Exception as exc:
                record.status = TaskStatus.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                logger.error("task_failed", task_id=task_id, error=record.error)
            finally:
                record.completed_at = datetime.now(UTC).isoformat()

        record._async_task = asyncio.create_task(_run())
        logger.info("task_submitted", task_id=task_id)
        return task_id

    def get_status(self, task_id: str) -> dict | None:
        """Get task status and result. Returns None if not found."""
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return {
            "task_id": record.task_id,
            "status": record.status.value,
            "result": record.result,
            "error": record.error,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        }

    def list_tasks(self) -> list[dict]:
        """List all tasks with their statuses."""
        return [self.get_status(tid) for tid in self._tasks]  # type: ignore[misc]

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task. Returns True if cancelled."""
        record = self._tasks.get(task_id)
        if record is None or record._async_task is None:
            return False
        if record.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return False
        record._async_task.cancel()
        record.status = TaskStatus.FAILED
        record.error = "Cancelled by user"
        record.completed_at = datetime.now(UTC).isoformat()
        return True


# Module-level singleton
_task_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
