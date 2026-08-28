from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.delegation.envelope import (
    DelegationEnvelopeService,
    InvalidDelegationEnvelope,
)
from app.services.db_store import Base, DelegationNonceRow


@pytest.fixture
async def envelopes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'envelopes.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    yield DelegationEnvelopeService(
        sessions, {1: b"a" * 32, 2: b"b" * 32}, active_key_version=2, max_age_seconds=60
    )
    await engine.dispose()


def issue(service, *, now=1000):
    return service.issue(
        parent_run_id="parent",
        child_run_id="child",
        owner_id="owner",
        project_id="project",
        context_hash="a" * 64,
        budget={
            "input_tokens": 10,
            "output_tokens": 5,
            "retries": 0,
            "timeout_seconds": 1.0,
        },
        now=now,
        nonce="unique-nonce",
    )


async def consume(service, envelope, *, now=1000):
    await service.verify_and_consume(
        envelope,
        owner_id="owner",
        project_id="project",
        parent_run_id="parent",
        child_run_id="child",
        context_hash="a" * 64,
        now=now,
    )


@pytest.mark.security
async def test_tamper_scope_freshness_and_key_version_fail_closed(envelopes) -> None:
    envelope = issue(envelopes)
    for changed, now in (
        (replace(envelope, project_id="foreign"), 1000),
        (replace(envelope, context_hash="b" * 64), 1000),
        (replace(envelope, budget=tuple(sorted({"input_tokens": 11}.items()))), 1000),
        (replace(envelope, signature="x" * 43), 1000),
        (replace(envelope, key_version=99), 1000),
        (envelope, 1061),
        (envelope, 969),
    ):
        with pytest.raises(InvalidDelegationEnvelope):
            await consume(envelopes, changed, now=now)


@pytest.mark.security
async def test_nonce_receipt_survives_and_rejects_replay(envelopes) -> None:
    envelope = issue(envelopes)
    await consume(envelopes, envelope)
    with pytest.raises(InvalidDelegationEnvelope):
        await consume(envelopes, envelope)


def test_keyring_and_budget_validation_fail_closed(tmp_path) -> None:
    sessions = async_sessionmaker(
        create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'invalid.db'}"),
        expire_on_commit=False,
    )
    with pytest.raises(ValueError, match="distinct versioned"):
        DelegationEnvelopeService(sessions, {1: b"a" * 32, 2: b"a" * 32}, active_key_version=2)
    service = DelegationEnvelopeService(sessions, {1: b"a" * 32}, active_key_version=1)
    budgets: tuple[dict[str, int | float], ...] = (
        {"tokens": 1},
        {"input_tokens": -1},
        {"input_tokens": 1, "timeout_seconds": float("inf")},
    )
    for budget in budgets:
        with pytest.raises(ValueError, match="invalid budget"):
            service.issue(
                parent_run_id="parent",
                child_run_id="child",
                owner_id="owner",
                project_id="project",
                context_hash="a" * 64,
                budget=budget,
                now=1000,
            )


@pytest.mark.asyncio
async def test_expired_nonce_receipts_are_pruned(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'prune.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = DelegationEnvelopeService(
        sessions,
        {1: b"a" * 32},
        active_key_version=1,
        max_age_seconds=10,
        max_future_skew_seconds=0,
    )
    first = service.issue(
        parent_run_id="parent",
        child_run_id="child-1",
        owner_id="owner",
        project_id="project",
        context_hash="a" * 64,
        budget={"input_tokens": 1},
        now=100,
        nonce="nonce-first",
    )
    await service.verify_and_consume(
        first,
        owner_id="owner",
        project_id="project",
        parent_run_id="parent",
        child_run_id="child-1",
        context_hash="a" * 64,
        now=100,
    )
    second = service.issue(
        parent_run_id="parent",
        child_run_id="child-2",
        owner_id="owner",
        project_id="project",
        context_hash="b" * 64,
        budget={"input_tokens": 1},
        now=200,
        nonce="nonce-second",
    )
    await service.verify_and_consume(
        second,
        owner_id="owner",
        project_id="project",
        parent_run_id="parent",
        child_run_id="child-2",
        context_hash="b" * 64,
        now=200,
    )
    async with sessions() as session:
        count = await session.scalar(select(func.count()).select_from(DelegationNonceRow))
        nonce = await session.scalar(select(DelegationNonceRow.nonce))
    assert count == 1 and nonce == "nonce-second"
    await engine.dispose()
