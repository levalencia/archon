"""Reconcile the six pre-Alembic core tables at the forward head.

Revision ID: 20260902_22
Revises: 20260901_21

Early development created these tables through SQLAlchemy ``create_all``.
Fresh PostgreSQL databases and databases stamped by the historical Alembic
chain may therefore lack them.  This forward reconciliation adopts a complete
legacy schema or creates each missing table.  Downgrade deliberately preserves
core data because Alembic did not originally own legacy tables.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

from alembic import context, op

revision: str = "20260902_22"
down_revision: str | None = "20260901_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


class ColumnContract(NamedTuple):
    family: str
    nullable: bool
    length: int | None = None
    timezone: bool | None = None
    autoincrement: bool = False


# ---------------------------------------------------------------------------
# Known historical server-defaults from pre-Alembic ``create_all`` on
# PostgreSQL.  These are safe to accept during adoption because they mirror
# the Python-level Column(default=…) values that were active when the
# retained production database was originally created.  Any default string
# NOT in this set still triggers fail-closed RuntimeError.
# ---------------------------------------------------------------------------
_KNOWN_LEGACY_SERVER_DEFAULTS: dict[str, dict[str, frozenset[str]]] = {
    "users": {
        "email": frozenset({"''::character varying"}),
        "is_admin": frozenset({"0"}),
    },
    "conversations": {
        "title": frozenset({"'New Conversation'::character varying"}),
        "user_id": frozenset({"'default'::character varying"}),
        "is_active": frozenset({"1"}),
    },
    "audit_entries": {
        "result": frozenset({"'success'::character varying"}),
        "security_level": frozenset({"'info'::character varying"}),
    },
    "artifacts": {
        "version": frozenset({"1"}),
    },
}


_COLUMN_CONTRACTS: dict[str, dict[str, ColumnContract]] = {
    "users": {
        "id": ColumnContract("varchar", False, 36),
        "username": ColumnContract("varchar", False, 50),
        "email": ColumnContract("varchar", False, 320),
        "password_hash": ColumnContract("text", False),
        "is_admin": ColumnContract("integer", False),
    },
    "api_keys": {
        "id": ColumnContract("varchar", False, 36),
        "key_hash": ColumnContract("varchar", False, 64),
        "user_id": ColumnContract("varchar", False, 36),
        "name": ColumnContract("varchar", False, 100),
    },
    "conversations": {
        "id": ColumnContract("varchar", False, 36),
        "title": ColumnContract("varchar", False, 200),
        "user_id": ColumnContract("varchar", False, 36),
        "created_at": ColumnContract("datetime", True, timezone=True),
        "updated_at": ColumnContract("datetime", True, timezone=True),
        "is_active": ColumnContract("integer", True),
    },
    "messages": {
        "id": ColumnContract("integer", False, autoincrement=True),
        "conversation_id": ColumnContract("varchar", False, 36),
        "role": ColumnContract("varchar", False, 20),
        "content": ColumnContract("text", False),
        "created_at": ColumnContract("datetime", True, timezone=True),
    },
    "audit_entries": {
        "id": ColumnContract("integer", False, autoincrement=True),
        "timestamp": ColumnContract("varchar", False, 30),
        "agent_id": ColumnContract("varchar", False, 100),
        "action": ColumnContract("varchar", False, 100),
        "resource": ColumnContract("varchar", False, 500),
        "parameters": ColumnContract("text", True),
        "result": ColumnContract("varchar", True, 50),
        "security_level": ColumnContract("varchar", True, 20),
        "correlation_id": ColumnContract("varchar", True, 36),
    },
    "artifacts": {
        "id": ColumnContract("varchar", False, 36),
        "conversation_id": ColumnContract("varchar", False, 36),
        "message_id": ColumnContract("varchar", True, 36),
        "title": ColumnContract("varchar", False, 200),
        "artifact_type": ColumnContract("varchar", False, 20),
        "language": ColumnContract("varchar", True, 20),
        "content": ColumnContract("text", False),
        "version": ColumnContract("integer", True),
        "created_at": ColumnContract("datetime", True, timezone=True),
    },
}

_INDEX_CONTRACTS: dict[str, dict[str, tuple[tuple[str, ...], bool]]] = {
    "users": {"ix_users_username": (("username",), True)},
    "api_keys": {
        "ix_api_keys_key_hash": (("key_hash",), True),
        "ix_api_keys_user_id": (("user_id",), False),
    },
    "conversations": {},
    "messages": {"ix_messages_conversation_id": (("conversation_id",), False)},
    "audit_entries": {"ix_audit_entries_correlation_id": (("correlation_id",), False)},
    "artifacts": {"ix_artifacts_conversation_id": (("conversation_id",), False)},
}

# ---------------------------------------------------------------------------
# Historical PostgreSQL uniqueness representation.
#
# Pre-Alembic ``create_all`` on PostgreSQL created both a plain (non-unique)
# index *and* a separate UNIQUE constraint for columns with ``unique=True``
# on the ORM model.  The Inspector sees the plain index as non-unique and
# reports the UNIQUE constraint separately via ``get_unique_constraints``.
#
# Mapping: index_name -> required_unique_constraint_name
# When the index is found as non-unique we accept it only if the matching
# named UNIQUE constraint exists on the same columns.  A non-unique index
# without the companion constraint fails closed.
# ---------------------------------------------------------------------------
_HISTORICAL_PG_UNIQUE_PAIRS: dict[str, dict[str, str]] = {
    "users": {"ix_users_username": "uq_users_username"},
    "api_keys": {"ix_api_keys_key_hash": "uq_api_keys_key_hash"},
}


def _type_contract(
    type_: sa.types.TypeEngine, dialect_name: str
) -> tuple[str, int | None, bool | None]:
    if isinstance(type_, sa.Text):
        return ("text", None, None)
    if isinstance(type_, sa.CHAR):
        return ("char", type_.length, None)
    if isinstance(type_, sa.String):
        return ("varchar", type_.length, None)
    if isinstance(type_, sa.SmallInteger):
        return ("smallint", None, None)
    if isinstance(type_, sa.BigInteger):
        return ("bigint", None, None)
    if isinstance(type_, sa.Integer):
        return ("integer", None, None)
    if isinstance(type_, sa.DateTime):
        timezone = bool(type_.timezone) if dialect_name == "postgresql" else None
        return ("datetime", None, timezone)
    return (type(type_).__name__.lower(), None, None)


def _validate_legacy_table(inspector: Inspector, table_name: str) -> None:
    expected_columns = _COLUMN_CONTRACTS[table_name]
    reflected = {column["name"]: column for column in inspector.get_columns(table_name)}
    if set(reflected) != set(expected_columns):
        raise RuntimeError(
            f"legacy {table_name} column contract mismatch: "
            f"expected={sorted(expected_columns)!r} actual={sorted(reflected)!r}"
        )
    dialect_name = inspector.bind.dialect.name
    for column_name, expected in expected_columns.items():
        actual = reflected[column_name]
        expected_timezone = expected.timezone if dialect_name == "postgresql" else None
        expected_type = (expected.family, expected.length, expected_timezone)
        actual_type = _type_contract(actual["type"], dialect_name)
        if actual_type != expected_type or bool(actual["nullable"]) != expected.nullable:
            raise RuntimeError(
                f"legacy {table_name}.{column_name} type/nullability contract mismatch: "
                f"expected={(expected_type, expected.nullable)!r} "
                f"actual={(actual_type, bool(actual['nullable']))!r}"
            )
        server_default = actual.get("default")
        generated_identity = (
            expected.autoincrement
            and isinstance(server_default, str)
            and server_default.startswith("nextval(")
        )
        known_legacy = _KNOWN_LEGACY_SERVER_DEFAULTS.get(table_name, {}).get(
            column_name, frozenset()
        )
        accepted_legacy = isinstance(server_default, str) and server_default in known_legacy
        if server_default is not None and not generated_identity and not accepted_legacy:
            raise RuntimeError(
                f"legacy {table_name}.{column_name} server-default contract mismatch: "
                f"actual={server_default!r}"
            )
        if (
            dialect_name == "postgresql"
            and expected.autoincrement
            and not bool(actual.get("autoincrement"))
            and not generated_identity
        ):
            raise RuntimeError(f"legacy {table_name}.{column_name} autoincrement contract mismatch")

    primary_key = tuple(inspector.get_pk_constraint(table_name)["constrained_columns"])
    if primary_key != ("id",):
        raise RuntimeError(
            f"legacy {table_name} primary-key contract mismatch: actual={primary_key!r}"
        )
    actual_indexes = {
        str(index["name"]): (tuple(index["column_names"]), bool(index["unique"]))
        for index in inspector.get_indexes(table_name)
    }
    # Build unique-constraint lookup for historical PostgreSQL pair validation.
    pg_unique_pairs = _HISTORICAL_PG_UNIQUE_PAIRS.get(table_name, {})
    unique_constraints: dict[str, tuple[str, ...]] | None = None
    if pg_unique_pairs:
        unique_constraints = {
            str(uc["name"]): tuple(uc["column_names"])
            for uc in inspector.get_unique_constraints(table_name)
            if uc.get("name")
        }
    for index_name, expected_index in _INDEX_CONTRACTS[table_name].items():
        actual = actual_indexes.get(index_name)
        if actual == expected_index:
            continue  # Canonical form matches exactly.
        # Accept historical PostgreSQL form: nonunique ix + named UNIQUE constraint.
        expected_cols, expected_unique = expected_index
        required_uc_name = pg_unique_pairs.get(index_name)
        if (
            expected_unique
            and required_uc_name is not None
            and actual is not None
            and actual == (expected_cols, False)
            and unique_constraints is not None
            and unique_constraints.get(required_uc_name) == expected_cols
        ):
            continue  # Historical pair satisfies uniqueness.
        raise RuntimeError(
            f"legacy {table_name} index contract mismatch for {index_name}: "
            f"expected={expected_index!r} actual={actual!r}"
        )
    if inspector.get_foreign_keys(table_name):
        raise RuntimeError(f"legacy {table_name} foreign-key contract mismatch")


def _adopt_or_create(table_name: str, create: Callable[[], None]) -> None:
    if context.is_offline_mode():
        raise RuntimeError("core table reconciliation requires online Alembic schema inspection")
    inspector = sa.inspect(op.get_bind())
    if table_name in inspector.get_table_names():
        _validate_legacy_table(inspector, table_name)
        return
    create()


def _create_users() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def _create_api_keys() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], unique=False)


def _create_conversations() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_messages() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)


def _create_audit_entries() -> None:
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.String(length=30), nullable=False),
        sa.Column("agent_id", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource", sa.String(length=500), nullable=False),
        sa.Column("parameters", sa.Text(), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=True),
        sa.Column("security_level", sa.String(length=20), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_entries_correlation_id",
        "audit_entries",
        ["correlation_id"],
        unique=False,
    )


def _create_artifacts() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("artifact_type", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_artifacts_conversation_id",
        "artifacts",
        ["conversation_id"],
        unique=False,
    )


def upgrade() -> None:
    for table_name, create in (
        ("users", _create_users),
        ("api_keys", _create_api_keys),
        ("conversations", _create_conversations),
        ("messages", _create_messages),
        ("audit_entries", _create_audit_entries),
        ("artifacts", _create_artifacts),
    ):
        _adopt_or_create(table_name, create)


def downgrade() -> None:
    """Preserve pre-Alembic core tables and their data below the reconciliation head."""
    pass
