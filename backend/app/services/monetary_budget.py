"""Atomic, durable nano-USD model-call budget repository."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.cost_tracker import price_model_usage_nusd, validated_pricing_pair
from app.services.db_store import ModelChargeRow, ProjectBudgetRow, RunRow

_MAX_BIGINT = 2**63 - 1
_MAX_PAGE = 200
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


class ChargeState(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    RECONCILED = "reconciled"
    RELEASED = "released"
    INDETERMINATE = "indeterminate"


class MonetaryBudgetError(RuntimeError):
    code = "monetary_budget_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class RunBudgetExceeded(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    code = "run_budget_exceeded"


class ProjectBudgetExceeded(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    code = "project_budget_exceeded"


class BudgetLimitConflict(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    code = "budget_limit_conflict"


class ChargeStateConflict(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    code = "charge_state_conflict"


class ChargeConflict(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    """A charge key collided outside the caller's visible owner scope."""

    code = "charge_conflict"


class QuoteExceeded(MonetaryBudgetError):  # noqa: N818 - public domain terminology
    code = "charge_quote_exceeded"


@dataclass(frozen=True, slots=True)
class ChargeReservation:
    charge_id: str
    state: ChargeState
    should_dispatch: bool
    reserved_nusd: int


@dataclass(frozen=True, slots=True)
class ChargeRecord:
    """Safe charge metadata. Prompts and raw provider usage are never represented."""

    charge_id: str
    owner_id: str
    project_id: str
    run_id: str
    ordinal: int
    state: ChargeState
    reserved_nusd: int
    actual_nusd: int | None
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    reason_code: str | None
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None
    reconciled_at: datetime | None


@dataclass(frozen=True, slots=True)
class BudgetSummary:
    owner_id: str
    project_id: str
    run_id: str
    project_limit_nusd: int
    project_spent_nusd: int
    project_reserved_nusd: int
    run_limit_nusd: int
    run_spent_nusd: int
    run_reserved_nusd: int


