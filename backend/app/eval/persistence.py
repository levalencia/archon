"""Typed, owner-scoped persistence for privacy-safe evaluation results."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeAlias, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.db_store import EvalCaseResultRow, EvalCohortRevisionRow, EvalRunRow

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
_FORBIDDEN_KEYS = frozenset({"answer", "raw_answer", "events", "raw_events", "event_payload"})


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    id: str
    evaluation_id: str
    source_run_id: str
    case_key: str
    passed: bool
    score: float
    metrics: Mapping[str, JSONValue]
    checks: tuple[Mapping[str, JSONValue], ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    id: str
    owner_id: str
    project_id: str
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    model_revision: str
    provider_revision: str
    config_revision: str
    source_run_ids: tuple[str, ...]
    threshold: float
    status: str
    passed: bool | None
    aggregate_metrics: Mapping[str, JSONValue]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cases: tuple[EvaluationCaseResult, ...] = ()


def _safe_json(value: object, *, field: str) -> JSONValue:
    """Copy JSON data while rejecting non-finite numbers and raw-answer/event keys."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, list | tuple):
        return [_safe_json(item, field=field) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field} keys must be strings")
            if key.lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"{field} must not contain raw answers or events")
            result[key] = _safe_json(item, field=field)
        return result
    raise ValueError(f"{field} must contain JSON values only")


def _object(value: object, *, field: str) -> dict[str, JSONValue]:
    safe = _safe_json(value, field=field)
    if not isinstance(safe, dict):
        raise ValueError(f"{field} must be an object")
    json.dumps(safe, allow_nan=False)
    return safe


