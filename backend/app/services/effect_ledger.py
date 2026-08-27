"""Atomic durable repository for effect reservation tombstones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.effect_ledger import EffectBinding, EffectState
from app.services.db_store import EffectRow

_EFFECT_ID = re.compile(r"^eff_v1_[0-9a-f]{64}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_PAGE = 200
_MAX_BIGINT = 2**63 - 1


class EffectStateConflict(RuntimeError):  # noqa: N818 - public domain terminology
    """A requested transition did not own the reserved state."""

    def __init__(self) -> None:
        super().__init__("effect_state_conflict")
        self.code = "effect_state_conflict"


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _effect_id(value: str) -> str:
    if not isinstance(value, str) or not _EFFECT_ID.fullmatch(value):
        raise ValueError("effect_id must be a version-1 effect digest")
    return value


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _safe_code(value: str) -> str:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        raise ValueError("safe_code must be a sanitized lowercase identifier")
    return value


@dataclass(frozen=True, slots=True)
class EffectReservation:
    effect_id: str
    state: EffectState
    should_execute: bool


@dataclass(frozen=True, slots=True)
class EffectRecord:
    """Safe persisted effect metadata; payload inputs and outputs are never exposed."""

    effect_id: str
    identity_version: int
    owner_id: str
    project_id: str
    run_id: str
    tool_name: str
    schema_hash: str
    state: EffectState
    output_hash: str | None
    output_size: int | None
    failure_code: str | None
    reserved_at: datetime
    completed_at: datetime | None


class EffectRepository:
    """Portable owner-scoped effect ledger with first-writer-wins reservation."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def reserve(
        self, binding: EffectBinding, *, now: datetime | None = None
    ) -> EffectReservation:
        if not isinstance(binding, EffectBinding):
            raise TypeError("binding must be an EffectBinding")
        effect_id = _effect_id(binding.effect_id)
        reserved_at = _utc(now or datetime.now(tz=UTC), "now")
        values = {
            "effect_id": effect_id,
            "identity_version": binding.identity_version,
            "owner_id": binding.owner_id,
            "project_id": binding.project_id,
            "run_id": binding.run_id,
            "tool_name": binding.tool_name,
            "schema_hash": _digest(binding.schema_hash, "schema_hash"),
            "state": EffectState.RESERVED.value,
            "reserved_at": reserved_at,
        }
        async with self._sessions() as session:
            dialect = session.get_bind().dialect.name
            if dialect in {"postgresql", "sqlite"}:
                constructor = pg_insert if dialect == "postgresql" else sqlite_insert
                statement = (
                    constructor(EffectRow)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=[EffectRow.effect_id])
                    .returning(EffectRow.effect_id)
                )
                inserted = (await session.execute(statement)).scalar_one_or_none() is not None
                await session.commit()
                if inserted:
                    return EffectReservation(effect_id, EffectState.RESERVED, True)
            else:
                session.add(EffectRow(**values))
                try:
                    await session.commit()
                    return EffectReservation(effect_id, EffectState.RESERVED, True)
                except IntegrityError:
                    await session.rollback()

            result = await session.execute(
                select(EffectRow.state).where(EffectRow.effect_id == effect_id)
            )
            state_value = result.scalar_one_or_none()
        if state_value is None:
            raise RuntimeError("effect_reservation_unavailable")
        return EffectReservation(effect_id, EffectState(state_value), False)

    async def commit(self, effect_id: str, output_hash: str, output_size: int) -> None:
        output_hash = _digest(output_hash, "output_hash")
        if type(output_size) is not int or not 0 <= output_size <= _MAX_BIGINT:
            raise ValueError("output_size must be an integer within the BIGINT range")
        await self._transition(
            effect_id,
            EffectState.COMMITTED,
            output_hash=output_hash,
            output_size=output_size,
            failure_code=None,
        )

    async def fail(self, effect_id: str, safe_code: str) -> None:
        await self._transition(
            effect_id,
            EffectState.FAILED,
            output_hash=None,
            output_size=None,
            failure_code=_safe_code(safe_code),
        )

    async def mark_indeterminate(self, effect_id: str, safe_code: str) -> None:
        await self._transition(
            effect_id,
            EffectState.INDETERMINATE,
            output_hash=None,
            output_size=None,
            failure_code=_safe_code(safe_code),
        )

    async def _transition(
        self,
        effect_id: str,
        state: EffectState,
        *,
        output_hash: str | None,
        output_size: int | None,
        failure_code: str | None,
    ) -> None:
        effect_id = _effect_id(effect_id)
        completed_at = datetime.now(tz=UTC)
        async with self._sessions() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(EffectRow)
                    .where(
                        EffectRow.effect_id == effect_id,
                        EffectRow.state == EffectState.RESERVED.value,
                    )
                    .values(
                        state=state.value,
                        output_hash=output_hash,
                        output_size=output_size,
                        failure_code=failure_code,
                        completed_at=completed_at,
                    )
                ),
            )
            if result.rowcount != 1:
                await session.rollback()
                raise EffectStateConflict
            await session.commit()

    async def recover_stale_reservations(self, cutoff: datetime) -> int:
        cutoff = _utc(cutoff, "cutoff")
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(EffectRow)
                    .where(
                        EffectRow.state == EffectState.RESERVED.value,
                        EffectRow.reserved_at < cutoff,
                    )
                    .values(
                        state=EffectState.INDETERMINATE.value,
                        failure_code="stale_reservation",
                        completed_at=now,
                    )
                ),
            )
            count = int(result.rowcount or 0)
            await session.commit()
            return count

    async def get(
        self, effect_id: str, *, owner_id: str, project_id: str, run_id: str
    ) -> EffectRecord | None:
        effect_id = _effect_id(effect_id)
        async with self._sessions() as session:
            result = await session.execute(
                select(EffectRow).where(
                    EffectRow.effect_id == effect_id,
                    EffectRow.owner_id == owner_id,
                    EffectRow.project_id == project_id,
                    EffectRow.run_id == run_id,
                )
            )
            row = result.scalar_one_or_none()
            return None if row is None else self._record(row)

    async def list(
        self,
        *,
        owner_id: str,
        project_id: str,
        run_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[EffectRecord, ...]:
        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= _MAX_PAGE
            or offset < 0
        ):
            raise ValueError("pagination is outside supported bounds")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(EffectRow)
                    .where(
                        EffectRow.owner_id == owner_id,
                        EffectRow.project_id == project_id,
                        EffectRow.run_id == run_id,
                    )
                    .order_by(EffectRow.reserved_at, EffectRow.effect_id)
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
            return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: EffectRow) -> EffectRecord:
        return EffectRecord(
            effect_id=row.effect_id,
            identity_version=row.identity_version,
            owner_id=row.owner_id,
            project_id=row.project_id,
            run_id=row.run_id,
            tool_name=row.tool_name,
            schema_hash=row.schema_hash,
            state=EffectState(row.state),
            output_hash=row.output_hash,
            output_size=row.output_size,
            failure_code=row.failure_code,
            reserved_at=_utc(row.reserved_at, "reserved_at"),
            completed_at=(
                None if row.completed_at is None else _utc(row.completed_at, "completed_at")
            ),
        )


# Terminology-friendly alias while keeping the class concise at call sites.
EffectLedgerRepository = EffectRepository
