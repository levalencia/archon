"""Allowlisted durable-job worker loop."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import Any

import structlog

from app.observability.logging import safe_exception_metadata
from app.services.task_queue import ALLOWED_JOB_KINDS, ClaimedJob, DurableJobQueue

logger = structlog.get_logger()
JobHandler = Callable[[ClaimedJob], Coroutine[Any, Any, Any]]


async def echo_handler(job: ClaimedJob) -> dict[str, Any]:
    """Safe built-in used for health checks and simple metadata work."""
    return {"payload": job.payload}


class PermanentJobError(RuntimeError):
    """A safe non-retryable handler failure."""


class HandlerCancelledError(RuntimeError):
    """The handler cancelled itself; the worker must remain alive."""


class JobWorker:
    def __init__(
        self,
        queue: DurableJobQueue,
        worker_id: str,
        handlers: dict[str, JobHandler] | None = None,
        *,
        poll_seconds: float = 0.25,
        handler_timeout_seconds: float = 300.0,
    ) -> None:
        supplied = handlers or {"echo": echo_handler}
        if not set(supplied).issubset(ALLOWED_JOB_KINDS):
            raise ValueError("worker contains a non-allowlisted handler")
        if (
            isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, (int, float))
            or not math.isfinite(poll_seconds)
            or not 0.01 <= poll_seconds <= 60
            or isinstance(handler_timeout_seconds, bool)
            or not isinstance(handler_timeout_seconds, (int, float))
            or not math.isfinite(handler_timeout_seconds)
            or not 0.1 <= handler_timeout_seconds <= 3600
        ):
            raise ValueError("worker timing is outside supported bounds")
        self._queue = queue
        self._worker_id = worker_id
        self._handlers = dict(supplied)
        self._poll = poll_seconds
        self._handler_timeout = handler_timeout_seconds
        self.last_error_code: str | None = None

    @staticmethod
    def _consume_detached(task: asyncio.Task[Any]) -> None:
        with suppress(asyncio.CancelledError, Exception):
            task.result()

    async def _run_with_heartbeat(self, job: ClaimedJob, handler: JobHandler) -> Any:
        task = asyncio.create_task(handler(job))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._handler_timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    task.cancel()
                    task.add_done_callback(self._consume_detached)
                    raise TimeoutError("job handler deadline exceeded")
                done, _ = await asyncio.wait(
                    {task}, timeout=min(self._queue.heartbeat_interval_seconds, remaining)
                )
                if task in done:
                    try:
                        return task.result()
                    except asyncio.CancelledError as exc:
                        raise HandlerCancelledError("handler_cancelled") from exc
                if loop.time() >= deadline:
                    task.cancel()
                    task.add_done_callback(self._consume_detached)
                    raise TimeoutError("job handler deadline exceeded")
                if not await self._queue.heartbeat(job):
                    task.cancel()
                    task.add_done_callback(self._consume_detached)
                    raise PermanentJobError("job_lease_lost")
        except asyncio.CancelledError:
            task.cancel()
            task.add_done_callback(self._consume_detached)
            raise

    async def run_once(self) -> bool:
        await self._queue.recover_expired()
        job = await self._queue.claim(self._worker_id)
        if job is None:
            return False
        handler = self._handlers.get(job.kind)
        if handler is None:
            await self._queue.fail(job, "handler_unavailable", retryable=False)
            return True
        try:
            result = await self._run_with_heartbeat(job, handler)
            await self._queue.succeed(job, result)
        except asyncio.CancelledError:
            # This branch is only worker shutdown; handler self-cancellation is wrapped above.
            raise
        except HandlerCancelledError:
            await self._queue.fail(job, "handler_cancelled")
        except PermanentJobError as exc:
            if str(exc) != "job_lease_lost":
                await self._queue.fail(job, "handler_rejected", retryable=False)
        except TimeoutError:
            await self._queue.fail(job, "job_timeout")
        except Exception as exc:
            logger.warning(
                "background_job_failed",
                job_id=job.job_id,
                kind=job.kind,
                attempts=job.attempts,
                **safe_exception_metadata(exc, "job_handler_failed"),
            )
            await self._queue.fail(job, "handler_failed")
        return True

    async def run_forever(self) -> None:
        while True:
            try:
                processed = await self.run_once()
                self.last_error_code = None
                if not processed:
                    await asyncio.sleep(self._poll)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error_code = "job_worker_iteration_failed"
                logger.error(
                    "background_worker_iteration_failed",
                    worker_id=self._worker_id,
                    **safe_exception_metadata(exc, "job_worker_iteration_failed"),
                )
                await asyncio.sleep(self._poll)
