"""Durable at-most-once orchestration for effectful tool executions."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.runtime.effect_executor import (
    DurableEffectToolExecutor,
    EffectRunContext,
    IndeterminateToolEffectError,
)
from app.runtime.effect_ledger import EffectState
from app.runtime.models import ToolCall
from app.security.policy import ResourceKind, ResourcePattern, RiskClass
from app.services.db_store import Base
from app.services.effect_ledger import EffectRepository
from app.tools.registry import SecureToolRegistry


async def executor(tmp_path, registry: SecureToolRegistry, run_id: str = "run-1"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / (run_id + '.db')}")
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = EffectRepository(sessions)
    wrapped = DurableEffectToolExecutor(
        registry,
        repository,
        EffectRunContext("alice", "project", run_id),
        b"e" * 32,
    )
    return wrapped, repository, engine


def schema() -> dict:
    return {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_effectful_duplicate_executes_once_and_returns_safe_tombstone(tmp_path) -> None:
    calls: list[str] = []

    async def write(value: str) -> dict[str, object]:
        calls.append(value)
        return {"written": value}

    registry = SecureToolRegistry()
    registry.register(
        "write", write, input_schema=schema(), risk_classes=frozenset({RiskClass.WRITE})
    )
    wrapped, repository, engine = await executor(tmp_path, registry)

    first = await wrapped.execute(ToolCall("call-1", "write", {"value": "x"}))
    duplicate = await wrapped.execute(ToolCall("call-2", "write", {"value": "x"}))

    assert first == {"written": "x"}
    assert duplicate["status"] == "duplicate_effect_blocked"
    assert duplicate["effect_state"] == "committed"
    assert "effect_id" not in duplicate
    assert calls == ["x"]
    records = await repository.list(owner_id="alice", project_id="project", run_id="run-1")
    assert len(records) == 1 and records[0].state is EffectState.COMMITTED
    await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_arguments_and_run_scope_create_distinct_effects(tmp_path) -> None:
    calls: list[str] = []

    async def write(value: str) -> dict[str, object]:
        calls.append(value)
        return {"written": value}

    registry = SecureToolRegistry()
    registry.register(
        "write", write, input_schema=schema(), risk_classes=frozenset({RiskClass.WRITE})
    )
    first, _, first_engine = await executor(tmp_path, registry, "run-1")
    second, _, second_engine = await executor(tmp_path, registry, "run-2")

    await first.execute(ToolCall("a", "write", {"value": "x"}))
    await first.execute(ToolCall("b", "write", {"value": "y"}))
    await second.execute(ToolCall("c", "write", {"value": "x"}))
    assert calls == ["x", "y", "x"]
    await first_engine.dispose()
    await second_engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_only_tools_bypass_effect_ledger(tmp_path) -> None:
    calls = 0

    async def read(value: str) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"value": value}

    registry = SecureToolRegistry()
    registry.register("read", read, input_schema=schema(), risk_classes=frozenset({RiskClass.READ}))
    wrapped, repository, engine = await executor(tmp_path, registry)
    call = ToolCall("same", "read", {"value": "x"})

    await wrapped.execute(call)
    await wrapped.execute(call)
    assert calls == 2
    assert await repository.list(owner_id="alice", project_id="project", run_id="run-1") == ()
    await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_declared_idempotency_key_is_hidden_and_handed_off(tmp_path) -> None:
    received: list[str] = []

    async def send(value: str, idempotency_key: str) -> dict[str, object]:
        received.append(idempotency_key)
        return {"sent": value}

    registry = SecureToolRegistry()
    registry.register(
        "send",
        send,
        input_schema=schema(),
        risk_classes=frozenset({RiskClass.EXTERNAL_SIDE_EFFECT}),
        idempotency_key_parameter="idempotency_key",
    )
    wrapped, _, engine = await executor(tmp_path, registry)

    definitions = registry.definitions()
    assert "idempotency_key" not in definitions[0].input_schema.get("properties", {})
    await wrapped.execute(ToolCall("call", "send", {"value": "x"}))
    assert len(received) == 1 and received[0].startswith("eff_v1_")
    await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handler_failure_becomes_indeterminate_and_never_reexecutes(tmp_path) -> None:
    calls = 0

    async def fail(value: str) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise RuntimeError("raw downstream secret")

    registry = SecureToolRegistry()
    registry.register(
        "send", fail, input_schema=schema(), risk_classes=frozenset({RiskClass.WRITE})
    )
    wrapped, repository, engine = await executor(tmp_path, registry)
    call = ToolCall("first", "send", {"value": "x"})

    with pytest.raises(IndeterminateToolEffectError, match="^indeterminate_tool_effect$") as caught:
        await wrapped.execute(call)
    assert "raw downstream secret" not in str(caught.value)
    duplicate = await wrapped.execute(ToolCall("second", "send", {"value": "x"}))
    assert duplicate["effect_state"] == "indeterminate"
    assert calls == 1
    records = await repository.list(owner_id="alice", project_id="project", run_id="run-1")
    assert records[0].state is EffectState.INDETERMINATE
    assert records[0].failure_code == "dispatch_interrupted"
    await engine.dispose()


@pytest.mark.unit
def test_positional_only_idempotency_parameter_is_rejected() -> None:
    def send(idempotency_key, /, value: str) -> dict[str, object]:
        return {"value": value, "key": idempotency_key}

    registry = SecureToolRegistry()
    with pytest.raises(ValueError, match="handler does not accept"):
        registry.register(
            "send",
            send,
            input_schema=schema(),
            effectful=True,
            idempotency_key_parameter="idempotency_key",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unsupported_output_is_sanitized_and_indeterminate(tmp_path) -> None:
    async def unsafe(value: str) -> dict[str, object]:
        del value
        return {"unsafe": object()}

    registry = SecureToolRegistry()
    registry.register(
        "unsafe",
        unsafe,
        input_schema=schema(),
        effectful=True,
        risk_classes=frozenset({RiskClass.WRITE}),
    )
    wrapped, repository, engine = await executor(tmp_path, registry)

    with pytest.raises(IndeterminateToolEffectError, match="^indeterminate_tool_effect$"):
        await wrapped.execute(ToolCall("call", "unsafe", {"value": "x"}))
    records = await repository.list(owner_id="alice", project_id="project", run_id="run-1")
    assert records[0].state is EffectState.INDETERMINATE
    await engine.dispose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_effect_identity_reuses_exactly_approved_resources(tmp_path) -> None:
    resolutions = 0

    def resources(_arguments) -> tuple[ResourcePattern, ...]:
        nonlocal resolutions
        resolutions += 1
        return (ResourcePattern(ResourceKind.HOST, f"host-{resolutions}.example"),)

    async def send(value: str) -> dict[str, object]:
        return {"sent": value}

    registry = SecureToolRegistry()
    registry.register(
        "send",
        send,
        input_schema=schema(),
        risk_classes=frozenset({RiskClass.EXTERNAL_SIDE_EFFECT}),
        resource_resolver=resources,
    )
    wrapped, _, engine = await executor(tmp_path, registry)
    call = ToolCall("call", "send", {"value": "x"})

    approved = wrapped.policy_request(call)
    assert approved.resources[0].pattern == "host-1.example"
    await wrapped.execute(call)
    assert resolutions == 1
    await engine.dispose()
