"""Tests for historical PostgreSQL index uniqueness validation in core table reconciliation.

Simulates PostgreSQL Inspector responses for the two accepted forms:
1. Canonical: unique index directly (ix_users_username unique=True)
2. Historical PG: nonunique ix + named UNIQUE constraint (uq_users_username)

Also tests fail-closed when a nonunique ix exists without the companion constraint.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa

# Import _validate_legacy_table from the migration file directly.
_MIGRATION_PATH = (
    Path(__file__).parents[2] / "alembic" / "versions" / "20260902_22_core_table_reconciliation.py"
)
_spec = importlib.util.spec_from_file_location("_reconciliation", _MIGRATION_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
_validate_legacy_table = _mod._validate_legacy_table  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers to build mock Inspector
# ---------------------------------------------------------------------------

_USERS_COLUMNS: list[dict[str, Any]] = [
    {
        "name": "id",
        "type": sa.String(36),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "username",
        "type": sa.String(50),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "email",
        "type": sa.String(320),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "password_hash",
        "type": sa.Text(),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "is_admin",
        "type": sa.Integer(),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
]

_API_KEYS_COLUMNS: list[dict[str, Any]] = [
    {
        "name": "id",
        "type": sa.String(36),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "key_hash",
        "type": sa.String(64),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "user_id",
        "type": sa.String(36),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
    {
        "name": "name",
        "type": sa.String(100),
        "nullable": False,
        "default": None,
        "autoincrement": False,
    },
]


def _make_inspector(
    *,
    columns: list[dict[str, Any]],
    indexes: list[dict[str, Any]],
    unique_constraints: list[dict[str, Any]] | None = None,
    foreign_keys: list[dict[str, Any]] | None = None,
    dialect_name: str = "postgresql",
) -> MagicMock:
    inspector = MagicMock()
    inspector.get_columns.return_value = columns
    inspector.get_indexes.return_value = indexes
    inspector.get_pk_constraint.return_value = {"constrained_columns": ["id"]}
    inspector.get_unique_constraints.return_value = unique_constraints or []
    inspector.get_foreign_keys.return_value = foreign_keys or []
    inspector.bind.dialect.name = dialect_name
    return inspector


# ---------------------------------------------------------------------------
# Users table tests
# ---------------------------------------------------------------------------


class TestUsersIndexValidation:
    """Validate ix_users_username acceptance for both forms."""

    def test_canonical_unique_index_accepted(self) -> None:
        """When ix_users_username is reported as unique=True, accept directly."""
        inspector = _make_inspector(
            columns=_USERS_COLUMNS,
            indexes=[{"name": "ix_users_username", "column_names": ["username"], "unique": True}],
        )
        # Should not raise
        _validate_legacy_table(inspector, "users")

    def test_historical_pg_pair_accepted(self) -> None:
        """Nonunique ix + uq_users_username UNIQUE constraint accepted."""
        inspector = _make_inspector(
            columns=_USERS_COLUMNS,
            indexes=[{"name": "ix_users_username", "column_names": ["username"], "unique": False}],
            unique_constraints=[{"name": "uq_users_username", "column_names": ["username"]}],
        )
        _validate_legacy_table(inspector, "users")

    def test_nonunique_without_constraint_rejected(self) -> None:
        """Nonunique ix WITHOUT uq_users_username must fail closed."""
        inspector = _make_inspector(
            columns=_USERS_COLUMNS,
            indexes=[{"name": "ix_users_username", "column_names": ["username"], "unique": False}],
            unique_constraints=[],
        )
        with pytest.raises(RuntimeError, match="index contract mismatch for ix_users_username"):
            _validate_legacy_table(inspector, "users")

    def test_nonunique_with_wrong_constraint_name_rejected(self) -> None:
        """Nonunique ix with differently-named UNIQUE constraint must fail."""
        inspector = _make_inspector(
            columns=_USERS_COLUMNS,
            indexes=[{"name": "ix_users_username", "column_names": ["username"], "unique": False}],
            unique_constraints=[{"name": "wrong_name", "column_names": ["username"]}],
        )
        with pytest.raises(RuntimeError, match="index contract mismatch for ix_users_username"):
            _validate_legacy_table(inspector, "users")

    def test_nonunique_with_wrong_columns_rejected(self) -> None:
        """Nonunique ix with UNIQUE constraint on wrong columns must fail."""
        inspector = _make_inspector(
            columns=_USERS_COLUMNS,
            indexes=[{"name": "ix_users_username", "column_names": ["username"], "unique": False}],
            unique_constraints=[{"name": "uq_users_username", "column_names": ["email"]}],
        )
        with pytest.raises(RuntimeError, match="index contract mismatch for ix_users_username"):
            _validate_legacy_table(inspector, "users")


# ---------------------------------------------------------------------------
# API keys table tests
# ---------------------------------------------------------------------------


class TestApiKeysIndexValidation:
    """Validate ix_api_keys_key_hash and ix_api_keys_user_id."""

    def test_canonical_unique_index_accepted(self) -> None:
        inspector = _make_inspector(
            columns=_API_KEYS_COLUMNS,
            indexes=[
                {"name": "ix_api_keys_key_hash", "column_names": ["key_hash"], "unique": True},
                {"name": "ix_api_keys_user_id", "column_names": ["user_id"], "unique": False},
            ],
        )
        _validate_legacy_table(inspector, "api_keys")

    def test_historical_pg_pair_accepted(self) -> None:
        """Nonunique ix_api_keys_key_hash + uq_api_keys_key_hash accepted."""
        inspector = _make_inspector(
            columns=_API_KEYS_COLUMNS,
            indexes=[
                {"name": "ix_api_keys_key_hash", "column_names": ["key_hash"], "unique": False},
                {"name": "ix_api_keys_user_id", "column_names": ["user_id"], "unique": False},
            ],
            unique_constraints=[{"name": "uq_api_keys_key_hash", "column_names": ["key_hash"]}],
        )
        _validate_legacy_table(inspector, "api_keys")

    def test_nonunique_key_hash_without_constraint_rejected(self) -> None:
        inspector = _make_inspector(
            columns=_API_KEYS_COLUMNS,
            indexes=[
                {"name": "ix_api_keys_key_hash", "column_names": ["key_hash"], "unique": False},
                {"name": "ix_api_keys_user_id", "column_names": ["user_id"], "unique": False},
            ],
            unique_constraints=[],
        )
        with pytest.raises(RuntimeError, match="index contract mismatch for ix_api_keys_key_hash"):
            _validate_legacy_table(inspector, "api_keys")

    def test_missing_index_rejected(self) -> None:
        """Missing ix_api_keys_key_hash entirely must fail."""
        inspector = _make_inspector(
            columns=_API_KEYS_COLUMNS,
            indexes=[
                {"name": "ix_api_keys_user_id", "column_names": ["user_id"], "unique": False},
            ],
        )
        with pytest.raises(RuntimeError, match="index contract mismatch for ix_api_keys_key_hash"):
            _validate_legacy_table(inspector, "api_keys")
