"""Owner-scoped append-only run ledger repository."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.events import AgentEventKind
from app.runtime.run_models import EventPage, RunEventRecord, RunPage, RunRecord
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import (
    ConversationRow,
    ForkDraftRow,
    MessageRow,
    RunCheckpointRow,
    RunRow,
    RuntimeEventRow,
)

SCHEMA_VERSION = 1
_MAX_PAGE = 200
_TERMINAL_RUN_STATUSES = ("completed", "failed", "cancelled")
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
    AgentEventKind.EVIDENCE_RETRIEVED.value: frozenset(
        {"evidence_ids", "document_ids", "chunk_ids", "content_hashes", "scores", "evidence_count"}
    ),
    AgentEventKind.CLAIM_VERIFIED.value: frozenset(
        {
            "claim_hashes",
            "unsupported_hashes",
            "cited_evidence_ids",
            "supported_count",
            "unsupported_count",
        }
    ),
    AgentEventKind.GROUNDED_ANSWER.value: frozenset(
        {"answer_hash", "citation_ids", "supported_count", "unsupported_count"}
    ),
    AgentEventKind.DELEGATION_REQUESTED.value: frozenset(
        {
            "child_id",
            "parent_run_id",
            "user_id",
            "project_id",
            "policy_id",
            "claim_ids",
            "claim_hashes",
            "evidence_ids",
            "content_hashes",
            "claim_count",
            "evidence_count",
            "status",
            "reason_code",
            "input_tokens",
            "output_tokens",
        }
    ),
    AgentEventKind.DELEGATION_COMPLETED.value: frozenset(
        {
            "child_id",
            "parent_run_id",
            "claim_ids",
            "claim_hashes",
            "evidence_ids",
            "content_hashes",
            "claim_count",
            "evidence_count",
            "supported_count",
            "rejected_count",
            "escalated_count",
            "status",
            "reason_code",
            "reason_codes",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }
    ),
    AgentEventKind.RUN_STOPPED.value: frozenset({"reason", "error"}),
}


class LedgerDataError(RuntimeError):
    """Stored ledger data is malformed or uses an unsupported schema."""


def _terminal_run_filters() -> tuple[Any, Any]:
    """Return the canonical definition of a safely pruneable run."""
    return (
        RunRow.status.in_(_TERMINAL_RUN_STATUSES),
        RunRow.completed_at.is_not(None),
    )


async def _delete_terminal_runs(
    session: AsyncSession, run_ids: list[str], *, user_id: str | None = None
) -> int:
    """Delete complete trajectories only, with events removed before their parent runs."""
    if not run_ids:
        return 0
    run_query = select(RunRow.run_id).where(RunRow.run_id.in_(run_ids), *_terminal_run_filters())
    if user_id is not None:
        run_query = run_query.where(RunRow.user_id == user_id)
    eligible_ids = run_query.scalar_subquery()
    await session.execute(
        delete(RuntimeEventRow)
        .where(RuntimeEventRow.run_id.in_(eligible_ids))
        .execution_options(synchronize_session=False)
    )
    deleted = await session.execute(
        delete(RunRow)
        .where(RunRow.run_id.in_(eligible_ids))
        .execution_options(synchronize_session=False)
    )
    return int(getattr(deleted, "rowcount", 0))


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
                    .returning(RunRow.run_id)
                )
            elif dialect == "sqlite":
                statement = (
                    sqlite_insert(RunRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[RunRow.run_id])
                    .returning(RunRow.run_id)
                )
            else:
                existing = await session.get(RunRow, run_id)
                if existing is not None:
                    return
                session.add(RunRow(**values))
                await session.flush()
                inserted_run_id: str | None = run_id
            if dialect in {"postgresql", "sqlite"}:
                inserted_run_id = (await session.execute(statement)).scalar_one_or_none()
            if inserted_run_id is None:
                await session.commit()
                return

            # Only the transaction that creates the first run for this draft may consume it.
            # DELETE ... RETURNING makes distinct child runs race for exactly one lineage record,
            # while repeated ensure calls for an existing run leave any unrelated draft untouched.
            consumed = (
                await session.execute(
                    delete(ForkDraftRow)
                    .where(
                        ForkDraftRow.user_id == user_id,
                        ForkDraftRow.project_id == project_id,
                        ForkDraftRow.target_conversation_id == conversation_id,
                    )
                    .returning(ForkDraftRow.source_run_id, ForkDraftRow.source_sequence)
                )
            ).one_or_none()
            if consumed is not None:
                await session.execute(
                    update(RunRow)
                    .where(RunRow.run_id == run_id, RunRow.user_id == user_id)
                    .values(parent_run_id=consumed[0], fork_source_sequence=consumed[1])
                )
            await session.commit()

    async def ensure_child_run(
        self,
        *,
        run_id: str,
        parent_run_id: str,
        user_id: str,
        project_id: str,
        provider: str,
        model: str,
    ) -> None:
        """Create a child with explicit, immutable owner-scoped lineage."""
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            parent = await session.scalar(select(RunRow).where(RunRow.run_id == parent_run_id))
            if parent is not None and (
                str(parent.user_id) != user_id or str(parent.project_id) != project_id
            ):
                raise ValueError("parent run owner mismatch")
            existing = await session.scalar(select(RunRow).where(RunRow.run_id == run_id))
            if existing is not None:
                if (
                    str(existing.user_id) != user_id
                    or str(existing.project_id) != project_id
                    or str(existing.parent_run_id) != parent_run_id
                ):
                    raise ValueError("child run identity mismatch")
                return
            session.add(
                RunRow(
                    run_id=run_id,
                    parent_run_id=parent_run_id,
                    user_id=user_id,
                    project_id=project_id,
                    conversation_id=parent_run_id,
                    correlation_id=run_id,
                    provider=provider,
                    model=model,
                    schema_version=SCHEMA_VERSION,
                    status="running",
                    started_at=now,
                    next_sequence=1,
                )
            )
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
                        status=(
                            "cancelled"
                            if reason == "cancelled"
                            else "failed"
                            if error
                            else "completed"
                        ),
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

    async def list(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        conversation_id: str | None = None,
        project_id: str | None = None,
    ) -> RunPage:
        limit, offset = _bounded_page(limit, offset)
        async with self._sessions() as session:
            query = select(RunRow).where(RunRow.user_id == user_id)
            if conversation_id is not None:
                query = query.where(RunRow.conversation_id == conversation_id)
            if project_id is not None:
                query = query.where(RunRow.project_id == project_id)
            rows = (
                await session.scalars(
                    query.order_by(RunRow.started_at.desc(), RunRow.run_id.desc())
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

    async def finalize_metadata(
        self,
        user_id: str,
        run_id: str,
        *,
        answer: str,
        cost_usd: float | None = None,
        latency_ms: float | None = None,
    ) -> None:
        """Persist bounded redacted display metadata after either sync or SSE completion."""
        summary = self._redactor.redact_text(answer).text[:2000]
        values: dict[str, Any] = {"answer_summary": summary}
        if cost_usd is not None and cost_usd >= 0:
            values["cost_usd"] = float(cost_usd)
        if latency_ms is not None and latency_ms >= 0:
            values["latency_ms"] = float(latency_ms)
        async with self._sessions() as session:
            changed = await session.execute(
                update(RunRow)
                .where(RunRow.run_id == run_id, RunRow.user_id == user_id)
                .values(**values)
            )
            if getattr(changed, "rowcount", 0) != 1:
                raise ValueError("run not found")
            await session.commit()

    async def fork(
        self,
        user_id: str,
        run_id: str,
        source_sequence: int,
        *,
        policy_profile: str = "default",
        selected_memory_ids: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        """Atomically checkpoint stored safe conversation data and create a fork draft."""
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            run = await session.scalar(
                select(RunRow).where(RunRow.run_id == run_id, RunRow.user_id == user_id)
            )
            if run is None:
                return None
            event = await session.scalar(
                select(RuntimeEventRow).where(
                    RuntimeEventRow.run_id == run_id,
                    RuntimeEventRow.user_id == user_id,
                    RuntimeEventRow.sequence == source_sequence,
                )
            )
            if event is None:
                raise ValueError("source sequence not found")
            conversation = await session.scalar(
                select(ConversationRow).where(
                    ConversationRow.id == run.conversation_id,
                    ConversationRow.user_id == user_id,
                )
            )
            if conversation is None:
                raise ValueError("source conversation not found")
            cutoff = (
                run.completed_at
                if event.kind == AgentEventKind.RUN_STOPPED.value
                else event.event_at
            )
            if cutoff is None:
                raise ValueError("terminal run has no completion timestamp")
            messages = (
                await session.scalars(
                    select(MessageRow)
                    .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
                    .where(
                        MessageRow.conversation_id == run.conversation_id,
                        ConversationRow.user_id == user_id,
                        MessageRow.created_at <= cutoff,
                    )
                    .order_by(MessageRow.created_at, MessageRow.id)
                )
            ).all()
            snapshot_items = [
                {
                    "role": str(item.role),
                    "content": self._redactor.redact_text(str(item.content)).text[:10000],
                }
                for item in messages
            ]
            snapshot = json.dumps(snapshot_items, ensure_ascii=False, separators=(",", ":"))
            checkpoint_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"archon:checkpoint:{user_id}:{run_id}:{source_sequence}",
                )
            )
            checkpoint_values = {
                "checkpoint_id": checkpoint_id,
                "user_id": user_id,
                "project_id": run.project_id,
                "source_run_id": run_id,
                "source_sequence": source_sequence,
                "conversation_snapshot": snapshot,
                "policy_profile": policy_profile[:100],
                "selected_memory_ids": json.dumps(list(selected_memory_ids)),
                "workspace_restoration": "none",
                "created_at": now,
            }
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                checkpoint_insert: Any = (
                    pg_insert(RunCheckpointRow)
                    .values(**checkpoint_values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            RunCheckpointRow.user_id,
                            RunCheckpointRow.source_run_id,
                            RunCheckpointRow.source_sequence,
                        ]
                    )
                )
            elif dialect == "sqlite":
                checkpoint_insert = (
                    sqlite_insert(RunCheckpointRow)
                    .values(**checkpoint_values)
                    .on_conflict_do_nothing(
                        index_elements=[
                            RunCheckpointRow.user_id,
                            RunCheckpointRow.source_run_id,
                            RunCheckpointRow.source_sequence,
                        ]
                    )
                )
            else:
                existing_checkpoint = await session.scalar(
                    select(RunCheckpointRow).where(
                        RunCheckpointRow.user_id == user_id,
                        RunCheckpointRow.source_run_id == run_id,
                        RunCheckpointRow.source_sequence == source_sequence,
                    )
                )
                if existing_checkpoint is None:
                    session.add(RunCheckpointRow(**checkpoint_values))
            if dialect in {"postgresql", "sqlite"}:
                await session.execute(checkpoint_insert)
            checkpoint = await session.scalar(
                select(RunCheckpointRow).where(
                    RunCheckpointRow.user_id == user_id,
                    RunCheckpointRow.source_run_id == run_id,
                    RunCheckpointRow.source_sequence == source_sequence,
                )
            )
            if checkpoint is None:
                raise RuntimeError("checkpoint insert failed")
            checkpoint_id = str(checkpoint.checkpoint_id)
            snapshot_items = json.loads(str(checkpoint.conversation_snapshot))
            checkpoint_policy_profile = str(checkpoint.policy_profile)
            checkpoint_memory_ids = json.loads(str(checkpoint.selected_memory_ids))
            checkpoint_created_at = checkpoint.created_at
            target_id = str(uuid.uuid4())
            session.add(
                ConversationRow(
                    id=target_id,
                    title=f"Fork: {conversation.title}"[:200],
                    user_id=user_id,
                    created_at=now,
                    updated_at=now,
                    is_active=1,
                )
            )
            for item in snapshot_items:
                session.add(
                    MessageRow(
                        conversation_id=target_id,
                        role=item["role"],
                        content=item["content"],
                        created_at=now,
                    )
                )
            session.add(
                ForkDraftRow(
                    id=str(uuid.uuid4()),
                    checkpoint_id=checkpoint_id,
                    user_id=user_id,
                    project_id=run.project_id,
                    source_run_id=run_id,
                    source_sequence=source_sequence,
                    target_conversation_id=target_id,
                    created_at=now,
                )
            )
            await session.commit()
        return {
            "checkpoint_id": checkpoint_id,
            "source_run_id": run_id,
            "source_sequence": source_sequence,
            "target_conversation_id": target_id,
            "workspace_restoration": "none",
            "policy_profile": checkpoint_policy_profile,
            "selected_memory_ids": checkpoint_memory_ids,
            "created_at": checkpoint_created_at,
        }

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
                    select(RunRow.run_id)
                    .where(
                        RunRow.user_id == user_id,
                        *_terminal_run_filters(),
                        RunRow.completed_at < completed_before,
                    )
                    .with_for_update()
                )
            ).all()
            if not ids:
                return 0
            deleted = await _delete_terminal_runs(session, list(ids), user_id=user_id)
            await session.commit()
            return deleted

    async def prune_terminal_to_event_budget(self, max_events: int) -> int:
        """Prune oldest whole terminal runs until the global event budget is met.

        Active runs may temporarily take the ledger over budget. This compatibility
        retention path never truncates a run or treats an inconsistent row with a
        missing completion timestamp as safe to delete.
        """
        if max_events < 0:
            raise ValueError("max_events must be non-negative")
        async with self._sessions() as session:
            event_total = int(await session.scalar(select(func.count(RuntimeEventRow.id))) or 0)
            if event_total <= max_events:
                return 0
            event_count = (
                select(func.count(RuntimeEventRow.id))
                .where(RuntimeEventRow.run_id == RunRow.run_id)
                .correlate(RunRow)
                .scalar_subquery()
            )
            candidates = (
                await session.execute(
                    select(RunRow.run_id, event_count)
                    .where(*_terminal_run_filters())
                    .order_by(RunRow.completed_at, RunRow.run_id)
                    .with_for_update()
                )
            ).all()
            stale: list[str] = []
            removed_events = 0
            for run_id, count in candidates:
                stale.append(str(run_id))
                removed_events += int(count)
                if event_total - removed_events <= max_events:
                    break
            if not stale:
                return 0
            deleted = await _delete_terminal_runs(session, stale)
            await session.commit()
            return deleted

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
