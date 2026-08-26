"""Execution and durability tests for the isolated verifier child."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import select

from app.delegation import (
    ChildVerificationRequest,
    ChildVerificationStatus,
    ClaimInput,
    EvidenceSlice,
    EvidenceVerifierSpecialist,
    TransientVerifierError,
    VerificationBudget,
    VerificationReasonCode,
)
from app.runtime.models import Message, ModelResponse, TokenUsage, ToolDefinition
from app.security.persistence_redactor import PersistenceRedactor
from app.services.db_store import DatabaseStore, RunRow, RuntimeEventRow
from app.services.run_ledger import RunRepository

HASH = "a" * 64


def make_request(**changes: Any) -> ChildVerificationRequest:
    values: dict[str, Any] = {
        "child_id": "child-1",
        "parent_run_id": "parent-1",
        "user_id": "user-1",
        "project_id": "project-1",
        "policy_id": "policy-1",
        "model": "model-1",
        "claims": (ClaimInput("claim-1", HASH, "the claim", ("ev-1",)),),
        "evidence": (EvidenceSlice("ev-1", "doc-1", "chunk-1", HASH, "the quote"),),
        "budget": VerificationBudget(2_000, 123, 1.0),
    }
    values.update(changes)
    return ChildVerificationRequest(**values)


def response(*, evidence_id: str = "ev-1") -> ModelResponse:
    return ModelResponse(
        json.dumps(
            {
                "verdicts": [
                    {
                        "claim_id": "claim-1",
                        "status": "supported",
                        "reason_code": "evidence_supports",
                        "confidence": 0.9,
                        "evidence_ids": [evidence_id],
                    }
                ]
            }
        ),
        usage=TokenUsage(20, 5),
    )


class Provider:
    def __init__(self, outcomes: list[ModelResponse | BaseException]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[Sequence[Message], Sequence[ToolDefinition], int]] = []

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del response_format
        self.calls.append((messages, tools, max_tokens))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BlockingProvider(Provider):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()

    async def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
        *,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> ModelResponse:
        del messages, tools, max_tokens, response_format
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.fixture
async def ledger(tmp_path: Any):
    store = DatabaseStore(f"sqlite+aiosqlite:///{tmp_path / 'verifier.db'}")
    await store.initialize()
    repository = RunRepository(store.session_factory, PersistenceRedactor())
    await repository.ensure_run(
        run_id="parent-1",
        user_id="user-1",
        project_id="project-1",
        conversation_id="conversation",
        correlation_id="correlation",
        provider="mock",
        model="model",
    )
    yield store, repository
    await store.close()


@pytest.mark.asyncio
async def test_valid_call_is_isolated_bounded_and_durable(ledger: Any) -> None:
    store, repository = ledger
    provider = Provider([response()])
    request = make_request()
    result = await EvidenceVerifierSpecialist(provider, repository, PersistenceRedactor()).verify(
        request
    )

    assert result.status is ChildVerificationStatus.COMPLETED
    assert result.usage == TokenUsage(20, 5)
    assert len(provider.calls) == 1
    messages, tools, maximum = provider.calls[0]
    assert tools == () and maximum == 123
    encoded = "\n".join(message.content for message in messages)
    assert "the claim" in encoded and "the quote" in encoded
    assert "SENTINEL_PARENT_HISTORY" not in encoded
    assert "policy-1" not in encoded and "parent-1" not in encoded

    restarted = RunRepository(store.session_factory, PersistenceRedactor())
    run = await restarted.get("user-1", "child-1")
    events = await restarted.events("user-1", "child-1")
    assert run is not None and run.parent_run_id == "parent-1"
    assert (run.status, run.total_tokens, run.cost_usd) == ("completed", 25, 0.0)
    assert events is not None
    assert [event.kind for event in events.items] == [
        "delegation_requested",
        "delegation_completed",
        "run_stopped",
    ]
    async with store.session_factory() as session:
        raw = " ".join(
            await session.scalars(
                select(RuntimeEventRow.payload).where(RuntimeEventRow.run_id == "child-1")
            )
        )
    assert "the claim" not in raw and "the quote" not in raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_response", "reason"),
    [
        (ModelResponse("not json"), VerificationReasonCode.MALFORMED_RESPONSE),
        (response(evidence_id="foreign"), VerificationReasonCode.MALFORMED_RESPONSE),
    ],
)
async def test_malformed_and_foreign_evidence_fail_closed(
    ledger: Any, model_response: ModelResponse, reason: VerificationReasonCode
) -> None:
    _, repository = ledger
    result = await EvidenceVerifierSpecialist(
        Provider([model_response]), repository, PersistenceRedactor()
    ).verify(make_request())
    assert result.status is ChildVerificationStatus.FAILED
    assert result.verdicts[0].status.value == "escalate"
    assert result.verdicts[0].reason_code is reason


@pytest.mark.asyncio
async def test_budget_prevents_call_and_retry_is_bounded(ledger: Any) -> None:
    _, repository = ledger
    blocked = Provider([response()])
    result = await EvidenceVerifierSpecialist(blocked, repository, PersistenceRedactor()).verify(
        make_request(child_id="budget-child", budget=VerificationBudget(1, 10, 1.0))
    )
    assert result.verdicts[0].reason_code is VerificationReasonCode.BUDGET_EXCEEDED
    assert blocked.calls == []

    retrying = Provider([TransientVerifierError("temporary"), response()])
    result = await EvidenceVerifierSpecialist(retrying, repository, PersistenceRedactor()).verify(
        make_request(child_id="retry-child", budget=VerificationBudget(4_000, 123, 1.0, retries=1))
    )
    assert result.status is ChildVerificationStatus.COMPLETED
    assert len(retrying.calls) == 2
    assert [call[2] for call in retrying.calls] == [123, 123]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("usage", "budget"),
    [
        (TokenUsage(2_001, 1), VerificationBudget(2_000, 123, 1.0)),
        (TokenUsage(20, 124), VerificationBudget(2_000, 123, 1.0)),
        # Providers can report usage aggregated across internal retries.
        (TokenUsage(2_001, 124), VerificationBudget(2_000, 123, 1.0, retries=1)),
    ],
)
async def test_actual_provider_usage_over_budget_discards_verdict(
    ledger: Any, usage: TokenUsage, budget: VerificationBudget
) -> None:
    _, repository = ledger
    normal = response()
    provider = Provider([ModelResponse(normal.content, usage=usage)])

    result = await EvidenceVerifierSpecialist(provider, repository, PersistenceRedactor()).verify(
        make_request(
            child_id=f"oversized-{usage.input_tokens}-{usage.output_tokens}", budget=budget
        )
    )

    assert result.status is ChildVerificationStatus.FAILED
    assert result.usage == usage
    assert result.verdicts[0].status.value == "escalate"
    assert result.verdicts[0].reason_code is VerificationReasonCode.BUDGET_EXCEEDED
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_timeout_and_cancellation_are_terminal(ledger: Any) -> None:
    _, repository = ledger
    timeout_provider = BlockingProvider()
    result = await EvidenceVerifierSpecialist(
        timeout_provider, repository, PersistenceRedactor()
    ).verify(make_request(child_id="timeout-child", budget=VerificationBudget(2_000, 10, 0.1)))
    assert result.status is ChildVerificationStatus.TIMEOUT
    timeout_run = await repository.get("user-1", "timeout-child")
    assert timeout_run is not None and timeout_run.status == "failed"

    cancel_provider = BlockingProvider()
    task = asyncio.create_task(
        EvidenceVerifierSpecialist(cancel_provider, repository, PersistenceRedactor()).verify(
            make_request(child_id="cancel-child")
        )
    )
    await cancel_provider.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    cancel_run = await repository.get("user-1", "cancel-child")
    assert cancel_run is not None and cancel_run.status == "cancelled"


@pytest.mark.asyncio
async def test_foreign_parent_is_rejected(ledger: Any) -> None:
    store, repository = ledger
    await repository.ensure_run(
        run_id="foreign-parent",
        user_id="other-user",
        project_id="project-1",
        conversation_id="conversation",
        correlation_id="correlation",
        provider="mock",
        model="model",
    )
    with pytest.raises(ValueError, match="parent run owner mismatch"):
        await EvidenceVerifierSpecialist(
            Provider([response()]), repository, PersistenceRedactor()
        ).verify(make_request(parent_run_id="foreign-parent"))
    async with store.session_factory() as session:
        child = await session.scalar(select(RunRow).where(RunRow.run_id == "child-1"))
    assert child is None


@pytest.mark.asyncio
async def test_missing_parent_is_rejected_before_child_or_event(ledger: Any) -> None:
    store, repository = ledger
    with pytest.raises(ValueError, match="parent run does not exist"):
        await EvidenceVerifierSpecialist(
            Provider([response()]), repository, PersistenceRedactor()
        ).verify(make_request(parent_run_id="missing-parent"))
    async with store.session_factory() as session:
        child = await session.scalar(select(RunRow).where(RunRow.run_id == "child-1"))
        events = tuple(
            await session.scalars(
                select(RuntimeEventRow).where(RuntimeEventRow.run_id == "child-1")
            )
        )
    assert child is None and events == ()
