"""Durable optimization recommendations with exact human approval and no activation side effect."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.eval.persistence import JSONValue, _safe_json
from app.security.approval_repository import ApprovalRepository, ApprovalStatus
from app.security.persistence_redactor import PersistenceRedactor
from app.security.pii_detector import PIIDetector
from app.security.policy import RiskClass
from app.services.db_store import (
    ApprovalRequestRow,
    EvalDriftReportRow,
    EvalRunRow,
    OptimizationCandidateEventRow,
    OptimizationCandidateRow,
)

_PURPOSE = "optimization_candidate_promotion"
_TOOL = "optimization.promote"
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REDACTOR = PersistenceRedactor(PIIDetector(use_spacy=False))


class CandidateType(StrEnum):
    PROMPT = "prompt"
    POLICY = "policy"
    RETRIEVAL = "retrieval"
    CONFIG = "config"


class CandidateState(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled_back"


class CandidateConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OptimizationCandidate:
    id: str
    owner_id: str
    project_id: str
    candidate_type: CandidateType
    change_summary: str
    proposal_metadata: Mapping[str, JSONValue]
    rollback_plan: str
    target_revision: str
    baseline_eval_id: str
    candidate_eval_id: str
    drift_report_id: str | None
    state: CandidateState
    version: int
    approval_id: str | None
    created_at: datetime
    updated_at: datetime
    promoted_at: datetime | None
    rolled_back_at: datetime | None


def _bounded_text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{field} must be non-empty, trimmed, and at most {maximum} characters")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field} contains control characters")
    if _REDACTOR.redact_text(value).text != value:
        raise ValueError(f"{field} contains sensitive data")
    return value


_ALLOWED_METADATA_KEYS: dict[CandidateType, frozenset[str]] = {
    CandidateType.PROMPT: frozenset({"template_revision", "change_tags"}),
    CandidateType.POLICY: frozenset({"policy_revision", "rule_ids"}),
    CandidateType.RETRIEVAL: frozenset({"retriever_revision", "index_revision", "top_k"}),
    CandidateType.CONFIG: frozenset({"component", "revision_hash", "parameter_names"}),
}


def _metadata(value: Mapping[str, object], kind: CandidateType) -> dict[str, JSONValue]:
    safe = _safe_json(value, field="proposal_metadata")
    if not isinstance(safe, dict):
        raise ValueError("proposal_metadata must be an object")
    allowed = _ALLOWED_METADATA_KEYS[kind]
    if not set(safe).issubset(allowed):
        raise ValueError(f"proposal_metadata keys are not allowed for {kind.value} candidates")
    if len(safe) > 10:
        raise ValueError("proposal_metadata objects are bounded to 10 keys")
    for item in safe.values():
        values = item if isinstance(item, list) else [item]
        if isinstance(item, dict) or len(values) > 20:
            raise ValueError("proposal_metadata values must be bounded scalar lists")
        for child in values:
            if isinstance(child, dict | list) or (
                isinstance(child, str)
                and (len(child) > 255 or any(ord(character) < 32 for character in child))
            ):
                raise ValueError("proposal_metadata values must be bounded scalars")
    if _REDACTOR.redact_value(safe) != safe:
        raise ValueError("proposal_metadata contains sensitive data")
    encoded = json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > 4_096:
        raise ValueError("proposal_metadata exceeds 4096 bytes")
    return safe


def approval_arguments_hash(candidate: OptimizationCandidate, version: int) -> str:
    payload = {
        "purpose": _PURPOSE,
        "owner_id": candidate.owner_id,
        "project_id": candidate.project_id,
        "candidate_id": candidate.id,
        "candidate_version": version,
        "target_revision": candidate.target_revision,
        "baseline_eval_id": candidate.baseline_eval_id,
        "candidate_eval_id": candidate.candidate_eval_id,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class OptimizationCandidateService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], approvals: ApprovalRepository
    ) -> None:
        self._sessions, self._approvals = sessions, approvals

    @staticmethod
    async def _begin_write_fence(session: AsyncSession) -> None:
        bind = session.get_bind()
        if bind.dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))

    async def create(
        self,
        owner_id: str,
        *,
        project_id: str,
        candidate_type: CandidateType | str,
        change_summary: str,
        proposal_metadata: Mapping[str, object],
        rollback_plan: str,
        target_revision: str,
        baseline_eval_id: str,
        candidate_eval_id: str,
        drift_report_id: str | None = None,
    ) -> OptimizationCandidate:
        kind = CandidateType(candidate_type)
        summary = _bounded_text(change_summary, "change_summary", 1000)
        rollback = _bounded_text(rollback_plan, "rollback_plan", 2000)
        target = _bounded_text(target_revision, "target_revision", 255)
        metadata = _metadata(proposal_metadata, kind)
        now, candidate_id = datetime.now(tz=UTC), str(uuid.uuid4())
        async with self._sessions() as session:
            evaluations = (
                await session.scalars(
                    select(EvalRunRow).where(
                        EvalRunRow.id.in_((baseline_eval_id, candidate_eval_id)),
                        EvalRunRow.owner_id == owner_id,
                        EvalRunRow.project_id == project_id,
                        EvalRunRow.status == "completed",
                    )
                )
            ).all()
            if len(evaluations) != 2 or baseline_eval_id == candidate_eval_id:
                raise LookupError("evaluation evidence not found")
            if drift_report_id is not None:
                report = await session.scalar(
                    select(EvalDriftReportRow).where(
                        EvalDriftReportRow.id == drift_report_id,
                        EvalDriftReportRow.owner_id == owner_id,
                        EvalDriftReportRow.project_id == project_id,
                        EvalDriftReportRow.baseline_eval_id == baseline_eval_id,
                        EvalDriftReportRow.candidate_eval_id == candidate_eval_id,
                    )
                )
                if report is None:
                    raise LookupError("drift evidence not found")
            row = OptimizationCandidateRow(
                id=candidate_id,
                owner_id=owner_id,
                project_id=project_id,
                candidate_type=kind.value,
                change_summary=summary,
                proposal_metadata_json=metadata,
                rollback_plan=rollback,
                target_revision=target,
                baseline_eval_id=baseline_eval_id,
                candidate_eval_id=candidate_eval_id,
                drift_report_id=drift_report_id,
                state=CandidateState.PROPOSED.value,
                version=1,
                approval_id=None,
                created_at=now,
                updated_at=now,
                promoted_at=None,
                rolled_back_at=None,
            )
            session.add(row)
            await session.flush()
            self._event(session, row, None, CandidateState.PROPOSED, None, None)
            await session.commit()
            return self._model(row)

    async def get(
        self, owner_id: str, candidate_id: str, *, project_id: str | None = None
    ) -> OptimizationCandidate | None:
        query = select(OptimizationCandidateRow).where(
            OptimizationCandidateRow.id == candidate_id,
            OptimizationCandidateRow.owner_id == owner_id,
        )
        if project_id is not None:
            query = query.where(OptimizationCandidateRow.project_id == project_id)
        async with self._sessions() as session:
            row = await session.scalar(query)
        return None if row is None else self._model(row)

    async def list(
        self, owner_id: str, *, project_id: str, limit: int = 50
    ) -> tuple[OptimizationCandidate, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("limit is outside supported bounds")
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(OptimizationCandidateRow)
                    .where(
                        OptimizationCandidateRow.owner_id == owner_id,
                        OptimizationCandidateRow.project_id == project_id,
                    )
                    .order_by(OptimizationCandidateRow.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return tuple(self._model(row) for row in rows)

    async def request_approval(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        ttl: timedelta = timedelta(minutes=15),
    ) -> tuple[str, str]:
        tool_call_id = str(uuid.uuid4())
        async with self._sessions() as session:
            await self._begin_write_fence(session)
            row = await session.scalar(
                select(OptimizationCandidateRow)
                .where(
                    OptimizationCandidateRow.id == candidate_id,
                    OptimizationCandidateRow.owner_id == owner_id,
                    OptimizationCandidateRow.project_id == project_id,
                    OptimizationCandidateRow.state == CandidateState.PROPOSED.value,
                    OptimizationCandidateRow.version == expected_version,
                )
                .with_for_update()
            )
            if row is None:
                raise CandidateConflictError("candidate state or version changed")
            candidate = self._model(row)
            receipt = await self._approvals.reserve_in_session(
                session,
                user_id=owner_id,
                conversation_id=project_id,
                run_id=candidate.id,
                tool_call_id=tool_call_id,
                tool_name=_TOOL,
                arguments_hash=approval_arguments_hash(candidate, expected_version),
                risk_classes=(RiskClass.WRITE,),
                matched_rule_id="optimization_human_approval",
                ttl=ttl,
            )
            await session.commit()
        return receipt.id, tool_call_id

    async def approve(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        approval_id: str,
    ) -> OptimizationCandidate:
        return await self._approved_transition(
            owner_id,
            candidate_id,
            project_id=project_id,
            expected_version=expected_version,
            approval_id=approval_id,
        )

    async def promote(
        self, owner_id: str, candidate_id: str, *, project_id: str, expected_version: int
    ) -> OptimizationCandidate:
        # This records the declared target revision only. It does not mutate runtime config.
        return await self._transition(
            owner_id,
            candidate_id,
            project_id=project_id,
            expected_version=expected_version,
            source=CandidateState.APPROVED,
            target=CandidateState.PROMOTED,
        )

    async def reject(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        reason_code: str,
    ) -> OptimizationCandidate:
        if not _REASON.fullmatch(reason_code):
            raise ValueError("reason_code must be a sanitized identifier")
        return await self._transition(
            owner_id,
            candidate_id,
            project_id=project_id,
            expected_version=expected_version,
            source=(CandidateState.PROPOSED, CandidateState.APPROVED),
            target=CandidateState.REJECTED,
            reason_code=reason_code,
        )

    async def rollback(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        reason_code: str,
    ) -> OptimizationCandidate:
        if not _REASON.fullmatch(reason_code):
            raise ValueError("reason_code must be a sanitized identifier")
        return await self._transition(
            owner_id,
            candidate_id,
            project_id=project_id,
            expected_version=expected_version,
            source=CandidateState.PROMOTED,
            target=CandidateState.ROLLED_BACK,
            reason_code=reason_code,
        )

    async def _approved_transition(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        approval_id: str,
    ) -> OptimizationCandidate:
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            await self._begin_write_fence(session)
            row = await session.scalar(
                select(OptimizationCandidateRow)
                .where(
                    OptimizationCandidateRow.id == candidate_id,
                    OptimizationCandidateRow.owner_id == owner_id,
                    OptimizationCandidateRow.project_id == project_id,
                    OptimizationCandidateRow.state == CandidateState.PROPOSED.value,
                    OptimizationCandidateRow.version == expected_version,
                )
                .with_for_update()
            )
            if row is None:
                raise CandidateConflictError("candidate state or version changed")
            candidate = self._model(row)
            approval = await session.scalar(
                select(ApprovalRequestRow).where(
                    ApprovalRequestRow.id == approval_id,
                    ApprovalRequestRow.user_id == owner_id,
                    ApprovalRequestRow.conversation_id == project_id,
                    ApprovalRequestRow.run_id == candidate_id,
                    ApprovalRequestRow.tool_name == _TOOL,
                    ApprovalRequestRow.arguments_hash
                    == approval_arguments_hash(candidate, expected_version),
                    ApprovalRequestRow.status == ApprovalStatus.APPROVED.value,
                    ApprovalRequestRow.expires_at > now,
                )
            )
            if approval is None:
                raise CandidateConflictError("exact approved receipt not found")
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(OptimizationCandidateRow)
                    .where(
                        OptimizationCandidateRow.id == candidate_id,
                        OptimizationCandidateRow.owner_id == owner_id,
                        OptimizationCandidateRow.project_id == project_id,
                        OptimizationCandidateRow.state == CandidateState.PROPOSED.value,
                        OptimizationCandidateRow.version == expected_version,
                        OptimizationCandidateRow.approval_id.is_(None),
                    )
                    .values(
                        state=CandidateState.APPROVED.value,
                        version=expected_version + 1,
                        approval_id=approval_id,
                        updated_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                await session.rollback()
                raise CandidateConflictError("candidate transition lost race")
            row.state, row.version, row.approval_id, row.updated_at = (
                CandidateState.APPROVED.value,
                expected_version + 1,
                approval_id,
                now,
            )
            await session.execute(
                update(ApprovalRequestRow)
                .where(
                    ApprovalRequestRow.id != approval_id,
                    ApprovalRequestRow.user_id == owner_id,
                    ApprovalRequestRow.conversation_id == project_id,
                    ApprovalRequestRow.run_id == candidate_id,
                    ApprovalRequestRow.tool_name == _TOOL,
                    ApprovalRequestRow.arguments_hash
                    == approval_arguments_hash(candidate, expected_version),
                    ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                )
                .values(
                    status=ApprovalStatus.CANCELLED.value,
                    decision_reason="candidate_approved_elsewhere",
                    decided_at=now,
                )
            )
            self._event(
                session, row, CandidateState.PROPOSED, CandidateState.APPROVED, approval_id, None
            )
            await session.commit()
        found = await self.get(owner_id, candidate_id, project_id=project_id)
        assert found is not None
        return found

    async def _transition(
        self,
        owner_id: str,
        candidate_id: str,
        *,
        project_id: str,
        expected_version: int,
        source: CandidateState | tuple[CandidateState, ...],
        target: CandidateState,
        reason_code: str | None = None,
    ) -> OptimizationCandidate:
        allowed = (source,) if isinstance(source, CandidateState) else source
        now = datetime.now(tz=UTC)
        values: dict[str, object] = {
            "state": target.value,
            "version": expected_version + 1,
            "updated_at": now,
        }
        if target is CandidateState.PROMOTED:
            values["promoted_at"] = now
        if target is CandidateState.ROLLED_BACK:
            values["rolled_back_at"] = now
        async with self._sessions() as session:
            await self._begin_write_fence(session)
            row = await session.scalar(
                select(OptimizationCandidateRow)
                .where(
                    OptimizationCandidateRow.id == candidate_id,
                    OptimizationCandidateRow.owner_id == owner_id,
                    OptimizationCandidateRow.project_id == project_id,
                    OptimizationCandidateRow.state.in_([item.value for item in allowed]),
                    OptimizationCandidateRow.version == expected_version,
                )
                .with_for_update()
            )
            if row is None:
                raise CandidateConflictError("candidate state or version changed")
            if target is CandidateState.PROMOTED and row.approval_id is None:
                raise CandidateConflictError("promotion requires an exact approval")
            previous = CandidateState(str(row.state))
            if target is CandidateState.REJECTED:
                await session.execute(
                    update(ApprovalRequestRow)
                    .where(
                        ApprovalRequestRow.user_id == owner_id,
                        ApprovalRequestRow.conversation_id == project_id,
                        ApprovalRequestRow.run_id == candidate_id,
                        ApprovalRequestRow.tool_name == _TOOL,
                        ApprovalRequestRow.arguments_hash
                        == approval_arguments_hash(self._model(row), expected_version),
                        ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                    )
                    .values(
                        status=ApprovalStatus.CANCELLED.value,
                        decision_reason="candidate_rejected",
                        decided_at=now,
                    )
                )
            result = cast(
                CursorResult[object],
                await session.execute(
                    update(OptimizationCandidateRow)
                    .where(
                        OptimizationCandidateRow.id == candidate_id,
                        OptimizationCandidateRow.owner_id == owner_id,
                        OptimizationCandidateRow.project_id == project_id,
                        OptimizationCandidateRow.state == previous.value,
                        OptimizationCandidateRow.version == expected_version,
                    )
                    .values(**values)
                ),
            )
            if result.rowcount != 1:
                await session.rollback()
                raise CandidateConflictError("candidate transition lost race")
            row.state, row.version, row.updated_at = target.value, expected_version + 1, now
            if target is CandidateState.PROMOTED:
                row.promoted_at = now
            elif target is CandidateState.ROLLED_BACK:
                row.rolled_back_at = now
            self._event(
                session, row, previous, target, cast(str | None, row.approval_id), reason_code
            )
            await session.commit()
        found = await self.get(owner_id, candidate_id, project_id=project_id)
        assert found is not None
        return found

    @staticmethod
    def _event(
        session: AsyncSession,
        row: OptimizationCandidateRow,
        source: CandidateState | None,
        target: CandidateState,
        approval_id: str | None,
        reason_code: str | None,
    ) -> None:
        session.add(
            OptimizationCandidateEventRow(
                id=str(uuid.uuid4()),
                candidate_id=row.id,
                owner_id=row.owner_id,
                project_id=row.project_id,
                event_type=target.value,
                from_state=None if source is None else source.value,
                to_state=target.value,
                candidate_version=row.version,
                approval_id=approval_id,
                reason_code=reason_code,
                created_at=row.updated_at,
            )
        )

    @staticmethod
    def _model(row: OptimizationCandidateRow) -> OptimizationCandidate:
        return OptimizationCandidate(
            id=str(row.id),
            owner_id=str(row.owner_id),
            project_id=str(row.project_id),
            candidate_type=CandidateType(str(row.candidate_type)),
            change_summary=str(row.change_summary),
            proposal_metadata=cast(dict[str, JSONValue], row.proposal_metadata_json),
            rollback_plan=str(row.rollback_plan),
            target_revision=str(row.target_revision),
            baseline_eval_id=str(row.baseline_eval_id),
            candidate_eval_id=str(row.candidate_eval_id),
            drift_report_id=cast(str | None, row.drift_report_id),
            state=CandidateState(str(row.state)),
            version=int(row.version),
            approval_id=cast(str | None, row.approval_id),
            created_at=cast(datetime, row.created_at),
            updated_at=cast(datetime, row.updated_at),
            promoted_at=cast(datetime | None, row.promoted_at),
            rolled_back_at=cast(datetime | None, row.rolled_back_at),
        )
