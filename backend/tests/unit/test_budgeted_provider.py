"""Durable model-provider budget boundary tests."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.observability.cost_tracker import quote_model_call_nusd
from app.runtime.capabilities import ProviderCapabilities
from app.runtime.models import Message, ModelResponse, Role, TokenUsage, ToolCall, ToolDefinition
from app.runtime.monetary_budget import (
    BudgetRunContext,
    DuplicateModelCharge,
    DurableBudgetedProvider,
    DurableModelChargeStateError,
    IndeterminateModelCharge,
    ModelBudgetExhausted,
    PricingCandidate,
)
from app.services.db_store import Base, RunRow
from app.services.monetary_budget import ChargeState, MonetaryBudgetRepository


class FakeProvider:
    capabilities = ProviderCapabilities(
        native_tools=True, images=True, usage=True, cache_usage=True
    )

    def __init__(self, responses: list[ModelResponse] | None = None) -> None:
        self.responses = responses or [
            ModelResponse(
                "ok", usage=TokenUsage(10, 2), actual_provider="openai", actual_model="gpt-4o"
            )
        ]
        self.calls: list[tuple[object, object, dict[str, Any]]] = []

    async def complete(self, messages, tools=(), **kwargs):
        self.calls.append((messages, tools, kwargs))
        return self.responses.pop(0)


class RoutedProvider(FakeProvider):
    routes_capabilities = True


class RaisingProvider(FakeProvider):
    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def complete(self, messages, tools=(), **kwargs):
        self.calls.append((messages, tools, kwargs))
        raise self.error


async def repository(path: Path, run_id: str = "run-1"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", connect_args={"timeout": 30})
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(
            RunRow(
                run_id=run_id,
                user_id="alice",
                project_id="project",
                conversation_id=run_id,
                correlation_id=run_id,
                provider="mock",
                model="mock-model",
                status="running",
                started_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()
    return MonetaryBudgetRepository(sessions), engine


def wrapper(delegate, repo, *, run_id="run-1", candidates=None, limit=1_000_000_000):
    return DurableBudgetedProvider(
        delegate,
        repo,
        BudgetRunContext("alice", "project", run_id),
        run_limit_nusd=limit,
        project_limit_nusd=limit,
        max_input_tokens=1_000,
        pricing_candidates=candidates or (PricingCandidate("openai", "gpt-4o"),),
    )


@pytest.mark.asyncio
async def test_lazy_open_once_ordinals_ids_and_actual_cache_reconciliation(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "calls.db")
    delegate = FakeProvider(
        [
            ModelResponse(
                "one",
                usage=TokenUsage(100, 5, 80, 10),
                actual_provider="OpenAIAdapter",
                actual_model="gpt-4o",
            ),
            ModelResponse(
                "two", usage=TokenUsage(20, 3), actual_provider="openai", actual_model="gpt-4o"
            ),
        ]
    )
    budgeted = wrapper(delegate, repo)
    assert await repo.summary(owner_id="alice", project_id="project", run_id="run-1") is None

    await budgeted.complete([Message(Role.USER, "secret one")], max_tokens=20)
    await budgeted.complete([Message(Role.USER, "secret two")], max_tokens=30)

    charges = await repo.list(owner_id="alice", project_id="project", run_id="run-1")
    assert [charge.ordinal for charge in charges] == [0, 1]
    assert len({charge.charge_id for charge in charges}) == 2
    assert all(charge.charge_id.startswith("model_v1_") for charge in charges)
    assert all(charge.state is ChargeState.RECONCILED for charge in charges)
    assert (charges[0].provider, charges[0].model) == ("openai", "gpt-4o")
    assert (charges[0].cache_read_tokens, charges[0].cache_write_tokens) == (80, 10)
    assert "secret" not in " ".join(charge.charge_id for charge in charges)
    await engine.dispose()


@pytest.mark.asyncio
async def test_max_candidate_quote_exact_budget_and_zero_budget_block_before_delegate(
    tmp_path: Path,
) -> None:
    candidates = (
        PricingCandidate("openai", "gpt-4o-mini"),
        PricingCandidate("openai", "gpt-4o"),
    )
    quote = quote_model_call_nusd(candidates, 1_000, 10)
    repo, engine = await repository(tmp_path / "exact.db")
    delegate = FakeProvider()
    budgeted = wrapper(delegate, repo, candidates=candidates, limit=quote)
    await budgeted.complete([Message(Role.USER, "x")], max_tokens=10)
    charges = await repo.list(owner_id="alice", project_id="project", run_id="run-1")
    assert charges[0].reserved_nusd == quote

    zero_repo, zero_engine = await repository(tmp_path / "zero.db", "zero")
    zero_delegate = FakeProvider()
    with pytest.raises(ModelBudgetExhausted, match="model_budget_exhausted"):
        await wrapper(zero_delegate, zero_repo, run_id="zero", limit=0).complete(
            [Message(Role.USER, "x")], max_tokens=1
        )
    assert not zero_delegate.calls
    await engine.dispose()
    await zero_engine.dispose()

    free_repo, free_engine = await repository(tmp_path / "free.db", "free")
    free_delegate = FakeProvider(
        [
            ModelResponse(
                "free",
                usage=TokenUsage(10, 2),
                actual_provider="mock",
                actual_model="mock-model",
            )
        ]
    )
    await wrapper(
        free_delegate,
        free_repo,
        run_id="free",
        limit=0,
        candidates=(PricingCandidate("mock", "mock-model"),),
    ).complete([Message(Role.USER, "x")], max_tokens=1)
    assert len(free_delegate.calls) == 1
    await free_engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_new_run_scoped_wrapper_never_dispatches(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "duplicate.db")
    await wrapper(FakeProvider(), repo).complete([Message(Role.USER, "x")], max_tokens=1)
    duplicate_delegate = FakeProvider()
    with pytest.raises(DuplicateModelCharge, match="duplicate_model_charge"):
        await wrapper(duplicate_delegate, repo).complete(
            [Message(Role.USER, "different")], max_tokens=1
        )
    assert not duplicate_delegate.calls
    await engine.dispose()


@pytest.mark.asyncio
async def test_identity_fallback_and_disallowed_or_missing_winner_are_indeterminate(
    tmp_path: Path,
) -> None:
    repo, engine = await repository(tmp_path / "identities.db")
    single = FakeProvider([ModelResponse("ok", usage=TokenUsage(1, 1))])
    await wrapper(single, repo).complete([Message(Role.USER, "x")], max_tokens=2)
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert (charge.provider, charge.model, charge.state) == (
        "openai",
        "gpt-4o",
        ChargeState.RECONCILED,
    )
    await engine.dispose()

    for suffix, response in (
        ("missing", ModelResponse("ok", usage=TokenUsage(1, 1))),
        (
            "winner",
            ModelResponse(
                "ok", usage=TokenUsage(1, 1), actual_provider="openai", actual_model="gpt-4-turbo"
            ),
        ),
    ):
        run_id = f"run-{suffix}"
        repo, engine = await repository(tmp_path / f"{suffix}.db", run_id)
        candidates = (
            PricingCandidate("openai", "gpt-4o"),
            PricingCandidate("openai", "gpt-4o-mini"),
        )
        with pytest.raises(IndeterminateModelCharge, match="indeterminate_model_charge"):
            await wrapper(
                FakeProvider([response]), repo, run_id=run_id, candidates=candidates
            ).complete([Message(Role.USER, "x")], max_tokens=2)
        charge = (await repo.list(owner_id="alice", project_id="project", run_id=run_id))[0]
        assert charge.state is ChargeState.INDETERMINATE
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("provider failed"), asyncio.CancelledError()])
async def test_provider_exception_and_cancellation_mark_indeterminate(
    tmp_path: Path, error: BaseException
) -> None:
    run_id = "run-cancel" if isinstance(error, asyncio.CancelledError) else "run-error"
    repo, engine = await repository(tmp_path / f"{run_id}.db", run_id)
    delegate = RaisingProvider(error)
    with pytest.raises(type(error)):
        await wrapper(delegate, repo, run_id=run_id).complete([Message(Role.USER, "x")])
    charge = (await repo.list(owner_id="alice", project_id="project", run_id=run_id))[0]
    assert charge.state is ChargeState.INDETERMINATE
    await engine.dispose()


@pytest.mark.asyncio
async def test_capabilities_contract_tools_images_and_marker_forwarded_unchanged(
    tmp_path: Path,
) -> None:
    repo, engine = await repository(tmp_path / "forward.db")
    delegate = RoutedProvider()
    budgeted = wrapper(delegate, repo)
    messages = (Message(Role.USER, "look", images=("image",)),)
    tools = (ToolDefinition("tool", input_schema={"type": "object"}),)
    required = ProviderCapabilities(images=True, native_tools=True)
    await budgeted.complete(
        messages,
        tools,
        max_tokens=7,
        response_format="json",
        required_capabilities=required,
    )
    assert budgeted.capabilities is delegate.capabilities
    assert budgeted.routes_capabilities is True
    got_messages, got_tools, kwargs = delegate.calls[0]
    assert got_messages is messages and got_tools is tools
    assert kwargs == {
        "max_tokens": 7,
        "response_format": "json",
        "required_capabilities": required,
    }
    await engine.dispose()


def test_context_candidates_and_limits_are_validated_and_immutable(tmp_path: Path) -> None:
    context = BudgetRunContext("alice", "project", "run-1")
    candidate = PricingCandidate("OpenAIAdapter", "gpt-4o")
    assert candidate == PricingCandidate("openai", "gpt-4o")
    with pytest.raises(FrozenInstanceError):
        context.run_id = "other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        DurableBudgetedProvider(FakeProvider(), object(), context, 1, 1, 1, ())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DurableBudgetedProvider(
            FakeProvider(),
            object(),
            context,
            1,
            1,
            -1,
            (candidate,),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_concurrent_calls_get_unique_ordinals_and_accounting(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "concurrent.db")

    class ConcurrentProvider(FakeProvider):
        async def complete(self, messages, tools=(), **kwargs):
            self.calls.append((messages, tools, kwargs))
            await asyncio.sleep(0)
            return ModelResponse(
                "ok", usage=TokenUsage(1, 1), actual_provider="openai", actual_model="gpt-4o"
            )

    delegate = ConcurrentProvider()
    budgeted = wrapper(delegate, repo)
    await asyncio.gather(
        *(budgeted.complete([Message(Role.USER, str(index))], max_tokens=2) for index in range(10))
    )
    charges = await repo.list(owner_id="alice", project_id="project", run_id="run-1")
    assert [charge.ordinal for charge in charges] == list(range(10))
    assert len({charge.charge_id for charge in charges}) == 10
    assert all(charge.state is ChargeState.RECONCILED for charge in charges)
    await engine.dispose()


@pytest.mark.asyncio
async def test_base_exception_and_invalid_usage_fail_closed(tmp_path: Path) -> None:
    class FatalProviderError(BaseException):
        pass

    for run_id, delegate, expected in (
        ("fatal", RaisingProvider(FatalProviderError()), FatalProviderError),
        (
            "usage",
            FakeProvider(
                [
                    ModelResponse(
                        "bad",
                        usage=TokenUsage(1, 1),
                        actual_provider="openai",
                        actual_model="gpt-4o",
                    )
                ]
            ),
            IndeterminateModelCharge,
        ),
    ):
        repo, engine = await repository(tmp_path / f"{run_id}.db", run_id)
        if run_id == "usage":
            object.__setattr__(delegate.responses[0].usage, "input_tokens", None)
        with pytest.raises(expected):
            await wrapper(delegate, repo, run_id=run_id).complete([Message(Role.USER, "x")])
        charge = (await repo.list(owner_id="alice", project_id="project", run_id=run_id))[0]
        assert charge.state is ChargeState.INDETERMINATE
        await engine.dispose()


@pytest.mark.asyncio
async def test_response_is_fully_snapshotted_before_reconcile(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "snapshot.db")
    arguments = {"nested": ["original"]}
    structured = {"items": ["original"]}
    response = ModelResponse(
        tool_calls=(ToolCall("id", "tool", arguments),),
        usage=TokenUsage(11, 3),
        structured_output=structured,
        actual_provider="openai",
        actual_model="gpt-4o",
    )
    original_reconcile = repo.reconcile

    async def mutate_then_reconcile(*args, **kwargs):
        object.__setattr__(response.usage, "input_tokens", 999)
        arguments["nested"].append("mutated")
        structured["items"].append("mutated")
        return await original_reconcile(*args, **kwargs)

    repo.reconcile = mutate_then_reconcile  # type: ignore[method-assign]
    result = await wrapper(FakeProvider([response]), repo).complete([Message(Role.USER, "x")])
    assert result.usage.input_tokens == 11
    assert result.tool_calls[0].arguments == {"nested": ["original"]}
    assert result.structured_output == {"items": ["original"]}
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert charge.input_tokens == 11
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancellation_during_successful_reserve_releases_without_dispatch(
    tmp_path: Path,
) -> None:
    repo, engine = await repository(tmp_path / "reserve-cancel.db")
    original_reserve = repo.reserve_call
    committed = asyncio.Event()
    finish = asyncio.Event()

    async def delayed_return(*args, **kwargs):
        result = await original_reserve(*args, **kwargs)
        committed.set()
        await finish.wait()
        return result

    repo.reserve_call = delayed_return  # type: ignore[method-assign]
    delegate = FakeProvider()
    task = asyncio.create_task(wrapper(delegate, repo).complete([Message(Role.USER, "x")]))
    await committed.wait()
    task.cancel("reserve-cancel")
    finish.set()
    with pytest.raises(asyncio.CancelledError, match="reserve-cancel"):
        await task
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert charge.state is ChargeState.RELEASED
    assert not delegate.calls
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_commit_then_error_preserves_reconciled(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "commit-error.db")
    original_reconcile = repo.reconcile

    async def commit_then_error(*args, **kwargs):
        await original_reconcile(*args, **kwargs)
        raise RuntimeError("after commit")

    repo.reconcile = commit_then_error  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="after commit"):
        await wrapper(FakeProvider(), repo).complete([Message(Role.USER, "x")])
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert charge.state is ChargeState.RECONCILED
    await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_repository_failure_is_stable(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "cleanup-error.db")

    async def unsafe_get(*args, **kwargs):
        raise RuntimeError("secret raw input")

    repo.get = unsafe_get  # type: ignore[method-assign]
    with pytest.raises(DurableModelChargeStateError) as caught:
        await wrapper(RaisingProvider(RuntimeError("delegate")), repo).complete(
            [Message(Role.USER, "secret")]
        )
    assert str(caught.value) == "durable_model_charge_state_error"
    assert str(caught.value.__cause__) == "indeterminate_model_charge"
    await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_cleanup_cancellation_waits_and_preserves_first_identity(
    tmp_path: Path,
) -> None:
    repo, engine = await repository(tmp_path / "repeat-cancel.db")
    provider_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()
    original_mark = repo.mark_indeterminate

    class WaitingProvider(FakeProvider):
        async def complete(self, messages, tools=(), **kwargs):
            provider_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def delayed_mark(*args, **kwargs):
        cleanup_started.set()
        await finish_cleanup.wait()
        return await original_mark(*args, **kwargs)

    repo.mark_indeterminate = delayed_mark  # type: ignore[method-assign]
    task = asyncio.create_task(wrapper(WaitingProvider(), repo).complete([Message(Role.USER, "x")]))
    await provider_started.wait()
    task.cancel("first-cancellation")
    await cleanup_started.wait()
    task.cancel("second-cancellation")
    await asyncio.sleep(0)
    task.cancel("third-cancellation")
    await asyncio.sleep(0)
    finish_cleanup.set()
    with pytest.raises(asyncio.CancelledError, match="first-cancellation"):
        await task
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert charge.state is ChargeState.INDETERMINATE
    await engine.dispose()


@pytest.mark.asyncio
async def test_external_cancellation_is_not_converted_by_timeout_scope(tmp_path: Path) -> None:
    repo, engine = await repository(tmp_path / "timeout-cancel.db")
    provider_started = asyncio.Event()
    cleanup_started = asyncio.Event()
    finish_cleanup = asyncio.Event()
    original_mark = repo.mark_indeterminate

    class WaitingProvider(FakeProvider):
        async def complete(self, messages, tools=(), **kwargs):
            provider_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def delayed_mark(*args, **kwargs):
        cleanup_started.set()
        await finish_cleanup.wait()
        return await original_mark(*args, **kwargs)

    repo.mark_indeterminate = delayed_mark  # type: ignore[method-assign]

    timeout_scope: dict[str, asyncio.Timeout] = {}

    async def bounded_call() -> None:
        async with asyncio.timeout(None) as timeout:
            timeout_scope["value"] = timeout
            await wrapper(WaitingProvider(), repo).complete([Message(Role.USER, "x")])

    task = asyncio.create_task(bounded_call())
    await provider_started.wait()
    task.cancel("external-first")
    await cleanup_started.wait()
    timeout_scope["value"].reschedule(asyncio.get_running_loop().time() + 0.02)
    await asyncio.sleep(0.04)
    finish_cleanup.set()

    with pytest.raises(asyncio.CancelledError, match="external-first"):
        await task
    assert task.cancelled()
    charge = (await repo.list(owner_id="alice", project_id="project", run_id="run-1"))[0]
    assert charge.state is ChargeState.INDETERMINATE
    await engine.dispose()
