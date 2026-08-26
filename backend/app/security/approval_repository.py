"""Durable, owner-scoped persistence for exact-binding approval requests."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.policy import RiskClass, canonical_tool_name
from app.services.db_store import ApprovalRequestRow

_HASH = re.compile(r"^[0-9a-f]{64}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ApprovalStatus(StrEnum):
    """Complete durable lifecycle of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != normalized.strip() or not normalized:
        raise ValueError(f"{label} must be non-empty without surrounding whitespace")
    if len(normalized) > 255:
        raise ValueError(f"{label} is too long")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise ValueError(f"{label} cannot contain control characters")
    return normalized


def _uuid(value: str) -> str:
    value = _identifier(value, "approval id")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise ValueError("approval id must be a UUID string") from error
    if str(parsed) != value:
        raise ValueError("approval id must be a canonical UUID string")
    return value


def _datetime(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    # SQLite drops timezone metadata. Treat its naive values as UTC, never local time.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _reason(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _REASON.fullmatch(value):
        raise ValueError("decision reason must be a sanitized lowercase identifier")
    return value


def _risks(values: Iterable[RiskClass | str]) -> frozenset[RiskClass]:
    if isinstance(values, (str, bytes)):
        raise TypeError("risk_classes must be an iterable of risk classes")
    try:
        risks = frozenset(RiskClass(value) for value in values)
    except (TypeError, ValueError) as error:
        raise ValueError("risk_classes contains an unknown risk class") from error
    if not risks:
        raise ValueError("risk_classes must be non-empty")
    return risks


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Immutable durable approval state. It intentionally has no raw-arguments field."""

    id: str
    user_id: str
    conversation_id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    arguments_hash: str
    risk_classes: frozenset[RiskClass] = field(default_factory=frozenset)
    matched_rule_id: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _uuid(self.id))
        for name in ("user_id", "conversation_id", "run_id", "tool_call_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if not isinstance(self.tool_name, str):
            raise TypeError("tool_name must be a string")
        if canonical_tool_name(self.tool_name) != self.tool_name:
            raise ValueError("tool_name must be canonical")
        tool_name = _identifier(self.tool_name, "tool_name")
        object.__setattr__(self, "tool_name", tool_name)
        if not isinstance(self.arguments_hash, str) or not _HASH.fullmatch(self.arguments_hash):
            raise ValueError("arguments_hash must be a lowercase SHA-256 digest")
        object.__setattr__(self, "risk_classes", _risks(self.risk_classes))
        if self.matched_rule_id is not None:
            object.__setattr__(
                self, "matched_rule_id", _identifier(self.matched_rule_id, "matched_rule_id")
            )
        try:
            status = ApprovalStatus(self.status)
        except (TypeError, ValueError) as error:
            raise ValueError("unknown approval status") from error
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "decision_reason", _reason(self.decision_reason))
        created = _datetime(self.created_at, "created_at")
        expires = _datetime(self.expires_at, "expires_at")
        decided = None if self.decided_at is None else _datetime(self.decided_at, "decided_at")
        if expires <= created:
            raise ValueError("expires_at must be after created_at")
        if status is ApprovalStatus.PENDING and (
            self.decision_reason is not None or decided is not None
        ):
            raise ValueError("pending approvals cannot have decision metadata")
        if status is not ApprovalStatus.PENDING and decided is None:
            raise ValueError("terminal approvals require decided_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "decided_at", decided)


class ApprovalRepository:
    """Portable async SQLAlchemy repository with conditional atomic transitions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def reserve(
        self,
        *,
        user_id: str,
        conversation_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_hash: str,
        risk_classes: Iterable[RiskClass | str],
        matched_rule_id: str | None = None,
        ttl: timedelta,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        created = _datetime(now or datetime.now(tz=UTC), "now")
        record = ApprovalRecord(
            id=str(uuid.uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
            risk_classes=_risks(risk_classes),
            matched_rule_id=matched_rule_id,
            created_at=created,
            expires_at=created + ttl,
        )
        row = ApprovalRequestRow(
            id=record.id,
            user_id=record.user_id,
            conversation_id=record.conversation_id,
            run_id=record.run_id,
            tool_call_id=record.tool_call_id,
            tool_name=record.tool_name,
            arguments_hash=record.arguments_hash,
            risk_classes=json.dumps(sorted(risk.value for risk in record.risk_classes)),
            matched_rule_id=record.matched_rule_id,
            status=record.status.value,
            decision_reason=None,
            created_at=record.created_at,
            expires_at=record.expires_at,
            decided_at=None,
        )
        async with self._sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise ValueError("duplicate approval owner/run/tool-call identity") from error
        return record

    async def get_owner(self, approval_id: str, user_id: str) -> ApprovalRecord | None:
        approval_id = _uuid(approval_id)
        user_id = _identifier(user_id, "user_id")
        async with self._sessions() as session:
            result = await session.execute(
                select(ApprovalRequestRow).where(
                    ApprovalRequestRow.id == approval_id,
                    ApprovalRequestRow.user_id == user_id,
                )
            )
            row = result.scalar_one_or_none()
            return None if row is None else self._record(row)

    async def find_pending_by_tool_call(
        self, *, user_id: str, tool_call_id: str, now: datetime | None = None
    ) -> ApprovalRecord | None:
        user_id = _identifier(user_id, "user_id")
        tool_call_id = _identifier(tool_call_id, "tool_call_id")
        current = _datetime(now or datetime.now(tz=UTC), "now")
        async with self._sessions() as session:
            result = await session.execute(
                select(ApprovalRequestRow)
                .where(
                    ApprovalRequestRow.user_id == user_id,
                    ApprovalRequestRow.tool_call_id == tool_call_id,
                    ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                    ApprovalRequestRow.expires_at > current,
                )
                .limit(2)
            )
            rows = result.scalars().all()
            return self._record(rows[0]) if len(rows) == 1 else None

    async def decide_for_owner(
        self,
        *,
        approval_id: str,
        user_id: str,
        status: ApprovalStatus,
        reason: str,
        now: datetime | None = None,
    ) -> bool:
        approval_id = _uuid(approval_id)
        user_id = _identifier(user_id, "user_id")
        try:
            decision = ApprovalStatus(status)
        except (TypeError, ValueError) as error:
            raise ValueError("unknown approval status") from error
        if decision not in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED}:
            raise ValueError("decision status must be approved or denied")
        decision_reason = _reason(reason)
        if decision_reason is None:
            raise ValueError("decision reason is required")
        current = _datetime(now or datetime.now(tz=UTC), "now")
        async with self._sessions() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ApprovalRequestRow)
                    .where(
                        ApprovalRequestRow.id == approval_id,
                        ApprovalRequestRow.user_id == user_id,
                        ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                        ApprovalRequestRow.expires_at > current,
                    )
                    .values(
                        status=decision.value,
                        decision_reason=decision_reason,
                        decided_at=current,
                    )
                ),
            )
            won = bool(result.rowcount == 1)
            await session.commit()
            return won

    async def expire_due(self, *, now: datetime | None = None) -> int:
        current = _datetime(now or datetime.now(tz=UTC), "now")
        async with self._sessions() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ApprovalRequestRow)
                    .where(
                        ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                        ApprovalRequestRow.expires_at <= current,
                    )
                    .values(
                        status=ApprovalStatus.EXPIRED.value,
                        decision_reason="approval_expired",
                        decided_at=current,
                    )
                ),
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def cancel_run(self, *, user_id: str, run_id: str, now: datetime | None = None) -> int:
        user_id = _identifier(user_id, "user_id")
        run_id = _identifier(run_id, "run_id")
        current = _datetime(now or datetime.now(tz=UTC), "now")
        async with self._sessions() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(ApprovalRequestRow)
                    .where(
                        ApprovalRequestRow.user_id == user_id,
                        ApprovalRequestRow.run_id == run_id,
                        ApprovalRequestRow.status == ApprovalStatus.PENDING.value,
                    )
                    .values(
                        status=ApprovalStatus.CANCELLED.value,
                        decision_reason="run_cancelled",
                        decided_at=current,
                    )
                ),
            )
            await session.commit()
            return int(result.rowcount or 0)

    async def get_status(self, approval_id: str, user_id: str) -> ApprovalStatus | None:
        record = await self.get_owner(approval_id, user_id)
        return None if record is None else record.status

    @staticmethod
    def _record(row: ApprovalRequestRow) -> ApprovalRecord:
        try:
            risks = json.loads(row.risk_classes)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("persisted risk_classes is invalid") from error
        if not isinstance(risks, list):
            raise ValueError("persisted risk_classes is invalid")
        return ApprovalRecord(
            id=row.id,
            user_id=row.user_id,
            conversation_id=row.conversation_id,
            run_id=row.run_id,
            tool_call_id=row.tool_call_id,
            tool_name=row.tool_name,
            arguments_hash=row.arguments_hash,
            risk_classes=_risks(risks),
            matched_rule_id=row.matched_rule_id,
            status=ApprovalStatus(row.status),
            decision_reason=row.decision_reason,
            created_at=_datetime(row.created_at, "created_at"),
            expires_at=_datetime(row.expires_at, "expires_at"),
            decided_at=None if row.decided_at is None else _datetime(row.decided_at, "decided_at"),
        )
