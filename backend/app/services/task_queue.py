"""Durable, bounded background-job repository (never serialized callables)."""

from __future__ import annotations

import asyncio
import json
import math
import re
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.disclosure import DisclosureScanError, DisclosureScanner
from app.services.db_store import BackgroundJobRow

MAX_PAYLOAD_BYTES = 64 * 1024
MAX_RESULT_BYTES = 64 * 1024
ALLOWED_JOB_KINDS = frozenset({"echo", "run_export"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_DISCLOSURE = DisclosureScanner()


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class InvalidJob(ValueError):  # noqa: N818 - public API validation name
    pass


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: str
    owner_id: str
    project_id: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    lease_generation: int
    worker_id: str


def _safe_json(value: Any, maximum: int, *, redact: bool = False) -> str:
    try:
        scan = _DISCLOSURE.scan(value)
    except DisclosureScanError as exc:
        raise InvalidJob("payload is not safe JSON") from exc
    if scan.redaction_count and not redact:
        raise InvalidJob("payload contains sensitive data")
    value = scan.value
    nodes = 0

    def inspect(item: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 100_000:
            raise InvalidJob("JSON structure exceeds supported bounds")
        if item is None or isinstance(item, (str, int, bool)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise InvalidJob("payload contains a non-finite number")
            return
        if isinstance(item, list):
            for child in item:
                inspect(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise InvalidJob("payload object keys must be strings")
                inspect(child, depth + 1)
            return
        raise InvalidJob("payload must contain JSON values only")

    inspect(value)
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise InvalidJob("payload is not valid JSON") from exc
    if len(encoded.encode()) > maximum:
        raise InvalidJob("JSON payload exceeds the size limit")
    return encoded


def _view(row: BackgroundJobRow) -> dict[str, Any]:
    return {
        "job_id": row.job_id,
        "owner_id": row.owner_id,
        "project_id": row.project_id,
        "kind": row.kind,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "idempotency_key": row.idempotency_key,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "result": json.loads(row.result_json) if row.result_json else None,
        "error_code": row.error_code,
    }


class DurableJobQueue:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: int = 30,
        base_backoff_seconds: int = 2,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, (int, float))
            or not math.isfinite(lease_seconds)
            or lease_seconds <= 0
            or isinstance(base_backoff_seconds, bool)
            or not isinstance(base_backoff_seconds, (int, float))
            or not math.isfinite(base_backoff_seconds)
            or base_backoff_seconds < 0
        ):
            raise ValueError("job lease and backoff must be bounded non-negative values")
        self._sessions = sessions
        self._lease_seconds = lease_seconds
        self._base_backoff = base_backoff_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @property
    def heartbeat_interval_seconds(self) -> float:
        return max(0.05, self._lease_seconds / 3)

    async def create(
        self,
        owner_id: str,
        project_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if _SAFE_ID.fullmatch(owner_id) is None or _SAFE_ID.fullmatch(project_id) is None:
            raise InvalidJob("invalid owner or project scope")
        if kind not in ALLOWED_JOB_KINDS:
            raise InvalidJob("job kind is not allowlisted")
        if kind == "run_export" and (
            set(payload) != {"run_id"}
            or not isinstance(payload.get("run_id"), str)
            or _SAFE_ID.fullmatch(payload["run_id"]) is None
        ):
            raise InvalidJob("run_export requires one safe run_id")
        if not 1 <= max_attempts <= 10:
            raise InvalidJob("max_attempts is outside the supported bounds")
        if idempotency_key is not None and _SAFE_ID.fullmatch(idempotency_key) is None:
            raise InvalidJob("invalid idempotency key")
        payload_json = _safe_json(payload, MAX_PAYLOAD_BYTES)
        now = self._now()
        async with self._sessions() as session:

            async def existing_job() -> BackgroundJobRow | None:
                if idempotency_key is None:
                    return None
                return (
                    await session.execute(
                        select(BackgroundJobRow).where(
                            BackgroundJobRow.owner_id == owner_id,
                            BackgroundJobRow.project_id == project_id,
                            BackgroundJobRow.idempotency_key == idempotency_key,
                        )
                    )
                ).scalar_one_or_none()

            def existing_view(existing: BackgroundJobRow) -> dict[str, Any]:
                if (
                    existing.kind != kind
                    or existing.payload_json != payload_json
                    or existing.max_attempts != max_attempts
                ):
                    raise InvalidJob("idempotency key conflicts with an existing job")
                return _view(existing)

            try:
                async with session.begin():
                    existing = await existing_job()
                    if existing is not None:
                        return existing_view(existing)
                    row = BackgroundJobRow(
                        job_id=str(uuid.uuid4()),
                        owner_id=owner_id,
                        project_id=project_id,
                        kind=kind,
                        payload_json=payload_json,
                        status=JobStatus.PENDING.value,
                        attempts=0,
                        max_attempts=max_attempts,
                        lease_generation=0,
                        idempotency_key=idempotency_key,
                        available_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                    await session.flush()
                    return _view(row)
            except IntegrityError as exc:
                await session.rollback()
                existing = await existing_job()
                if existing is None:
                    raise InvalidJob("job idempotency conflict") from exc
                return existing_view(existing)

    async def get(self, owner_id: str, project_id: str, job_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(BackgroundJobRow).where(
                        BackgroundJobRow.job_id == job_id,
                        BackgroundJobRow.owner_id == owner_id,
                        BackgroundJobRow.project_id == project_id,
                    )
                )
            ).scalar_one_or_none()
            return _view(row) if row else None

    async def list(
        self, owner_id: str, *, project_id: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        query = select(BackgroundJobRow).where(BackgroundJobRow.owner_id == owner_id)
        if project_id is not None:
            query = query.where(BackgroundJobRow.project_id == project_id)
        query = query.order_by(BackgroundJobRow.created_at.desc()).limit(limit).offset(offset)
        async with self._sessions() as session:
            return [_view(row) for row in (await session.execute(query)).scalars()]

    async def claim(self, worker_id: str) -> ClaimedJob | None:
        if _SAFE_ID.fullmatch(worker_id) is None:
            raise InvalidJob("invalid worker identifier")
        now = self._now()
        lease = now + timedelta(seconds=self._lease_seconds)
        async with self._sessions() as session, session.begin():
            candidate = (
                select(BackgroundJobRow.job_id)
                .where(
                    BackgroundJobRow.status == JobStatus.PENDING.value,
                    BackgroundJobRow.available_at <= now,
                    BackgroundJobRow.attempts < BackgroundJobRow.max_attempts,
                )
                .order_by(BackgroundJobRow.available_at, BackgroundJobRow.created_at)
                .limit(1)
                .scalar_subquery()
            )
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == candidate,
                    BackgroundJobRow.status == JobStatus.PENDING.value,
                )
                .values(
                    status=JobStatus.RUNNING.value,
                    worker_id=worker_id,
                    attempts=BackgroundJobRow.attempts + 1,
                    lease_generation=BackgroundJobRow.lease_generation + 1,
                    lease_expires_at=lease,
                    updated_at=now,
                )
                .returning(BackgroundJobRow)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return ClaimedJob(
                row.job_id,
                row.owner_id,
                row.project_id,
                row.kind,
                json.loads(row.payload_json),
                row.attempts,
                row.max_attempts,
                row.lease_generation,
                worker_id,
            )

    async def heartbeat(self, job: ClaimedJob) -> bool:
        now = self._now()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == job.job_id,
                    BackgroundJobRow.worker_id == job.worker_id,
                    BackgroundJobRow.attempts == job.attempts,
                    BackgroundJobRow.lease_generation == job.lease_generation,
                    BackgroundJobRow.status == JobStatus.RUNNING.value,
                    BackgroundJobRow.lease_expires_at > now,
                )
                .values(
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds), updated_at=now
                )
            )
            return bool(result.rowcount)

    async def recover_expired(self) -> int:
        now = self._now()
        async with self._sessions() as session, session.begin():
            retry = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.status == JobStatus.RUNNING.value,
                    BackgroundJobRow.lease_expires_at < now,
                    BackgroundJobRow.attempts < BackgroundJobRow.max_attempts,
                )
                .values(
                    status=JobStatus.PENDING.value,
                    worker_id=None,
                    lease_expires_at=None,
                    available_at=now,
                    updated_at=now,
                    error_code="lease_expired",
                )
            )
            dead = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.status == JobStatus.RUNNING.value,
                    BackgroundJobRow.lease_expires_at < now,
                    BackgroundJobRow.attempts >= BackgroundJobRow.max_attempts,
                )
                .values(
                    status=JobStatus.DEAD_LETTER.value,
                    worker_id=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                    error_code="lease_expired",
                )
            )
            return int((retry.rowcount or 0) + (dead.rowcount or 0))

    async def succeed(self, job: ClaimedJob, result_value: Any) -> bool:
        encoded = _safe_json(result_value, MAX_RESULT_BYTES, redact=True)
        now = self._now()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == job.job_id,
                    BackgroundJobRow.worker_id == job.worker_id,
                    BackgroundJobRow.attempts == job.attempts,
                    BackgroundJobRow.lease_generation == job.lease_generation,
                    BackgroundJobRow.status == JobStatus.RUNNING.value,
                    BackgroundJobRow.lease_expires_at > now,
                )
                .values(
                    status=JobStatus.SUCCEEDED.value,
                    result_json=encoded,
                    error_code=None,
                    worker_id=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            return bool(result.rowcount)

    async def fail(self, job: ClaimedJob, error_code: str, *, retryable: bool = True) -> bool:
        if len(error_code) > 64 or _SAFE_ID.fullmatch(error_code) is None:
            raise InvalidJob("invalid job error code")
        now = self._now()
        if not retryable:
            status = JobStatus.FAILED.value
            available = now
            completed = now
        elif job.attempts < job.max_attempts:
            status = JobStatus.PENDING.value
            available = now + timedelta(seconds=self._base_backoff * (2 ** (job.attempts - 1)))
            completed = None
        else:
            status = JobStatus.DEAD_LETTER.value
            available = now
            completed = now
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == job.job_id,
                    BackgroundJobRow.worker_id == job.worker_id,
                    BackgroundJobRow.attempts == job.attempts,
                    BackgroundJobRow.lease_generation == job.lease_generation,
                    BackgroundJobRow.status == JobStatus.RUNNING.value,
                    BackgroundJobRow.lease_expires_at > now,
                )
                .values(
                    status=status,
                    available_at=available,
                    completed_at=completed,
                    error_code=error_code,
                    worker_id=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            return bool(result.rowcount)

    async def cancel(self, owner_id: str, project_id: str, job_id: str) -> bool:
        now = self._now()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == job_id,
                    BackgroundJobRow.owner_id == owner_id,
                    BackgroundJobRow.project_id == project_id,
                    BackgroundJobRow.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
                )
                .values(
                    status=JobStatus.CANCELLED.value,
                    worker_id=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                    error_code=None,
                )
            )
            return bool(result.rowcount)

    async def retry(self, owner_id: str, project_id: str, job_id: str) -> bool:
        now = self._now()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(BackgroundJobRow)
                .where(
                    BackgroundJobRow.job_id == job_id,
                    BackgroundJobRow.owner_id == owner_id,
                    BackgroundJobRow.project_id == project_id,
                    or_(
                        BackgroundJobRow.status == JobStatus.DEAD_LETTER.value,
                        BackgroundJobRow.status == JobStatus.FAILED.value,
                    ),
                )
                .values(
                    status=JobStatus.PENDING.value,
                    attempts=0,
                    available_at=now,
                    completed_at=None,
                    error_code=None,
                    updated_at=now,
                )
            )
            return bool(result.rowcount)


