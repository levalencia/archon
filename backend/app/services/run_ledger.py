"""Owner-scoped append-only run ledger repository."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.events import AgentEventKind
from app.runtime.run_models import EventPage, RunEventRecord, RunPage, RunRecord
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import RunRow, RuntimeEventRow

SCHEMA_VERSION = 1
_MAX_PAGE = 200
_SAFE_FIELDS: dict[str, frozenset[str]] = {
    AgentEventKind.RUN_STARTED.value: frozenset({"safe"}),
    AgentEventKind.ITERATION_STARTED.value: frozenset(),
    AgentEventKind.MODEL_RESPONSE.value: frozenset({"provider_stop_reason"}),
    AgentEventKind.MODEL_PROGRESS.value: frozenset(),
    AgentEventKind.TEXT_DELTA.value: frozenset(),
    AgentEventKind.TOOL_CALL_REQUESTED.value: frozenset({"id", "name", "arguments_hash"}),
    AgentEventKind.POLICY_DECIDED.value: frozenset(
        {"id", "name", "arguments_hash", "risk_classes", "matched_rule_id", "action", "reason_code"}
    ),
    AgentEventKind.TOOL_CALL_COMPLETED.value: frozenset(
        {"id", "name", "arguments_hash", "output_hash", "output_size", "status"}
    ),
    AgentEventKind.TOOL_PROGRESS.value: frozenset({"id", "name", "status", "offset", "total"}),
    AgentEventKind.APPROVAL_REQUIRED.value: frozenset(
        {"id", "name", "arguments_hash", "risk_classes", "matched_rule_id"}
    ),
    AgentEventKind.APPROVAL_DECIDED.value: frozenset(
        {"id", "name", "arguments_hash", "approved", "reason_code"}
    ),
    AgentEventKind.TOOL_DENIED.value: frozenset(
        {"id", "name", "arguments_hash", "action", "reason_code", "status"}
    ),
    AgentEventKind.RUN_STOPPED.value: frozenset({"reason", "error"}),
}


class LedgerDataError(RuntimeError):
    """Stored ledger data is malformed or uses an unsupported schema."""


def _bounded_page(limit: int, position: int) -> tuple[int, int]:
    if not 1 <= limit <= _MAX_PAGE or position < 0:
        raise ValueError("pagination is outside supported bounds")
    return limit, position


def safe_event_payload(
    kind: str, payload: Mapping[str, Any], redactor: PersistenceRedactor
) -> dict[str, Any]:
    """Allow-list replay metadata; never persist text, arguments, results, or chain-of-thought."""
    allowed = _SAFE_FIELDS.get(kind)
    if allowed is None:
        raise ValueError("unsupported runtime event kind")
    projected = {key: payload[key] for key in allowed if key in payload}
    # Persist only the presence of an error. Exception messages can embed prompts,
    # provider responses, credentials, tool arguments, or tool results.
    if "error" in projected:
        projected["error"] = bool(projected["error"])
    safe = redactor.redact_value(projected)
    if not isinstance(safe, dict):
        raise ValueError("event payload must be an object")
    return safe


class RunRepository:
    """Ledger writer and owner-scoped reader. Events intentionally expose append only."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redactor: PersistenceRedactor,
    ) -> None:
        self._sessions = sessions
        self._redactor = redactor

    async def ensure_run(
        self,
        *,
        run_id: str,
        user_id: str,
        project_id: str,
        conversation_id: str,
        correlation_id: str,
        provider: str,
        model: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        values = {
            "run_id": run_id,
            "user_id": user_id,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "correlation_id": correlation_id,
            "provider": provider,
            "model": model,
            "schema_version": SCHEMA_VERSION,
            "status": "running",
            "started_at": now,
            "next_sequence": 1,
        }
        async with self._sessions() as session:
            dialect = session.get_bind().dialect.name
            statement: Any
            if dialect == "postgresql":
                statement = (
                    pg_insert(RunRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[RunRow.run_id])
                )
            elif dialect == "sqlite":
                statement = (
                    sqlite_insert(RunRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[RunRow.run_id])
                )
            else:
                if await session.get(RunRow, run_id) is None:
                    session.add(RunRow(**values))
                await session.commit()
                return
            await session.execute(statement)
            await session.commit()

    async def append(
        self,
        *,
        run_id: str,
        user_id: str,
        project_id: str,
        conversation_id: str,
        correlation_id: str,
        provider: str,
        model: str,
        kind: str,
        iteration: int,
        payload: Mapping[str, Any],
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
    ) -> int:
        await self.ensure_run(
            run_id=run_id,
            user_id=user_id,
            project_id=project_id,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
            provider=provider,
            model=model,
        )
        safe_payload = safe_event_payload(kind, payload, self._redactor)
        encoded = json.dumps(
            safe_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            allocated = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == user_id,
                    RunRow.status == "running",
                    RunRow.completed_at.is_(None),
                )
                .values(next_sequence=RunRow.next_sequence + 1)
                .returning(RunRow.next_sequence)
            )
            next_sequence = allocated.scalar_one_or_none()
            if next_sequence is None:
                await session.rollback()
                owned = await session.scalar(
                    select(RunRow.run_id).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
                )
                if owned is None:
                    raise ValueError("run owner mismatch")
                raise ValueError("run is not running")
            sequence = int(next_sequence) - 1
            session.add(
                RuntimeEventRow(
                    run_id=run_id,
                    user_id=user_id,
                    project_id=project_id,
                    conversation_id=conversation_id,
                    correlation_id=correlation_id,
                    sequence=sequence,
                    event_at=now,
                    kind=kind,
                    schema_version=SCHEMA_VERSION,
                    iteration=iteration,
                    payload=encoded,
                )
            )
            if kind == AgentEventKind.RUN_STOPPED.value:
                reason = safe_payload.get("reason")
                error = safe_payload.get("error")
                started = await session.scalar(
                    select(RunRow.started_at).where(RunRow.run_id == run_id)
                )
                if started is not None and started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
                latency_ms = (now - started).total_seconds() * 1000 if started else None
                finalized = await session.execute(
                    update(RunRow)
                    .where(
                        RunRow.run_id == run_id,
                        RunRow.user_id == user_id,
                        RunRow.status == "running",
                        RunRow.completed_at.is_(None),
                    )
                    .values(
                        status="failed" if error else "completed",
                        completed_at=now,
                        stop_reason=str(reason)[:100] if reason is not None else None,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                        iterations=iteration,
                        latency_ms=latency_ms,
                    )
                )
                if getattr(finalized, "rowcount", 0) != 1:
                    await session.rollback()
                    raise ValueError("run is not running")
            await session.commit()
            return sequence

    async def list(self, user_id: str, *, limit: int = 50, offset: int = 0) -> RunPage:
        limit, offset = _bounded_page(limit, offset)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(RunRow)
                    .where(RunRow.user_id == user_id)
                    .order_by(RunRow.started_at.desc(), RunRow.run_id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        return RunPage(tuple(self._run_record(row) for row in rows), limit, offset)

    async def get(self, user_id: str, run_id: str) -> RunRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RunRow).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
            )
        return self._run_record(row) if row is not None else None

    async def events(
        self, user_id: str, run_id: str, *, limit: int = 100, after_sequence: int = 0
    ) -> EventPage | None:
        limit, after_sequence = _bounded_page(limit, after_sequence)
        async with self._sessions() as session:
            owned = await session.scalar(
                select(RunRow.run_id).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
            )
            if owned is None:
                return None
            rows = (
                await session.scalars(
                    select(RuntimeEventRow)
                    .where(
                        RuntimeEventRow.run_id == run_id,
                        RuntimeEventRow.user_id == user_id,
                        RuntimeEventRow.sequence > after_sequence,
                    )
                    .order_by(RuntimeEventRow.sequence)
                    .limit(limit)
                )
            ).all()
        return EventPage(tuple(self._event_record(row) for row in rows), limit, after_sequence)

    async def prune_completed(self, user_id: str, *, completed_before: datetime) -> int:
        """Delete complete owner runs atomically; active runs and partial trajectories survive."""
        async with self._sessions() as session:
            ids = (
                await session.scalars(
                    select(RunRow.run_id).where(
                        RunRow.user_id == user_id,
                        RunRow.status != "running",
                        RunRow.completed_at < completed_before,
                    )
                )
            ).all()
            if not ids:
                return 0
            await session.execute(
                delete(RuntimeEventRow).where(
                    RuntimeEventRow.user_id == user_id, RuntimeEventRow.run_id.in_(ids)
                )
            )
            await session.execute(
                delete(RunRow).where(RunRow.user_id == user_id, RunRow.run_id.in_(ids))
            )
            await session.commit()
            return len(ids)

    @staticmethod
    def _run_record(row: Any) -> RunRecord:
        if row.schema_version != SCHEMA_VERSION:
            raise LedgerDataError("unsupported run schema version")
        return RunRecord(
            run_id=row.run_id,
            user_id=row.user_id,
            project_id=row.project_id,
            conversation_id=row.conversation_id,
            correlation_id=row.correlation_id,
            provider=row.provider,
            model=row.model,
            schema_version=row.schema_version,
            status=row.status,
            started_at=row.started_at,
            completed_at=row.completed_at,
            stop_reason=row.stop_reason,
            answer_summary=row.answer_summary,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            total_tokens=row.total_tokens,
            cost_usd=row.cost_usd,
            latency_ms=row.latency_ms,
            iterations=row.iterations,
            parent_run_id=row.parent_run_id,
            fork_source_sequence=row.fork_source_sequence,
        )

    @staticmethod
    def _event_record(row: Any) -> RunEventRecord:
        if row.schema_version != SCHEMA_VERSION or row.kind not in _SAFE_FIELDS:
            raise LedgerDataError("unsupported event schema")
        try:
            payload = json.loads(row.payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LedgerDataError("malformed event payload") from exc
        if not isinstance(payload, dict) or any(
            key not in _SAFE_FIELDS[row.kind] for key in payload
        ):
            raise LedgerDataError("malformed event payload")
        return RunEventRecord(
            run_id=row.run_id,
            project_id=row.project_id,
            conversation_id=row.conversation_id,
            correlation_id=row.correlation_id,
            sequence=row.sequence,
            event_at=row.event_at,
            kind=row.kind,
            schema_version=row.schema_version,
            iteration=row.iteration,
            payload=payload,
        )
