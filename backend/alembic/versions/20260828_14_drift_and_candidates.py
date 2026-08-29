"""Add immutable drift reports and human-approved optimization candidates.

Revision ID: 20260828_14
Revises: 20260828_13
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260828_14"
down_revision: str | None = "20260828_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_revision(label: str, values: list[str]) -> str:
    if not values:
        return f"legacy-{label}-unresolved"
    payload = json.dumps(sorted(set(values)), separators=(",", ":")).encode()
    return f"legacy-{label}-sha256:{hashlib.sha256(payload).hexdigest()}"


def _backfill_cohort_revisions() -> None:
    connection = op.get_bind()
    evaluations = connection.execute(
        sa.text("SELECT id, source_run_ids_json FROM eval_runs")
    ).mappings()
    run_query = sa.text(
        "SELECT run_id, provider, model FROM runs WHERE run_id IN :run_ids"
    ).bindparams(sa.bindparam("run_ids", expanding=True))
    cohort = sa.table(
        "eval_cohort_revisions",
        sa.column("eval_run_id", sa.String),
        sa.column("model_revision", sa.String),
        sa.column("provider_revision", sa.String),
        sa.column("config_revision", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for evaluation in evaluations:
        raw_ids = evaluation["source_run_ids_json"]
        run_ids = json.loads(raw_ids) if isinstance(raw_ids, str) else list(raw_ids or [])
        rows = (
            connection.execute(run_query, {"run_ids": run_ids}).mappings().all() if run_ids else []
        )
        connection.execute(
            cohort.insert().values(
                eval_run_id=evaluation["id"],
                model_revision=_legacy_revision("model", [str(row["model"]) for row in rows]),
                provider_revision=_legacy_revision(
                    "provider", [str(row["provider"]) for row in rows]
                ),
                config_revision="legacy-config-pre-s8.8",
                created_at=sa.func.current_timestamp(),
            )
        )


def _create_immutability_guards() -> None:
    dialect = op.get_bind().dialect.name
    immutable_tables = (
        "eval_cohort_revisions",
        "eval_drift_reports",
        "optimization_candidate_events",
    )
    if dialect == "sqlite":
        for table in immutable_tables:
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER trg_{table}_{operation.lower()} "
                    f"BEFORE {operation} ON {table} BEGIN "
                    "SELECT RAISE(ABORT, 'immutable record'); END"
                )
        op.execute(
            "CREATE TRIGGER trg_optimization_candidates_delete "
            "BEFORE DELETE ON optimization_candidates BEGIN "
            "SELECT RAISE(ABORT, 'immutable candidate'); END"
        )
        immutable = (
            "NEW.id IS NOT OLD.id OR NEW.owner_id IS NOT OLD.owner_id OR "
            "NEW.project_id IS NOT OLD.project_id OR "
            "NEW.candidate_type IS NOT OLD.candidate_type OR "
            "NEW.change_summary IS NOT OLD.change_summary OR "
            "NEW.proposal_metadata_json IS NOT OLD.proposal_metadata_json OR "
            "NEW.rollback_plan IS NOT OLD.rollback_plan OR "
            "NEW.target_revision IS NOT OLD.target_revision OR "
            "NEW.baseline_eval_id IS NOT OLD.baseline_eval_id OR "
            "NEW.candidate_eval_id IS NOT OLD.candidate_eval_id OR "
            "NEW.drift_report_id IS NOT OLD.drift_report_id OR "
            "NEW.created_at IS NOT OLD.created_at"
        )
        op.execute(
            "CREATE TRIGGER trg_optimization_candidates_immutable_fields "
            f"BEFORE UPDATE ON optimization_candidates WHEN {immutable} BEGIN "
            "SELECT RAISE(ABORT, 'immutable candidate evidence'); END"
        )
        transitions = (
            "NEW.version != OLD.version + 1 OR NOT ("
            "(OLD.state = 'proposed' AND NEW.state = 'approved' AND "
            "OLD.approval_id IS NULL AND NEW.approval_id IS NOT NULL) OR "
            "(OLD.state = 'proposed' AND NEW.state = 'rejected' AND "
            "NEW.approval_id IS OLD.approval_id) OR "
            "(OLD.state = 'approved' AND NEW.state IN ('promoted','rejected') AND "
            "NEW.approval_id IS OLD.approval_id) OR "
            "(OLD.state = 'promoted' AND NEW.state = 'rolled_back' AND "
            "NEW.approval_id IS OLD.approval_id))"
        )
        op.execute(
            "CREATE TRIGGER trg_optimization_candidates_transition "
            f"BEFORE UPDATE ON optimization_candidates WHEN {transitions} BEGIN "
            "SELECT RAISE(ABORT, 'invalid candidate transition'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION archon_s8_8_reject_immutable() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable record'; END $$"
        )
        for table in immutable_tables:
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION archon_s8_8_reject_immutable()"
            )
        op.execute(
            "CREATE FUNCTION archon_s8_8_candidate_guard() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'immutable candidate'; END IF; IF "
            "NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_id IS DISTINCT FROM OLD.owner_id OR "
            "NEW.project_id IS DISTINCT FROM OLD.project_id OR "
            "NEW.candidate_type IS DISTINCT FROM OLD.candidate_type OR "
            "NEW.change_summary IS DISTINCT FROM OLD.change_summary OR "
            "NEW.proposal_metadata_json IS DISTINCT FROM OLD.proposal_metadata_json OR "
            "NEW.rollback_plan IS DISTINCT FROM OLD.rollback_plan OR "
            "NEW.target_revision IS DISTINCT FROM OLD.target_revision OR "
            "NEW.baseline_eval_id IS DISTINCT FROM OLD.baseline_eval_id OR "
            "NEW.candidate_eval_id IS DISTINCT FROM OLD.candidate_eval_id OR "
            "NEW.drift_report_id IS DISTINCT FROM OLD.drift_report_id OR "
            "NEW.created_at IS DISTINCT FROM OLD.created_at THEN "
            "RAISE EXCEPTION 'immutable candidate evidence'; END IF; "
            "IF NEW.version != OLD.version + 1 OR NOT ("
            "(OLD.state = 'proposed' AND NEW.state = 'approved' AND "
            "OLD.approval_id IS NULL AND NEW.approval_id IS NOT NULL) OR "
            "(OLD.state = 'proposed' AND NEW.state = 'rejected' AND "
            "NEW.approval_id IS NOT DISTINCT FROM OLD.approval_id) OR "
            "(OLD.state = 'approved' AND NEW.state IN ('promoted','rejected') AND "
            "NEW.approval_id IS NOT DISTINCT FROM OLD.approval_id) OR "
            "(OLD.state = 'promoted' AND NEW.state = 'rolled_back' AND "
            "NEW.approval_id IS NOT DISTINCT FROM OLD.approval_id)) THEN "
            "RAISE EXCEPTION 'invalid candidate transition'; END IF; "
            "RETURN NEW; END $$"
        )
        op.execute(
            "CREATE TRIGGER trg_optimization_candidates_guard BEFORE UPDATE OR DELETE "
            "ON optimization_candidates FOR EACH ROW "
            "EXECUTE FUNCTION archon_s8_8_candidate_guard()"
        )


def _drop_immutability_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            *(
                f"trg_{table}_{operation}"
                for table in (
                    "eval_cohort_revisions",
                    "eval_drift_reports",
                    "optimization_candidate_events",
                )
                for operation in ("update", "delete")
            ),
            "trg_optimization_candidates_delete",
            "trg_optimization_candidates_immutable_fields",
            "trg_optimization_candidates_transition",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_optimization_candidates_guard ON optimization_candidates"
        )
        for table in (
            "eval_cohort_revisions",
            "eval_drift_reports",
            "optimization_candidate_events",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
        op.execute("DROP FUNCTION IF EXISTS archon_s8_8_candidate_guard()")
        op.execute("DROP FUNCTION IF EXISTS archon_s8_8_reject_immutable()")


def upgrade() -> None:
    op.create_index(
        "uq_eval_runs_scope", "eval_runs", ["id", "owner_id", "project_id"], unique=True
    )
    op.create_table(
        "eval_cohort_revisions",
        sa.Column(
            "eval_run_id",
            sa.String(36),
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("model_revision", sa.String(255), nullable=False),
        sa.Column("provider_revision", sa.String(255), nullable=False),
        sa.Column("config_revision", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _backfill_cohort_revisions()
    op.create_table(
        "eval_drift_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("baseline_eval_id", sa.String(36), nullable=False),
        sa.Column("candidate_eval_id", sa.String(36), nullable=False),
        sa.Column("baseline_identity_json", sa.JSON(), nullable=False),
        sa.Column("candidate_identity_json", sa.JSON(), nullable=False),
        sa.Column("baseline_summary_json", sa.JSON(), nullable=False),
        sa.Column("candidate_summary_json", sa.JSON(), nullable=False),
        sa.Column("deltas_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "owner_id", "project_id", name="uq_drift_scope"),
        sa.ForeignKeyConstraint(
            ["baseline_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_drift_baseline_scope",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_drift_candidate_scope",
        ),
        sa.CheckConstraint("minimum_sample_size BETWEEN 2 AND 10000", name="ck_drift_min_sample"),
        sa.CheckConstraint(
            "baseline_eval_id <> candidate_eval_id", name="ck_drift_distinct_evaluations"
        ),
        sa.UniqueConstraint(
            "owner_id",
            "project_id",
            "baseline_eval_id",
            "candidate_eval_id",
            "minimum_sample_size",
            name="uq_drift_comparison",
        ),
    )
    op.create_index(
        "ix_drift_owner_project_created",
        "eval_drift_reports",
        ["owner_id", "project_id", "created_at"],
    )
    op.create_table(
        "optimization_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("candidate_type", sa.String(20), nullable=False),
        sa.Column("change_summary", sa.String(1000), nullable=False),
        sa.Column("proposal_metadata_json", sa.JSON(), nullable=False),
        sa.Column("rollback_plan", sa.String(2000), nullable=False),
        sa.Column("target_revision", sa.String(255), nullable=False),
        sa.Column("baseline_eval_id", sa.String(36), nullable=False),
        sa.Column("candidate_eval_id", sa.String(36), nullable=False),
        sa.Column("drift_report_id", sa.String(36), nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "approval_id", sa.String(36), sa.ForeignKey("approval_requests.id"), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("id", "owner_id", "project_id", name="uq_candidate_scope"),
        sa.ForeignKeyConstraint(
            ["baseline_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_candidate_baseline_scope",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_candidate_evidence_scope",
        ),
        sa.ForeignKeyConstraint(
            ["drift_report_id", "owner_id", "project_id"],
            [
                "eval_drift_reports.id",
                "eval_drift_reports.owner_id",
                "eval_drift_reports.project_id",
            ],
            name="fk_candidate_drift_scope",
        ),
        sa.CheckConstraint(
            "candidate_type IN ('prompt','policy','retrieval','config')", name="ck_candidate_type"
        ),
        sa.CheckConstraint(
            "state IN ('proposed','approved','rejected','promoted','rolled_back')",
            name="ck_candidate_state",
        ),
        sa.CheckConstraint("version >= 1", name="ck_candidate_version"),
        sa.CheckConstraint(
            "baseline_eval_id <> candidate_eval_id", name="ck_candidate_distinct_evaluations"
        ),
        sa.UniqueConstraint("approval_id", name="uq_candidate_approval_single_use"),
    )
    op.create_index(
        "ix_candidates_owner_project_created",
        "optimization_candidates",
        ["owner_id", "project_id", "created_at"],
    )
    op.create_table(
        "optimization_candidate_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("from_state", sa.String(20), nullable=True),
        sa.Column("to_state", sa.String(20), nullable=False),
        sa.Column("candidate_version", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(36), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id", "owner_id", "project_id"],
            [
                "optimization_candidates.id",
                "optimization_candidates.owner_id",
                "optimization_candidates.project_id",
            ],
            name="fk_candidate_event_scope",
        ),
        sa.CheckConstraint(
            "event_type IN ('proposed','approved','rejected','promoted','rolled_back')",
            name="ck_candidate_event_type",
        ),
        sa.UniqueConstraint("candidate_id", "candidate_version", name="uq_candidate_event_version"),
    )
    _create_immutability_guards()


def downgrade() -> None:
    _drop_immutability_guards()
    op.drop_table("optimization_candidate_events")
    op.drop_table("optimization_candidates")
    op.drop_table("eval_drift_reports")
    op.drop_table("eval_cohort_revisions")
    op.drop_index("uq_eval_runs_scope", table_name="eval_runs")