# Compatibility for pre-S8.6 direct unit consumers only. Production routes and workers use
# DurableJobQueue; this shim never serializes or persists a callable.
class TaskQueue:
    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}

    async def submit_task(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> str:
        task_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "task_id": task_id,
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
        }
        self._tasks[task_id] = record

        async def run() -> None:
            record["status"] = "running"
            try:
                record["result"] = await fn(*args, **(kwargs or {}))
                record["status"] = "completed"
            except asyncio.CancelledError:
                record["status"] = "failed"
                record["error"] = "Cancelled by user"
            except Exception as exc:
                record["status"] = "failed"
                record["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                record["completed_at"] = datetime.now(UTC).isoformat()

        record["_task"] = asyncio.create_task(run())
        return task_id

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return {key: value for key, value in record.items() if key != "_task"}

    def list_tasks(self) -> list[dict[str, Any]]:
        return [item for task_id in self._tasks if (item := self.get_status(task_id)) is not None]

    def cancel(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if record is None or record["status"] in {"completed", "failed"}:
            return False
        task = record.get("_task")
        if isinstance(task, asyncio.Task):
            task.cancel()
        record["status"] = "failed"
        record["error"] = "Cancelled by user"
        record["completed_at"] = datetime.now(UTC).isoformat()
        return True


# Import compatibility for the legacy chat tool. New submissions are available only through the
# authenticated durable API; this singleton therefore cannot receive production work.
_legacy_task_queue = TaskQueue()


def get_task_queue() -> TaskQueue:
    return _legacy_task_queue
