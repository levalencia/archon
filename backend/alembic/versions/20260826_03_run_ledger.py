"""Create the durable owner-scoped append-only run ledger.

Revision ID: 20260826_03
Revises: 20260826_02
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "20260826_03"
down_revision: str | None = "20260826_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_runs() -> None:
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("parent_run_id", sa.String(length=36), nullable=True),
        sa.Column("fork_source_sequence", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(length=100), nullable=True),
        sa.Column("answer_summary", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("iterations", sa.Integer(), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint("next_sequence >= 1", name="ck_runs_next_sequence"),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled')", name="ck_runs_status"
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_runs_owner_started", "runs", ["user_id", "started_at"])
    op.create_index(
        "ix_runs_owner_project_started", "runs", ["user_id", "project_id", "started_at"]
    )
    op.create_index("ix_runs_conversation", "runs", ["conversation_id"])


def _create_events() -> None:
    op.create_table(
        "runtime_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_runtime_events_run_sequence"),
    )
    op.create_index("ix_runtime_events_owner_run", "runtime_events", ["user_id", "run_id"])
    op.create_index("ix_runtime_events_conversation_id", "runtime_events", ["conversation_id"])
    op.create_index("ix_runtime_events_correlation_id", "runtime_events", ["correlation_id"])


def upgrade() -> None:
    connection = op.get_bind()
    had_events = "runtime_events" in sa.inspect(connection).get_table_names()
    if had_events:
        op.rename_table("runtime_events", "runtime_events_legacy")
        for index in sa.inspect(connection).get_indexes("runtime_events_legacy"):
            if index["name"]:
                op.drop_index(index["name"], table_name="runtime_events_legacy")
    _create_runs()
    _create_events()
    if not had_events:
        return

    legacy = sa.table(
        "runtime_events_legacy",
        sa.column("id"),
        sa.column("run_id"),
        sa.column("conversation_id"),
        sa.column("correlation_id"),
        sa.column("kind"),
        sa.column("iteration"),
        sa.column("data"),
        sa.column("created_at"),
    )
    rows = connection.execute(sa.select(legacy).order_by(legacy.c.run_id, legacy.c.id)).mappings()
    grouped: dict[str, list[sa.RowMapping]] = defaultdict(list)
    for row in rows:
        grouped[str(row["run_id"])].append(row)
    now = datetime.now(tz=UTC)
    runs_table = sa.table(
        "runs",
        *[
            sa.column(name)
            for name in (
                "run_id",
                "user_id",
                "project_id",
                "conversation_id",
                "correlation_id",
                "provider",
                "model",
                "schema_version",
                "status",
                "started_at",
                "completed_at",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "iterations",
                "next_sequence",
            )
        ],
    )
    events_table = sa.table(
        "runtime_events",
        *[
            sa.column(name)
            for name in (
                "run_id",
                "user_id",
                "project_id",
                "conversation_id",
                "correlation_id",
                "sequence",
                "event_at",
                "kind",
                "schema_version",
                "iteration",
                "payload",
            )
        ],
    )
    for run_id, event_rows in grouped.items():
        first = event_rows[0]
        started = first["created_at"] or now
        connection.execute(
            runs_table.insert().values(
                run_id=run_id,
                user_id="legacy",
                project_id="default",
                conversation_id=first["conversation_id"],
                correlation_id=first["correlation_id"],
                provider="unknown",
                model="unknown",
                schema_version=1,
                status="completed",
                started_at=started,
                completed_at=event_rows[-1]["created_at"] or started,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                iterations=max(int(item["iteration"]) for item in event_rows),
                next_sequence=len(event_rows) + 1,
            )
        )
        for sequence, item in enumerate(event_rows, 1):
            allowed = {
                "run_started": {"safe"},
                "model_response": {"provider_stop_reason"},
                "tool_call_requested": {"id", "name", "arguments_hash"},
                "tool_call_completed": {
                    "id",
                    "name",
                    "arguments_hash",
                    "output_hash",
                    "output_size",
                    "status",
                },
                "run_stopped": {"reason", "error"},
            }.get(str(item["kind"]), set())
            try:
                decoded = json.loads(item["data"] or "{}")
            except (TypeError, json.JSONDecodeError):
                decoded = {}
            payload = (
                {key: decoded[key] for key in allowed if key in decoded}
                if isinstance(decoded, dict)
                else {}
            )
            if "error" in payload:
                payload["error"] = bool(payload["error"])
            connection.execute(
                events_table.insert().values(
                    run_id=run_id,
                    user_id="legacy",
                    project_id="default",
                    conversation_id=item["conversation_id"],
                    correlation_id=item["correlation_id"],
                    sequence=sequence,
                    event_at=item["created_at"] or started,
                    kind=item["kind"],
                    schema_version=1,
                    iteration=item["iteration"],
                    payload=json.dumps(payload),
                )
            )
    op.drop_table("runtime_events_legacy")


def downgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "runtime_events_legacy",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO runtime_events_legacy "
            "(run_id, conversation_id, correlation_id, kind, iteration, data, created_at) "
            "SELECT run_id, conversation_id, correlation_id, kind, iteration, payload, event_at "
            "FROM runtime_events ORDER BY run_id, sequence"
        )
    )
    op.drop_table("runtime_events")
    op.drop_table("runs")
    op.rename_table("runtime_events_legacy", "runtime_events")
    op.create_index("ix_runtime_events_run_id", "runtime_events", ["run_id"])
    op.create_index("ix_runtime_events_conversation_id", "runtime_events", ["conversation_id"])
    op.create_index("ix_runtime_events_correlation_id", "runtime_events", ["correlation_id"])