class EvaluationRepository:
    """Create and finalize evaluations without ever exposing cross-owner records."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        owner_id: str,
        *,
        project_id: str,
        dataset_id: str,
        dataset_version: str,
        dataset_hash: str,
        source_run_ids: Sequence[str],
        threshold: float,
        model_revision: str = "unknown",
        provider_revision: str = "unknown",
        config_revision: str = "unknown",
    ) -> EvaluationRun:
        if not owner_id or not project_id or not dataset_id or not dataset_version:
            raise ValueError("evaluation scope and dataset identity are required")
        if len(dataset_hash) != 64 or any(char not in "0123456789abcdef" for char in dataset_hash):
            raise ValueError("dataset_hash must be a lowercase SHA-256 digest")
        run_ids = tuple(source_run_ids)
        if not run_ids or len(set(run_ids)) != len(run_ids) or any(not item for item in run_ids):
            raise ValueError("source_run_ids must be non-empty and unique")
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("threshold must be finite and between zero and one")
        revisions = (model_revision, provider_revision, config_revision)
        if any(
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 255
            or any(ord(character) < 32 for character in value)
            for value in revisions
        ):
            raise ValueError("model, provider, and config revisions must be bounded identifiers")
        now = datetime.now(tz=UTC)
        row = EvalRunRow(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_hash=dataset_hash,
            source_run_ids_json=list(run_ids),
            threshold=threshold,
            status="running",
            passed=None,
            aggregate_metrics_json={},
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        async with self._sessions() as session:
            session.add(row)
            await session.flush()
            session.add(
                EvalCohortRevisionRow(
                    eval_run_id=row.id,
                    model_revision=model_revision,
                    provider_revision=provider_revision,
                    config_revision=config_revision,
                    created_at=now,
                )
            )
            await session.commit()
        return self._run_model(row, (), (model_revision, provider_revision, config_revision))

    async def append_case(
        self,
        owner_id: str,
        evaluation_id: str,
        *,
        source_run_id: str,
        case_key: str,
        passed: bool,
        score: float,
        metrics: Mapping[str, object],
        checks: Sequence[Mapping[str, object]],
    ) -> EvaluationCaseResult:
        if not source_run_id or not case_key:
            raise ValueError("source_run_id and case_key are required")
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("score must be finite and between zero and one")
        safe_metrics = _object(metrics, field="metrics")
        safe_checks = [_object(check, field="checks") for check in checks]
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            parent = await session.scalar(
                select(EvalRunRow).where(
                    EvalRunRow.id == evaluation_id,
                    EvalRunRow.owner_id == owner_id,
                    EvalRunRow.status == "running",
                )
            )
            if parent is None:
                raise ValueError("running evaluation not found")
            if source_run_id not in cast(list[str], parent.source_run_ids_json):
                raise ValueError("source run is not part of the evaluation")
            row = EvalCaseResultRow(
                id=str(uuid.uuid4()),
                eval_run_id=evaluation_id,
                source_run_id=source_run_id,
                case_key=case_key,
                passed=int(passed),
                score=score,
                metrics_json=safe_metrics,
                checks_json=safe_checks,
                created_at=now,
            )
            session.add(row)
            await session.commit()
        return self._case_model(row)

    async def finalize(
        self,
        owner_id: str,
        evaluation_id: str,
        *,
        status: str,
        passed: bool | None,
        aggregate_metrics: Mapping[str, object],
    ) -> EvaluationRun:
        if status not in {"completed", "failed"}:
            raise ValueError("final status must be completed or failed")
        if status == "completed" and passed is None:
            raise ValueError("completed evaluations require a pass result")
        if status == "failed" and passed is not None:
            raise ValueError("failed evaluations cannot have a pass result")
        safe_metrics = _object(aggregate_metrics, field="aggregate_metrics")
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(EvalRunRow)
                    .where(
                        EvalRunRow.id == evaluation_id,
                        EvalRunRow.owner_id == owner_id,
                        EvalRunRow.status == "running",
                    )
                    .values(
                        status=status,
                        passed=None if passed is None else int(passed),
                        aggregate_metrics_json=safe_metrics,
                        updated_at=now,
                        completed_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                await session.rollback()
                raise ValueError("running evaluation not found")
            await session.commit()
        found = await self.get(owner_id, evaluation_id)
        if found is None:  # pragma: no cover
            raise RuntimeError("finalized evaluation disappeared")
        return found

    async def get(self, owner_id: str, evaluation_id: str) -> EvaluationRun | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(EvalRunRow).where(
                    EvalRunRow.id == evaluation_id, EvalRunRow.owner_id == owner_id
                )
            )
            if row is None:
                return None
            revision = await session.get(EvalCohortRevisionRow, evaluation_id)
            case_rows = (
                await session.scalars(
                    select(EvalCaseResultRow)
                    .where(EvalCaseResultRow.eval_run_id == evaluation_id)
                    .order_by(EvalCaseResultRow.created_at, EvalCaseResultRow.id)
                )
            ).all()
        revision_identity = (
            ("unknown", "unknown", "unknown")
            if revision is None
            else (
                str(revision.model_revision),
                str(revision.provider_revision),
                str(revision.config_revision),
            )
        )
        return self._run_model(
            row,
            tuple(self._case_model(item) for item in case_rows),
            revision_identity,
        )

    async def list(
        self,
        owner_id: str,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[EvaluationRun, ...]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("pagination is outside supported bounds")
        statement = select(EvalRunRow).where(EvalRunRow.owner_id == owner_id)
        if project_id is not None:
            statement = statement.where(EvalRunRow.project_id == project_id)
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    statement.order_by(EvalRunRow.created_at.desc(), EvalRunRow.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            revisions = (
                await session.scalars(
                    select(EvalCohortRevisionRow).where(
                        EvalCohortRevisionRow.eval_run_id.in_([str(row.id) for row in rows])
                    )
                )
            ).all()
        by_eval = {
            str(item.eval_run_id): (
                str(item.model_revision),
                str(item.provider_revision),
                str(item.config_revision),
            )
            for item in revisions
        }
        return tuple(
            self._run_model(row, (), by_eval.get(str(row.id), ("unknown", "unknown", "unknown")))
            for row in rows
        )

    @staticmethod
    def _case_model(row: EvalCaseResultRow) -> EvaluationCaseResult:
        return EvaluationCaseResult(
            id=str(row.id),
            evaluation_id=str(row.eval_run_id),
            source_run_id=str(row.source_run_id),
            case_key=str(row.case_key),
            passed=bool(row.passed),
            score=float(row.score),
            metrics=cast(dict[str, JSONValue], row.metrics_json),
            checks=tuple(cast(list[dict[str, JSONValue]], row.checks_json)),
            created_at=cast(datetime, row.created_at),
        )

    @staticmethod
    def _run_model(
        row: EvalRunRow,
        cases: tuple[EvaluationCaseResult, ...],
        revision: tuple[str, str, str] = ("unknown", "unknown", "unknown"),
    ) -> EvaluationRun:
        return EvaluationRun(
            id=str(row.id),
            owner_id=str(row.owner_id),
            project_id=str(row.project_id),
            dataset_id=str(row.dataset_id),
            dataset_version=str(row.dataset_version),
            dataset_hash=str(row.dataset_hash),
            model_revision=revision[0],
            provider_revision=revision[1],
            config_revision=revision[2],
            source_run_ids=tuple(cast(list[str], row.source_run_ids_json)),
            threshold=float(row.threshold),
            status=str(row.status),
            passed=None if row.passed is None else bool(row.passed),
            aggregate_metrics=cast(dict[str, JSONValue], row.aggregate_metrics_json),
            created_at=cast(datetime, row.created_at),
            updated_at=cast(datetime, row.updated_at),
            completed_at=cast(datetime | None, row.completed_at),
            cases=cases,
        )