def _id(value: str, label: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must be a safe non-empty identifier")
    return value


def _amount(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_BIGINT:
        raise ValueError(f"{label} must be an integer within the BIGINT range")
    return value


def _optional_amount(value: int | None, label: str) -> int | None:
    return None if value is None else _amount(value, label)


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _rows(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount or 0)


class MonetaryBudgetRepository:
    """Owner-scoped accounting with conditional SQL updates and no float arithmetic."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def open_run(
        self,
        owner_id: str,
        project_id: str,
        run_id: str,
        run_limit_nusd: int,
        project_limit_nusd: int,
    ) -> BudgetSummary:
        owner_id, project_id, run_id = (
            _id(owner_id, "owner_id", 255),
            _id(project_id, "project_id", 255),
            _id(run_id, "run_id", 36),
        )
        run_limit = _amount(run_limit_nusd, "run_limit_nusd")
        project_limit = _amount(project_limit_nusd, "project_limit_nusd")
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            dialect = session.get_bind().dialect.name
            values = dict(
                owner_id=owner_id,
                project_id=project_id,
                limit_nusd=project_limit,
                spent_nusd=0,
                reserved_nusd=0,
                updated_at=now,
            )
            if dialect in {"sqlite", "postgresql"}:
                constructor = sqlite_insert if dialect == "sqlite" else pg_insert
                await session.execute(
                    constructor(ProjectBudgetRow)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=[ProjectBudgetRow.owner_id, ProjectBudgetRow.project_id]
                    )
                )
            else:
                existing_project = await session.get(ProjectBudgetRow, (owner_id, project_id))
                if existing_project is None:
                    session.add(ProjectBudgetRow(**values))
                    await session.flush()

            project = await session.scalar(
                select(ProjectBudgetRow)
                .where(
                    ProjectBudgetRow.owner_id == owner_id,
                    ProjectBudgetRow.project_id == project_id,
                )
                .with_for_update()
            )
            if project is None or int(project.limit_nusd) != project_limit:
                await session.rollback()
                raise BudgetLimitConflict

            opened = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == owner_id,
                    RunRow.project_id == project_id,
                    RunRow.budget_opened_at.is_(None),
                )
                .values(budget_limit_nusd=run_limit, budget_opened_at=now)
            )
            if _rows(opened) != 1:
                run = await session.scalar(
                    select(RunRow).where(
                        RunRow.run_id == run_id,
                        RunRow.user_id == owner_id,
                        RunRow.project_id == project_id,
                    )
                )
                if run is None:
                    await session.rollback()
                    raise ValueError("run scope mismatch or run does not exist")
                if run.budget_opened_at is None or int(run.budget_limit_nusd) != run_limit:
                    await session.rollback()
                    raise BudgetLimitConflict
            await session.commit()
        summary = await self.summary(owner_id=owner_id, project_id=project_id, run_id=run_id)
        assert summary is not None
        return summary

    async def reserve_call(
        self,
        charge_id: str,
        owner_id: str,
        project_id: str,
        run_id: str,
        ordinal: int,
        quote_nusd: int,
        provider: str,
        model: str,
    ) -> ChargeReservation:
        charge_id, owner_id, project_id, run_id = (
            _id(charge_id, "charge_id", 128),
            _id(owner_id, "owner_id", 255),
            _id(project_id, "project_id", 255),
            _id(run_id, "run_id", 36),
        )
        if type(ordinal) is not int or not 0 <= ordinal <= 2**31 - 1:
            raise ValueError("ordinal must be a nonnegative integer")
        quote = _amount(quote_nusd, "quote_nusd")
        provider = _id(provider, "provider", 100)
        model = _id(model, "model", 255)
        provider, model = validated_pricing_pair(model, provider)
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            existing = await self._duplicate(
                session, charge_id, owner_id, project_id, run_id, ordinal
            )
            if existing is not None:
                return self._reservation(existing, False)
            project_result = await session.execute(
                update(ProjectBudgetRow)
                .where(
                    ProjectBudgetRow.owner_id == owner_id,
                    ProjectBudgetRow.project_id == project_id,
                    quote
                    <= ProjectBudgetRow.limit_nusd
                    - ProjectBudgetRow.spent_nusd
                    - ProjectBudgetRow.reserved_nusd,
                )
                .values(reserved_nusd=ProjectBudgetRow.reserved_nusd + quote, updated_at=now)
            )
            if _rows(project_result) != 1:
                await session.rollback()
                existing = await self._duplicate(
                    session, charge_id, owner_id, project_id, run_id, ordinal
                )
                if existing is not None:
                    return self._reservation(existing, False)
                raise ProjectBudgetExceeded
            run_result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == owner_id,
                    RunRow.project_id == project_id,
                    RunRow.budget_opened_at.is_not(None),
                    quote
                    <= RunRow.budget_limit_nusd
                    - RunRow.budget_spent_nusd
                    - RunRow.budget_reserved_nusd,
                )
                .values(budget_reserved_nusd=RunRow.budget_reserved_nusd + quote)
            )
            if _rows(run_result) != 1:
                await session.rollback()
                existing = await self._duplicate(
                    session, charge_id, owner_id, project_id, run_id, ordinal
                )
                if existing is not None:
                    return self._reservation(existing, False)
                raise RunBudgetExceeded
            session.add(
                ModelChargeRow(
                    charge_id=charge_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    state=ChargeState.RESERVED.value,
                    reserved_nusd=quote,
                    actual_nusd=None,
                    provider=provider,
                    model=model,
                    created_at=now,
                    updated_at=now,
                )
            )
            try:
                await session.commit()
                return ChargeReservation(charge_id, ChargeState.RESERVED, True, quote)
            except IntegrityError:
                await session.rollback()
                existing = await self._duplicate(
                    session, charge_id, owner_id, project_id, run_id, ordinal
                )
                if existing is None:
                    raise ChargeConflict from None
                return self._reservation(existing, False)

    async def mark_dispatched(
        self, charge_id: str, owner_id: str, project_id: str, run_id: str
    ) -> ChargeRecord:
        return await self._simple_transition(
            charge_id,
            owner_id,
            project_id,
            run_id,
            source=(ChargeState.RESERVED,),
            target=ChargeState.DISPATCHED,
            dispatched_at=datetime.now(tz=UTC),
        )

    async def reconcile(
        self,
        charge_id: str,
        owner_id: str,
        project_id: str,
        run_id: str,
        actual_nusd: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> ChargeRecord:
        charge_id, owner_id, project_id, run_id = self._scope(
            charge_id, owner_id, project_id, run_id
        )
        supplied_actual = _optional_amount(actual_nusd, "actual_nusd")
        input_count = _amount(input_tokens, "input_tokens")
        output_count = _amount(output_tokens, "output_tokens")
        read = _optional_amount(cache_read_tokens, "cache_read_tokens")
        write = _optional_amount(cache_write_tokens, "cache_write_tokens")
        if (read or 0) + (write or 0) > input_count:
            raise ValueError("cache token subsets cannot exceed total input tokens")
        if provider is not None:
            provider = _id(provider, "provider", 100)
        if model is not None:
            model = _id(model, "model", 255)
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            # Read the immutable quote, then mutate in project -> run -> charge order.
            charge = await session.scalar(
                select(ModelChargeRow).where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id)
                )
            )
            if charge is None or charge.state != ChargeState.DISPATCHED.value:
                raise ChargeStateConflict
            quote = int(charge.reserved_nusd)
            actual_provider = provider if provider is not None else charge.provider
            actual_model = model if model is not None else charge.model
            if actual_provider is None or actual_model is None:
                raise ValueError("charge has no priceable provider/model")
            actual_provider, actual_model = validated_pricing_pair(actual_model, actual_provider)
            actual = price_model_usage_nusd(
                actual_model,
                actual_provider,
                input_count,
                output_count,
                read,
                write,
            )
            if supplied_actual is not None and supplied_actual != actual:
                raise ValueError("actual_nusd does not match computed provider usage")
            if actual > quote:
                project_lock = await session.execute(
                    update(ProjectBudgetRow)
                    .where(
                        ProjectBudgetRow.owner_id == owner_id,
                        ProjectBudgetRow.project_id == project_id,
                    )
                    .values(updated_at=ProjectBudgetRow.updated_at)
                )
                run_lock = await session.execute(
                    update(RunRow)
                    .where(
                        RunRow.run_id == run_id,
                        RunRow.user_id == owner_id,
                        RunRow.project_id == project_id,
                    )
                    .values(budget_reserved_nusd=RunRow.budget_reserved_nusd)
                )
                changed = await session.execute(
                    update(ModelChargeRow)
                    .where(
                        *self._charge_filters(charge_id, owner_id, project_id, run_id),
                        ModelChargeRow.state == ChargeState.DISPATCHED.value,
                    )
                    .values(
                        state=ChargeState.INDETERMINATE.value,
                        reason_code="quote_exceeded",
                        updated_at=now,
                    )
                )
                if any(_rows(result) != 1 for result in (project_lock, run_lock, changed)):
                    await session.rollback()
                    raise ChargeStateConflict
                await session.commit()
                raise QuoteExceeded
            project_result = await session.execute(
                update(ProjectBudgetRow)
                .where(
                    ProjectBudgetRow.owner_id == owner_id,
                    ProjectBudgetRow.project_id == project_id,
                    ProjectBudgetRow.reserved_nusd >= quote,
                )
                .values(
                    reserved_nusd=ProjectBudgetRow.reserved_nusd - quote,
                    spent_nusd=ProjectBudgetRow.spent_nusd + actual,
                    updated_at=now,
                )
            )
            run_result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == owner_id,
                    RunRow.project_id == project_id,
                    RunRow.budget_reserved_nusd >= quote,
                )
                .values(
                    budget_reserved_nusd=RunRow.budget_reserved_nusd - quote,
                    budget_spent_nusd=RunRow.budget_spent_nusd + actual,
                )
            )
            charge_result = await session.execute(
                update(ModelChargeRow)
                .where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id),
                    ModelChargeRow.state == ChargeState.DISPATCHED.value,
                    ModelChargeRow.reserved_nusd == quote,
                )
                .values(
                    state=ChargeState.RECONCILED.value,
                    actual_nusd=actual,
                    provider=actual_provider,
                    model=actual_model,
                    input_tokens=input_count,
                    output_tokens=output_count,
                    cache_read_tokens=read,
                    cache_write_tokens=write,
                    updated_at=now,
                    reconciled_at=now,
                )
            )
            if any(_rows(result) != 1 for result in (project_result, run_result, charge_result)):
                await session.rollback()
                raise ChargeStateConflict
            await session.commit()
            persisted = await session.scalar(
                select(ModelChargeRow).where(ModelChargeRow.charge_id == charge_id)
            )
            assert persisted is not None
            return self._record(persisted)

    async def release(
        self, charge_id: str, owner_id: str, project_id: str, run_id: str
    ) -> ChargeRecord:
        return await self._release(charge_id, owner_id, project_id, run_id, "released")

    async def mark_indeterminate(
        self,
        charge_id: str,
        owner_id: str,
        project_id: str,
        run_id: str,
        reason_code: str = "indeterminate",
    ) -> ChargeRecord:
        reason = _id(reason_code, "reason_code", 64)
        return await self._simple_transition(
            charge_id,
            owner_id,
            project_id,
            run_id,
            source=(ChargeState.RESERVED, ChargeState.DISPATCHED),
            target=ChargeState.INDETERMINATE,
            reason_code=reason,
        )

    async def recover_stale(self, cutoff: datetime) -> int:
        """Recover stale charges without ever taking a charge lock before account locks."""
        cutoff = _utc(cutoff, "cutoff")
        async with self._sessions() as session:
            candidates = (
                await session.execute(
                    select(
                        ModelChargeRow.charge_id,
                        ModelChargeRow.owner_id,
                        ModelChargeRow.project_id,
                        ModelChargeRow.run_id,
                        ModelChargeRow.state,
                        ModelChargeRow.reserved_nusd,
                    )
                    .where(
                        ModelChargeRow.state.in_(
                            [ChargeState.RESERVED.value, ChargeState.DISPATCHED.value]
                        ),
                        ModelChargeRow.updated_at < cutoff,
                    )
                    .order_by(
                        ModelChargeRow.owner_id,
                        ModelChargeRow.project_id,
                        ModelChargeRow.run_id,
                        ModelChargeRow.charge_id,
                    )
                )
            ).all()

        count = 0
        for charge_id, owner_id, project_id, run_id, state, reserved_nusd in candidates:
            now = datetime.now(tz=UTC)
            quote = int(reserved_nusd)
            async with self._sessions() as session:
                if state == ChargeState.RESERVED.value:
                    project = await session.execute(
                        update(ProjectBudgetRow)
                        .where(
                            ProjectBudgetRow.owner_id == owner_id,
                            ProjectBudgetRow.project_id == project_id,
                            ProjectBudgetRow.reserved_nusd >= quote,
                        )
                        .values(
                            reserved_nusd=ProjectBudgetRow.reserved_nusd - quote,
                            updated_at=now,
                        )
                    )
                    run = await session.execute(
                        update(RunRow)
                        .where(
                            RunRow.run_id == run_id,
                            RunRow.user_id == owner_id,
                            RunRow.project_id == project_id,
                            RunRow.budget_reserved_nusd >= quote,
                        )
                        .values(budget_reserved_nusd=RunRow.budget_reserved_nusd - quote)
                    )
                    changed = await session.execute(
                        update(ModelChargeRow)
                        .where(
                            ModelChargeRow.charge_id == charge_id,
                            ModelChargeRow.owner_id == owner_id,
                            ModelChargeRow.project_id == project_id,
                            ModelChargeRow.run_id == run_id,
                            ModelChargeRow.state == ChargeState.RESERVED.value,
                            ModelChargeRow.reserved_nusd == quote,
                            ModelChargeRow.updated_at < cutoff,
                        )
                        .values(
                            state=ChargeState.RELEASED.value,
                            reason_code="stale_reserved",
                            updated_at=now,
                        )
                    )
                else:
                    project = await session.execute(
                        update(ProjectBudgetRow)
                        .where(
                            ProjectBudgetRow.owner_id == owner_id,
                            ProjectBudgetRow.project_id == project_id,
                        )
                        .values(updated_at=ProjectBudgetRow.updated_at)
                    )
                    run = await session.execute(
                        update(RunRow)
                        .where(
                            RunRow.run_id == run_id,
                            RunRow.user_id == owner_id,
                            RunRow.project_id == project_id,
                        )
                        .values(budget_reserved_nusd=RunRow.budget_reserved_nusd)
                    )
                    changed = await session.execute(
                        update(ModelChargeRow)
                        .where(
                            ModelChargeRow.charge_id == charge_id,
                            ModelChargeRow.owner_id == owner_id,
                            ModelChargeRow.project_id == project_id,
                            ModelChargeRow.run_id == run_id,
                            ModelChargeRow.state == ChargeState.DISPATCHED.value,
                            ModelChargeRow.updated_at < cutoff,
                        )
                        .values(
                            state=ChargeState.INDETERMINATE.value,
                            reason_code="stale_dispatched",
                            updated_at=now,
                        )
                    )
                rows = (_rows(project), _rows(run), _rows(changed))
                if rows == (1, 1, 1):
                    await session.commit()
                    count += 1
                elif rows[2] == 0:
                    # Another recovery/terminal transition won. Roll back account
                    # changes together so recovery remains exactly-once.
                    await session.rollback()
                else:
                    await session.rollback()
                    raise ChargeStateConflict
        return count

    async def get(
        self, charge_id: str, *, owner_id: str, project_id: str, run_id: str
    ) -> ChargeRecord | None:
        charge_id, owner_id, project_id, run_id = self._scope(
            charge_id, owner_id, project_id, run_id
        )
        async with self._sessions() as session:
            row = await session.scalar(
                select(ModelChargeRow).where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id)
                )
            )
            return None if row is None else self._record(row)

    get_charge = get

    async def list(
        self,
        *,
        owner_id: str,
        project_id: str,
        run_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[ChargeRecord, ...]:
        owner_id, project_id, run_id = (
            _id(owner_id, "owner_id", 255),
            _id(project_id, "project_id", 255),
            _id(run_id, "run_id", 36),
        )
        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= _MAX_PAGE
            or offset < 0
        ):
            raise ValueError("pagination is outside supported bounds")
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ModelChargeRow)
                    .where(
                        ModelChargeRow.owner_id == owner_id,
                        ModelChargeRow.project_id == project_id,
                        ModelChargeRow.run_id == run_id,
                    )
                    .order_by(ModelChargeRow.ordinal, ModelChargeRow.charge_id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return tuple(self._record(row) for row in rows)

    list_charges = list

    async def summary(self, *, owner_id: str, project_id: str, run_id: str) -> BudgetSummary | None:
        owner_id, project_id, run_id = (
            _id(owner_id, "owner_id", 255),
            _id(project_id, "project_id", 255),
            _id(run_id, "run_id", 36),
        )
        async with self._sessions() as session:
            result = (
                await session.execute(
                    select(ProjectBudgetRow, RunRow)
                    .join(
                        RunRow,
                        (RunRow.user_id == ProjectBudgetRow.owner_id)
                        & (RunRow.project_id == ProjectBudgetRow.project_id),
                    )
                    .where(
                        ProjectBudgetRow.owner_id == owner_id,
                        ProjectBudgetRow.project_id == project_id,
                        RunRow.run_id == run_id,
                    )
                )
            ).one_or_none()
            if result is None:
                return None
            project, run = result
            return BudgetSummary(
                owner_id,
                project_id,
                run_id,
                int(project.limit_nusd),
                int(project.spent_nusd),
                int(project.reserved_nusd),
                int(run.budget_limit_nusd),
                int(run.budget_spent_nusd),
                int(run.budget_reserved_nusd),
            )

    get_summary = summary

    async def _release(
        self, charge_id: str, owner_id: str, project_id: str, run_id: str, reason: str
    ) -> ChargeRecord:
        charge_id, owner_id, project_id, run_id = self._scope(
            charge_id, owner_id, project_id, run_id
        )
        now = datetime.now(tz=UTC)
        async with self._sessions() as session:
            charge = await session.scalar(
                select(ModelChargeRow).where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id),
                    ModelChargeRow.state == ChargeState.RESERVED.value,
                )
            )
            if charge is None:
                raise ChargeStateConflict
            quote = int(charge.reserved_nusd)
            project = await session.execute(
                update(ProjectBudgetRow)
                .where(
                    ProjectBudgetRow.owner_id == owner_id,
                    ProjectBudgetRow.project_id == project_id,
                    ProjectBudgetRow.reserved_nusd >= quote,
                )
                .values(reserved_nusd=ProjectBudgetRow.reserved_nusd - quote, updated_at=now)
            )
            run = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == owner_id,
                    RunRow.project_id == project_id,
                    RunRow.budget_reserved_nusd >= quote,
                )
                .values(budget_reserved_nusd=RunRow.budget_reserved_nusd - quote)
            )
            changed = await session.execute(
                update(ModelChargeRow)
                .where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id),
                    ModelChargeRow.state == ChargeState.RESERVED.value,
                    ModelChargeRow.reserved_nusd == quote,
                )
                .values(
                    state=ChargeState.RELEASED.value,
                    reason_code=reason,
                    updated_at=now,
                )
            )
            if any(_rows(result) != 1 for result in (project, run, changed)):
                await session.rollback()
                raise ChargeStateConflict
            await session.commit()
            persisted = await session.scalar(
                select(ModelChargeRow).where(ModelChargeRow.charge_id == charge_id)
            )
            assert persisted is not None
            return self._record(persisted)

    async def _simple_transition(
        self,
        charge_id: str,
        owner_id: str,
        project_id: str,
        run_id: str,
        *,
        source: tuple[ChargeState, ...],
        target: ChargeState,
        **values: Any,
    ) -> ChargeRecord:
        charge_id, owner_id, project_id, run_id = self._scope(
            charge_id, owner_id, project_id, run_id
        )
        values.update(state=target.value, updated_at=datetime.now(tz=UTC))
        async with self._sessions() as session:
            project_lock = await session.execute(
                update(ProjectBudgetRow)
                .where(
                    ProjectBudgetRow.owner_id == owner_id,
                    ProjectBudgetRow.project_id == project_id,
                )
                .values(updated_at=ProjectBudgetRow.updated_at)
            )
            run_lock = await session.execute(
                update(RunRow)
                .where(
                    RunRow.run_id == run_id,
                    RunRow.user_id == owner_id,
                    RunRow.project_id == project_id,
                )
                .values(budget_reserved_nusd=RunRow.budget_reserved_nusd)
            )
            result = await session.execute(
                update(ModelChargeRow)
                .where(
                    *self._charge_filters(charge_id, owner_id, project_id, run_id),
                    ModelChargeRow.state.in_([state.value for state in source]),
                )
                .values(**values)
            )
            if any(_rows(item) != 1 for item in (project_lock, run_lock, result)):
                await session.rollback()
                raise ChargeStateConflict
            await session.commit()
            row = await session.scalar(
                select(ModelChargeRow).where(ModelChargeRow.charge_id == charge_id)
            )
            assert row is not None
            return self._record(row)

    @staticmethod
    async def _duplicate(
        session: AsyncSession,
        charge_id: str,
        owner_id: str,
        project_id: str,
        run_id: str,
        ordinal: int,
    ) -> ModelChargeRow | None:
        row = await session.scalar(
            select(ModelChargeRow).where(
                ModelChargeRow.owner_id == owner_id,
                ModelChargeRow.project_id == project_id,
                (
                    (ModelChargeRow.charge_id == charge_id)
                    | ((ModelChargeRow.run_id == run_id) & (ModelChargeRow.ordinal == ordinal))
                ),
            )
        )
        if row is not None and row.run_id != run_id:
            raise ChargeConflict
        return row

    @staticmethod
    def _scope(
        charge_id: str, owner_id: str, project_id: str, run_id: str
    ) -> tuple[str, str, str, str]:
        return (
            _id(charge_id, "charge_id", 128),
            _id(owner_id, "owner_id", 255),
            _id(project_id, "project_id", 255),
            _id(run_id, "run_id", 36),
        )

    @staticmethod
    def _charge_filters(
        charge_id: str, owner_id: str, project_id: str, run_id: str
    ) -> tuple[Any, ...]:
        return (
            ModelChargeRow.charge_id == charge_id,
            ModelChargeRow.owner_id == owner_id,
            ModelChargeRow.project_id == project_id,
            ModelChargeRow.run_id == run_id,
        )

    @staticmethod
    def _reservation(row: ModelChargeRow, should_dispatch: bool) -> ChargeReservation:
        return ChargeReservation(
            row.charge_id, ChargeState(row.state), should_dispatch, int(row.reserved_nusd)
        )

    @staticmethod
    def _record(row: ModelChargeRow) -> ChargeRecord:
        def date(value: datetime | None) -> datetime | None:
            return None if value is None else _utc(value, "stored timestamp")

        return ChargeRecord(
            charge_id=row.charge_id,
            owner_id=row.owner_id,
            project_id=row.project_id,
            run_id=row.run_id,
            ordinal=int(row.ordinal),
            state=ChargeState(row.state),
            reserved_nusd=int(row.reserved_nusd),
            actual_nusd=None if row.actual_nusd is None else int(row.actual_nusd),
            provider=row.provider,
            model=row.model,
            input_tokens=None if row.input_tokens is None else int(row.input_tokens),
            output_tokens=None if row.output_tokens is None else int(row.output_tokens),
            cache_read_tokens=(
                None if row.cache_read_tokens is None else int(row.cache_read_tokens)
            ),
            cache_write_tokens=(
                None if row.cache_write_tokens is None else int(row.cache_write_tokens)
            ),
            reason_code=row.reason_code,
            created_at=cast(datetime, date(row.created_at)),
            updated_at=cast(datetime, date(row.updated_at)),
            dispatched_at=date(row.dispatched_at),
            reconciled_at=date(row.reconciled_at),
        )


MonetaryChargeState = ChargeState
