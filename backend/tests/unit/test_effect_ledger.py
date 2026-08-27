"""Effect identity and durable reservation ledger coverage."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.runtime.effect_ledger import (
    EffectIdentityInput,
    EffectState,
    bind_effect_identity,
)
from app.security.policy import ResourceKind, ResourcePattern, canonical_arguments_hash
from app.services.db_store import Base, EffectRow
from app.services.effect_ledger import EffectRepository, EffectStateConflict

_SECRET = b"effect-ledger-test-secret-is-at-least-32-bytes"


def identity(**changes: object) -> EffectIdentityInput:
    values: dict[str, object] = {
        "owner_id": "alice",
        "project_id": "project-a",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "tool_name": " Write_File ",
        "arguments": {"path": "/workspace/a", "body": {"b": 2, "a": 1}},
        "resources": (
            ResourcePattern(ResourceKind.HOST, "EXAMPLE.com."),
            ResourcePattern(ResourceKind.PATH, "/workspace/./a"),
        ),
        "input_schema": {"required": ["path"], "type": "object"},
        "tool_call_id": "provider-call-1",
    }
    values.update(changes)
    return EffectIdentityInput(**values)  # type: ignore[arg-type]


def test_identity_is_canonical_keyed_and_immutable() -> None:
    first = bind_effect_identity(identity(), _SECRET)
    reordered = bind_effect_identity(
        identity(
            arguments={"body": {"a": 1, "b": 2}, "path": "/workspace/a"},
            resources=tuple(reversed(identity().resources)),
            input_schema={"type": "object", "required": ["path"]},
            tool_call_id="a-different-provider-call",
        ),
        _SECRET,
    )
    assert first == reordered
    assert first.effect_id.startswith("eff_v1_")
    assert len(first.effect_id) == 71
    assert first.schema_hash == "b50a4c54e752cb9029e80bb58469d75be90d446ce455837b3c58d469acd130f7"
    with pytest.raises(FrozenInstanceError):
        first.effect_id = "different"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "bob"),
        ("project_id", "project-b"),
        ("run_id", "00000000-0000-0000-0000-000000000002"),
        ("tool_name", "read_file"),
        ("arguments", {"path": "/workspace/b"}),
        ("resources", (ResourcePattern(ResourceKind.PATH, "/workspace/b"),)),
        ("input_schema", {"type": "object", "properties": {"x": {"type": "string"}}}),
    ],
)
def test_each_bound_component_changes_identity(field: str, value: object) -> None:
    assert (
        bind_effect_identity(identity(), _SECRET).effect_id
        != bind_effect_identity(identity(**{field: value}), _SECRET).effect_id
    )


def test_identity_rejects_unsafe_inputs_and_hmac_hides_low_entropy_values() -> None:
    with pytest.raises(ValueError):
        identity(owner_id=" ")
    with pytest.raises(ValueError):
        identity(project_id="x" * 256)
    with pytest.raises(ValueError):
        identity(arguments={"x": float("nan")})
    with pytest.raises(TypeError):
        identity(input_schema={"x": object()})
    with pytest.raises(ValueError, match="duplicate"):
        identity(
            resources=(
                ResourcePattern(ResourceKind.HOST, "example.com"),
                ResourcePattern(ResourceKind.HOST, "EXAMPLE.COM."),
            )
        )
    with pytest.raises(ValueError, match="32"):
        bind_effect_identity(identity(), b"too-short")
    binding = bind_effect_identity(identity(arguments={"pin": "7"}), _SECRET)
    assert binding.effect_id.removeprefix("eff_v1_") != canonical_arguments_hash({"pin": "7"})
    assert (
        binding.effect_id
        != bind_effect_identity(identity(arguments={"pin": "7"}), b"x" * 32).effect_id
    )
    assert "workspace" not in repr(binding)
    assert "secret" not in repr(binding)


def test_identity_complexity_is_bounded_before_recursive_snapshotting() -> None:
    deeply_nested: object = "leaf"
    for _ in range(500):
        deeply_nested = [deeply_nested]
    with pytest.raises(ValueError, match="nesting depth"):
        identity(arguments={"deep": deeply_nested})

    with pytest.raises(ValueError, match="complex"):
        identity(arguments={"items": list(range(4097))})
    with pytest.raises(ValueError, match="string"):
        identity(arguments={"value": "x" * (16 * 1024 + 1)})
    with pytest.raises(ValueError, match="too long"):
        identity(arguments={"x" * (16 * 1024 + 1): 1})
    with pytest.raises(ValueError, match="canonical JSON"):
        identity(arguments={str(index): "x" * 16_000 for index in range(20)})
    with pytest.raises(ValueError, match="canonical JSON"):
        identity(input_schema={str(index): "x" * 16_000 for index in range(20)})


def test_identity_rejects_oversized_resources_and_non_unicode_scalar_text() -> None:
    resources = tuple(
        ResourcePattern(ResourceKind.PATH, f"/workspace/{index}") for index in range(65)
    )
    with pytest.raises(ValueError, match="resources"):
        identity(resources=resources)
    with pytest.raises(ValueError, match="resource pattern"):
        identity(resources=(ResourcePattern(ResourceKind.PATH, "/" + "x" * 2048),))

    for changes in (
        {"arguments": {"value": "\ud800"}},
        {"arguments": {"\ud800": "value"}},
        {"input_schema": {"value": "\ud800"}},
        {"owner_id": "\ud800"},
        {"project_id": "\ud800"},
        {"run_id": "\ud800"},
        {"tool_name": "\ud800"},
    ):
        with pytest.raises(ValueError, match="Unicode scalar"):
            identity(**changes)

    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cycles"):
        identity(arguments=cyclic)

    # Exercise the ledger's own validation if malformed data bypasses ResourcePattern.__post_init__.
    malformed = object.__new__(ResourcePattern)
    object.__setattr__(malformed, "kind", ResourceKind.PATH)
    object.__setattr__(malformed, "pattern", "\ud800")
    with pytest.raises(ValueError, match="Unicode scalar"):
        identity(resources=(malformed,))


@pytest.fixture
async def ledger(tmp_path):
    database = tmp_path / "effects.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield EffectRepository(sessions), sessions, database
    await engine.dispose()


async def test_concurrent_reserve_has_exactly_one_executor_and_safe_rows(ledger) -> None:
    repository, sessions, database = ledger
    binding = bind_effect_identity(identity(), _SECRET)
    results = await asyncio.gather(*(repository.reserve(binding) for _ in range(12)))
    assert sum(result.should_execute for result in results) == 1
    assert {result.state for result in results} == {EffectState.RESERVED}

    async with sessions() as session:
        row = (await session.execute(select(EffectRow))).scalar_one()
        assert row.effect_id == binding.effect_id
        assert row.tool_name == "write_file"
        assert row.schema_hash == binding.schema_hash
    connection = sqlite3.connect(database)
    values = tuple(
        str(value) for row in connection.execute("SELECT * FROM effects") for value in row
    )
    connection.close()
    serialized = " ".join(values)
    assert "/workspace" not in serialized
    assert "provider-call" not in serialized
    assert _SECRET.decode() not in serialized


@pytest.mark.parametrize("terminal", ["commit", "fail", "mark_indeterminate"])
async def test_duplicate_terminal_states_never_execute(ledger, terminal: str) -> None:
    repository, _, _ = ledger
    binding = bind_effect_identity(identity(), _SECRET)
    assert (await repository.reserve(binding)).should_execute
    if terminal == "commit":
        await repository.commit(binding.effect_id, "a" * 64, 4)
    else:
        await getattr(repository, terminal)(binding.effect_id, "safe_code")
    duplicate = await repository.reserve(binding)
    assert not duplicate.should_execute
    expected = {
        "commit": EffectState.COMMITTED,
        "fail": EffectState.FAILED,
        "mark_indeterminate": EffectState.INDETERMINATE,
    }
    assert duplicate.state is expected[terminal]


async def test_terminal_transition_race_has_one_winner(ledger) -> None:
    repository, _, _ = ledger
    binding = bind_effect_identity(identity(), _SECRET)
    await repository.reserve(binding)
    outcomes = await asyncio.gather(
        repository.commit(binding.effect_id, "b" * 64, 10),
        repository.fail(binding.effect_id, "tool_failed"),
        return_exceptions=True,
    )
    assert sum(result is None for result in outcomes) == 1
    assert sum(isinstance(result, EffectStateConflict) for result in outcomes) == 1


async def test_output_size_must_fit_database_bigint_and_preserves_reservation(ledger) -> None:
    repository, _, _ = ledger
    binding = bind_effect_identity(identity(), _SECRET)
    await repository.reserve(binding)
    for invalid_size in (True, -1, 2**63):
        with pytest.raises(ValueError, match="BIGINT"):
            await repository.commit(binding.effect_id, "a" * 64, invalid_size)
    record = await repository.get(
        binding.effect_id,
        owner_id=binding.owner_id,
        project_id=binding.project_id,
        run_id=binding.run_id,
    )
    assert record is not None and record.state is EffectState.RESERVED


async def test_insert_winner_does_not_reread_adversarially_changed_state(ledger) -> None:
    repository, sessions, _ = ledger
    async with sessions() as session:
        await session.execute(
            text(
                "CREATE TRIGGER mutate_effect_after_insert AFTER INSERT ON effects "
                "BEGIN UPDATE effects SET state = 'failed' WHERE effect_id = NEW.effect_id; END"
            )
        )
        await session.commit()

    reservation = await repository.reserve(bind_effect_identity(identity(), _SECRET))
    assert reservation.should_execute
    assert reservation.state is EffectState.RESERVED


async def test_stale_recovery_and_owner_scoped_reads(ledger) -> None:
    repository, _, _ = ledger
    old = datetime.now(tz=UTC) - timedelta(hours=2)
    alice = bind_effect_identity(identity(), _SECRET)
    bob = bind_effect_identity(identity(owner_id="bob"), _SECRET)
    await repository.reserve(alice, now=old)
    await repository.reserve(bob, now=old)
    assert (
        await repository.recover_stale_reservations(datetime.now(tz=UTC) - timedelta(hours=1)) == 2
    )
    assert not (await repository.reserve(alice)).should_execute

    record = await repository.get(
        alice.effect_id,
        owner_id="alice",
        project_id="project-a",
        run_id=identity().run_id,
    )
    assert record is not None and record.state is EffectState.INDETERMINATE
    assert (
        await repository.get(
            alice.effect_id,
            owner_id="bob",
            project_id="project-a",
            run_id=identity().run_id,
        )
        is None
    )
    assert (
        len(
            await repository.list(
                owner_id="alice", project_id="project-a", run_id=identity().run_id
            )
        )
        == 1
    )
