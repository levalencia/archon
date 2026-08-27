"""Live factory and runtime wiring for durable monetary budgets."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.config import Settings
from app.observability.cost_tracker import UnknownModelPricing
from app.observability.log_buffer import OwnerLogBuffer
from app.runtime import AgentEventKind, AgentRuntime, Message, RecordingEventSink, Role, StopReason
from app.runtime.factory import RunContext, _pricing_candidates, create_chat_runtime
from app.runtime.models import ModelResponse
from app.runtime.monetary_budget import (
    DuplicateModelCharge,
    DurableBudgetedProvider,
    IndeterminateModelCharge,
    ModelBudgetExhausted,
    usd_limit_to_nusd,
)
from app.security.persistence_redactor import PersistenceRedactor


class TextProvider:
    async def complete(
        self,
        messages,
        tools=(),
        *,
        max_tokens=4096,
        response_contract=None,
        response_format=None,
    ):
        del messages, tools, max_tokens, response_contract, response_format
        return ModelResponse(content="ok")


class RaisingBudgetProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def complete(self, messages, tools=(), *, max_tokens=4096):
        del messages, tools, max_tokens
        raise self.error


class NoTools:
    def definitions(self):
        return ()

    async def execute(self, call):
        raise AssertionError(call)


class FactoryRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory


@pytest.mark.unit
def test_usd_limit_conversion_is_exact_and_bounded() -> None:
    assert usd_limit_to_nusd(Decimal("1.000000001")) == 1_000_000_001
    assert usd_limit_to_nusd(Decimal("0")) == 0
    with pytest.raises(ValueError, match="nine decimal"):
        usd_limit_to_nusd(Decimal("0.0000000001"))


@pytest.mark.unit
def test_pricing_candidates_are_deduplicated_and_fail_closed() -> None:
    settings = Settings(
        llm_provider="mock",
        llm_model="mock-model",
        llm_fallback_providers="mock,unknown,mock",
    )
    candidates = _pricing_candidates(settings)
    assert [(item.provider, item.model) for item in candidates] == [("mock", "mock-model")]

    with pytest.raises(UnknownModelPricing):
        _pricing_candidates(Settings(llm_provider="openai", llm_model="unpriced-model"))


@pytest.mark.unit
def test_factory_wraps_only_when_durable_budget_is_enabled(tmp_path) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'factory.db'}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    context = RunContext("alice", "conversation", "run-1", "correlation", "project")
    common: dict[str, Any] = dict(
        context=context,
        tools=NoTools(),
        repository=FactoryRepository(sessions),
        exporter=None,
        redactor=PersistenceRedactor(),
        log_buffer=OwnerLogBuffer(),
    )

    plain = TextProvider()
    disabled = create_chat_runtime(
        provider=plain,
        settings=Settings(llm_provider="mock", llm_model="mock-model"),
        **common,
    )
    assert disabled._model is plain

    enabled = create_chat_runtime(
        provider=plain,
        settings=Settings(
            llm_provider="mock",
            llm_model="mock-model",
            durable_monetary_budget_enabled=True,
            agent_run_budget_usd=Decimal("1"),
            agent_project_budget_usd=Decimal("2"),
        ),
        **common,
    )
    assert isinstance(enabled._model, DurableBudgetedProvider)
    assert enabled._model.context.run_id == "run-1"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ModelBudgetExhausted(), StopReason.MONETARY_BUDGET_EXHAUSTED),
        (DuplicateModelCharge(), StopReason.MODEL_CHARGE_DUPLICATE),
        (IndeterminateModelCharge(), StopReason.MODEL_CHARGE_INDETERMINATE),
    ],
)
async def test_runtime_maps_budget_errors_to_safe_terminal_events(
    error: Exception, reason: StopReason
) -> None:
    events = RecordingEventSink()
    result = await AgentRuntime(RaisingBudgetProvider(error), NoTools(), events=events).run(
        [Message(Role.USER, "go")]
    )

    assert result.stop_reason is reason
    assert result.error == error.code  # type: ignore[attr-defined]
    blocked = next(event for event in events.events if event.kind is AgentEventKind.BUDGET_BLOCKED)
    assert blocked.data == {"code": error.code, "stop_reason": reason.value}  # type: ignore[attr-defined]
