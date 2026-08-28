"""PostgreSQL-backed conversation and message store.

Replaces InMemoryStore for production. Uses SQLAlchemy async with
asyncpg driver. Falls back to aiosqlite for testing.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import structlog
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = structlog.get_logger()


class Base(DeclarativeBase):
    pass


class DelegationNonceRow(Base):
    """One-time receipt for an authenticated delegation envelope."""

    __tablename__ = "delegation_nonce_receipts"
    __table_args__ = (
        CheckConstraint("key_version BETWEEN 1 AND 255", name="ck_delegation_key_version"),
        Index("ix_delegation_receipts_issued_at", "issued_at"),
    )
    nonce = Column(String(255), primary_key=True)
    key_version = Column(Integer, nullable=False)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    parent_run_id = Column(String(255), nullable=False)
    child_run_id = Column(String(255), nullable=False)
    signature_hash = Column(String(64), nullable=False)
    issued_at = Column(BigInteger, nullable=False)
    received_at = Column(BigInteger, nullable=False)


class BackgroundJobRow(Base):
    """Restart-safe, owner/project-scoped allowlisted work item."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','dead_letter','cancelled')",
            name="ck_background_jobs_status",
        ),
        CheckConstraint("kind IN ('echo','run_export')", name="ck_background_jobs_kind"),
        CheckConstraint(
            "attempts >= 0 AND max_attempts BETWEEN 1 AND 10 AND attempts <= max_attempts",
            name="ck_background_jobs_attempts",
        ),
        CheckConstraint("lease_generation >= 0", name="ck_background_jobs_lease_generation"),
        CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status != 'running' AND worker_id IS NULL AND lease_expires_at IS NULL)",
            name="ck_background_jobs_lease_state",
        ),
        CheckConstraint(
            "(status IN ('succeeded','failed','dead_letter','cancelled') "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('pending','running') AND completed_at IS NULL)",
            name="ck_background_jobs_completion_state",
        ),
        UniqueConstraint("owner_id", "project_id", "idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_jobs_owner_project", "owner_id", "project_id", "created_at"),
    )
    job_id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    kind = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    lease_generation = Column(Integer, nullable=False, default=0)
    idempotency_key = Column(String(255), nullable=True)
    worker_id = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    result_json = Column(Text, nullable=True)
    error_code = Column(String(64), nullable=True)


class ConversationRow(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True)
    title = Column(String(200), nullable=False, default="New Conversation")
    user_id = Column(String(36), nullable=False, default="default")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(tz=UTC),
        onupdate=lambda: datetime.now(tz=UTC),
    )
    is_active = Column(Integer, default=1)


class MessageRow(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))


class AuditRow(Base):
    __tablename__ = "audit_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(String(30), nullable=False)
    agent_id = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    resource = Column(String(500), nullable=False)
    parameters = Column(Text, nullable=True)
    result = Column(String(50), default="success")
    security_level = Column(String(20), default="info")
    correlation_id = Column(String(36), nullable=True, index=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id = Column(String(36), primary_key=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    message_id = Column(String(36), nullable=True)
    title = Column(String(200), nullable=False)
    artifact_type = Column(String(20), nullable=False)
    language = Column(String(20), nullable=True)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(tz=UTC))


class UserRow(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(320), nullable=False, default="")
    password_hash = Column(Text, nullable=False)
    is_admin = Column(Integer, nullable=False, default=0)


class DocumentRow(Base):
    """Durable owner/project-scoped metadata for a redacted document."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_project_created", "owner_id", "project_id", "created_at"),
        CheckConstraint("status IN ('processing','ready','failed')", name="ck_documents_status"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    title = Column(String(500), nullable=False)
    source = Column(String(1000), nullable=False, default="")
    content_hash = Column(String(64), nullable=False)
    characters = Column(Integer, nullable=False)
    chunks = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="processing")
    embedding_provider = Column(String(100), nullable=False)
    embedding_model = Column(String(255), nullable=False)
    embedding_dimensions = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class VectorChunkRow(Base):
    """Redacted chunk and JSON embedding; this is not a pgvector column."""

    __tablename__ = "vector_chunks"
    __table_args__ = (
        Index("ix_vector_chunks_scope_document", "owner_id", "project_id", "document_id"),
        UniqueConstraint("document_id", "chunk_index", name="uq_vector_chunk_index"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    embedding_json = Column(Text, nullable=False)


class ApiKeyRow(Base):
    __tablename__ = "api_keys"
    id = Column(String(36), primary_key=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(String(36), nullable=False, index=True)
    name = Column(String(100), nullable=False)


class RuntimeEventRow(Base):
    __tablename__ = "runtime_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_runtime_events_run_sequence"),
        Index("ix_runtime_events_owner_run", "user_id", "run_id"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    conversation_id = Column(String(255), nullable=False, index=True)
    correlation_id = Column(String(100), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False)
    kind = Column(String(40), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1)
    iteration = Column(Integer, nullable=False)
    payload = Column(Text, nullable=False, default="{}")


class RunRow(Base):
    """Durable owner-scoped runtime invocation and atomic event sequence allocator."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled')", name="ck_runs_status"
        ),
        CheckConstraint("next_sequence >= 1", name="ck_runs_next_sequence"),
        CheckConstraint(
            "budget_limit_nusd >= 0 AND budget_spent_nusd >= 0 AND budget_reserved_nusd >= 0",
            name="ck_runs_budget_amounts_nonnegative",
        ),
        CheckConstraint(
            "budget_spent_nusd + budget_reserved_nusd <= budget_limit_nusd",
            name="ck_runs_budget_within_limit",
        ),
        Index("ix_runs_owner_started", "user_id", "started_at"),
        Index("ix_runs_owner_project_started", "user_id", "project_id", "started_at"),
        Index("ix_runs_conversation", "conversation_id"),
    )

    run_id = Column(String(36), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False, default="default")
    conversation_id = Column(String(255), nullable=False)
    correlation_id = Column(String(100), nullable=False)
    parent_run_id = Column(
        String(36), ForeignKey("runs.run_id", ondelete="RESTRICT"), nullable=True
    )
    fork_source_sequence = Column(Integer, nullable=True)
    provider = Column(String(100), nullable=False, default="unknown")
    model = Column(String(255), nullable=False, default="unknown")
    schema_version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    stop_reason = Column(String(100), nullable=True)
    answer_summary = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    iterations = Column(Integer, nullable=False, default=0)
    next_sequence = Column(Integer, nullable=False, default=1)
    budget_limit_nusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    budget_spent_nusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    budget_reserved_nusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    budget_opened_at = Column(DateTime(timezone=True), nullable=True)


class ContextSnapshotRow(Base):
    """Redacted effective-context lineage; never stores prompt or source content."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="ck_context_snapshots_schema_version"),
        CheckConstraint("estimated_tokens >= 0", name="ck_context_snapshots_tokens_nonnegative"),
        UniqueConstraint("run_id", name="uq_context_snapshots_run"),
        Index("ix_context_snapshots_owner_run", "owner_id", "run_id"),
        Index(
            "ix_context_snapshots_owner_project_created",
            "owner_id",
            "project_id",
            "created_at",
        ),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_message_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summarized_message_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    memory_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    skill_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    input_asset_fingerprints_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    summary_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    truncation_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunExportRow(Base):
    """Immutable, disclosure-scanned run evidence bundle."""

    __tablename__ = "run_exports"
    __table_args__ = (
        CheckConstraint("schema_version = 1", name="ck_run_exports_schema_version"),
        UniqueConstraint("export_id", "owner_id", name="uq_run_exports_export_owner"),
        UniqueConstraint("owner_id", "run_id", "content_checksum", name="uq_run_exports_content"),
        Index("ix_run_exports_owner_run", "owner_id", "run_id", "created_at"),
    )
    export_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_json: Mapped[str] = mapped_column(Text, nullable=False)
    content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunShareGrantRow(Base):
    """Purpose-bound read grant; only the token digest is durable."""

    __tablename__ = "run_share_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["export_id", "owner_id"],
            ["run_exports.export_id", "run_exports.owner_id"],
            ondelete="CASCADE",
            name="fk_share_export_owner",
        ),
        CheckConstraint(
            "purpose IN ('audit','incident_review','evaluation','support')",
            name="ck_share_purpose",
        ),
        CheckConstraint("expires_at > created_at", name="ck_share_expiry_after_create"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_share_revoked_after_create"
        ),
        Index("ix_share_grants_owner_export", "owner_id", "export_id", "created_at"),
        Index("ix_share_grants_token_hash", "token_hash", unique=True),
    )
    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    export_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(120), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EffectRow(Base):
    """Durable effect tombstone containing hashes and lifecycle metadata only."""

    __tablename__ = "effects"
    __table_args__ = (
        CheckConstraint(
            "state IN ('reserved','committed','failed','indeterminate')",
            name="ck_effects_state",
        ),
        CheckConstraint("identity_version >= 0", name="ck_effects_identity_version_nonnegative"),
        CheckConstraint(
            "output_size IS NULL OR output_size >= 0", name="ck_effects_output_size_nonnegative"
        ),
        Index("ix_effects_owner_project_state", "owner_id", "project_id", "state"),
        Index("ix_effects_owner_run", "owner_id", "run_id"),
        Index("ix_effects_run_state", "run_id", "state"),
    )

    effect_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    identity_version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectBudgetRow(Base):
    """Integer nano-US-dollar budget counters for an owner/project scope."""

    __tablename__ = "project_budgets"
    __table_args__ = (
        CheckConstraint(
            "limit_nusd >= 0 AND spent_nusd >= 0 AND reserved_nusd >= 0",
            name="ck_project_budgets_amounts_nonnegative",
        ),
        CheckConstraint(
            "spent_nusd + reserved_nusd <= limit_nusd",
            name="ck_project_budgets_within_limit",
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    limit_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    spent_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ModelChargeRow(Base):
    """Safe monetary reservation and reconciliation metadata for one model dispatch."""

    __tablename__ = "model_charges"
    __table_args__ = (
        CheckConstraint(
            "state IN ('reserved','dispatched','reconciled','released','indeterminate')",
            name="ck_model_charges_state",
        ),
        CheckConstraint("ordinal >= 0", name="ck_model_charges_ordinal_nonnegative"),
        CheckConstraint("reserved_nusd >= 0", name="ck_model_charges_reserved_nonnegative"),
        CheckConstraint(
            "actual_nusd IS NULL OR actual_nusd >= 0",
            name="ck_model_charges_actual_nonnegative",
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0) AND "
            "(cache_read_tokens IS NULL OR cache_read_tokens >= 0) AND "
            "(cache_write_tokens IS NULL OR cache_write_tokens >= 0)",
            name="ck_model_charges_tokens_nonnegative",
        ),
        UniqueConstraint("run_id", "ordinal", name="uq_model_charges_run_ordinal"),
        Index("ix_model_charges_owner_project_state", "owner_id", "project_id", "state"),
        Index("ix_model_charges_run_state", "run_id", "state"),
    )

    charge_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    reserved_nusd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_nusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRunRow(Base):
    """Owner-scoped metadata and safe aggregate metrics for an evaluation."""

    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_eval_runs_status"),
        CheckConstraint("threshold >= 0 AND threshold <= 1", name="ck_eval_runs_threshold"),
        CheckConstraint("passed IS NULL OR passed IN (0,1)", name="ck_eval_runs_passed"),
        UniqueConstraint("id", "owner_id", "project_id", name="uq_eval_runs_scope"),
        Index("ix_eval_runs_owner_project_created", "owner_id", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    dataset_id = Column(String(255), nullable=False)
    dataset_version = Column(String(100), nullable=False)
    dataset_hash = Column(String(64), nullable=False)
    source_run_ids_json = Column(JSON, nullable=False)
    threshold = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)
    passed = Column(Integer, nullable=True)
    aggregate_metrics_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class EvalCohortRevisionRow(Base):
    """Immutable runtime revision identity for an evaluation cohort."""

    __tablename__ = "eval_cohort_revisions"
    eval_run_id = Column(
        String(36), ForeignKey("eval_runs.id", ondelete="CASCADE"), primary_key=True
    )
    model_revision = Column(String(255), nullable=False)
    provider_revision = Column(String(255), nullable=False)
    config_revision = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class EvalCaseResultRow(Base):
    """Privacy-safe result for one case; answers and event payloads are never stored."""

    __tablename__ = "eval_case_results"
    __table_args__ = (
        CheckConstraint("passed IN (0,1)", name="ck_eval_case_results_passed"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_eval_case_results_score"),
        UniqueConstraint("eval_run_id", "case_key", name="uq_eval_case_results_run_case"),
        Index("ix_eval_case_results_eval_run", "eval_run_id"),
    )

    id = Column(String(36), primary_key=True)
    eval_run_id = Column(String(36), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False)
    source_run_id = Column(String(36), nullable=False)
    case_key = Column(String(255), nullable=False)
    passed = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    metrics_json = Column(JSON, nullable=False)
    checks_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class EvalDriftReportRow(Base):
    """Immutable metadata-only comparison of two evaluation cohorts."""

    __tablename__ = "eval_drift_reports"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "project_id", name="uq_drift_scope"),
        ForeignKeyConstraint(
            ["baseline_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_drift_baseline_scope",
        ),
        ForeignKeyConstraint(
            ["candidate_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_drift_candidate_scope",
        ),
        CheckConstraint("minimum_sample_size BETWEEN 2 AND 10000", name="ck_drift_min_sample"),
        CheckConstraint(
            "baseline_eval_id <> candidate_eval_id", name="ck_drift_distinct_evaluations"
        ),
        UniqueConstraint(
            "owner_id",
            "project_id",
            "baseline_eval_id",
            "candidate_eval_id",
            "minimum_sample_size",
            name="uq_drift_comparison",
        ),
        Index("ix_drift_owner_project_created", "owner_id", "project_id", "created_at"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    baseline_eval_id = Column(String(36), nullable=False)
    candidate_eval_id = Column(String(36), nullable=False)
    baseline_identity_json = Column(JSON, nullable=False)
    candidate_identity_json = Column(JSON, nullable=False)
    baseline_summary_json = Column(JSON, nullable=False)
    candidate_summary_json = Column(JSON, nullable=False)
    deltas_json = Column(JSON, nullable=False)
    warnings_json = Column(JSON, nullable=False)
    minimum_sample_size = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class OptimizationCandidateRow(Base):
    """Bounded recommendation only; promotion records but never applies a revision."""

    __tablename__ = "optimization_candidates"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", "project_id", name="uq_candidate_scope"),
        ForeignKeyConstraint(
            ["baseline_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_candidate_baseline_scope",
        ),
        ForeignKeyConstraint(
            ["candidate_eval_id", "owner_id", "project_id"],
            ["eval_runs.id", "eval_runs.owner_id", "eval_runs.project_id"],
            name="fk_candidate_evidence_scope",
        ),
        ForeignKeyConstraint(
            ["drift_report_id", "owner_id", "project_id"],
            [
                "eval_drift_reports.id",
                "eval_drift_reports.owner_id",
                "eval_drift_reports.project_id",
            ],
            name="fk_candidate_drift_scope",
        ),
        CheckConstraint(
            "candidate_type IN ('prompt','policy','retrieval','config')", name="ck_candidate_type"
        ),
        CheckConstraint(
            "state IN ('proposed','approved','rejected','promoted','rolled_back')",
            name="ck_candidate_state",
        ),
        CheckConstraint("version >= 1", name="ck_candidate_version"),
        CheckConstraint(
            "baseline_eval_id <> candidate_eval_id", name="ck_candidate_distinct_evaluations"
        ),
        UniqueConstraint("approval_id", name="uq_candidate_approval_single_use"),
        Index("ix_candidates_owner_project_created", "owner_id", "project_id", "created_at"),
    )
    id = Column(String(36), primary_key=True)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    candidate_type = Column(String(20), nullable=False)
    change_summary = Column(String(1000), nullable=False)
    proposal_metadata_json = Column(JSON, nullable=False)
    rollback_plan = Column(String(2000), nullable=False)
    target_revision = Column(String(255), nullable=False)
    baseline_eval_id = Column(String(36), nullable=False)
    candidate_eval_id = Column(String(36), nullable=False)
    drift_report_id = Column(String(36), nullable=True)
    state = Column(String(20), nullable=False)
    version = Column(Integer, nullable=False)
    approval_id = Column(String(36), ForeignKey("approval_requests.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)


class OptimizationCandidateEventRow(Base):
    """Append-only candidate transition audit record."""

    __tablename__ = "optimization_candidate_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["candidate_id", "owner_id", "project_id"],
            [
                "optimization_candidates.id",
                "optimization_candidates.owner_id",
                "optimization_candidates.project_id",
            ],
            name="fk_candidate_event_scope",
        ),
        CheckConstraint(
            "event_type IN ('proposed','approved','rejected','promoted','rolled_back')",
            name="ck_candidate_event_type",
        ),
        UniqueConstraint("candidate_id", "candidate_version", name="uq_candidate_event_version"),
    )
    id = Column(String(36), primary_key=True)
    candidate_id = Column(String(36), nullable=False)
    owner_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    event_type = Column(String(20), nullable=False)
    from_state = Column(String(20), nullable=True)
    to_state = Column(String(20), nullable=False)
    candidate_version = Column(Integer, nullable=False)
    approval_id = Column(String(36), nullable=True)
    reason_code = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class RunCheckpointRow(Base):
    """Privacy-safe immutable checkpoint used to create a conversation fork."""

    __tablename__ = "run_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_run_id", "source_sequence", name="uq_checkpoint_source"
        ),
        Index("ix_checkpoints_owner_project", "user_id", "project_id"),
    )
    checkpoint_id = Column(String(36), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    source_run_id = Column(
        String(36), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    source_sequence = Column(Integer, nullable=False)
    conversation_snapshot = Column(Text, nullable=False)
    policy_profile = Column(String(100), nullable=False, default="default")
    selected_memory_ids = Column(Text, nullable=False, default="[]")
    workspace_restoration = Column(String(20), nullable=False, default="none")
    created_at = Column(DateTime(timezone=True), nullable=False)


class ForkDraftRow(Base):
    """Durable ancestry from a checkpoint to its target conversation."""

    __tablename__ = "fork_drafts"
    __table_args__ = (Index("ix_fork_drafts_owner_target", "user_id", "target_conversation_id"),)
    id = Column(String(36), primary_key=True)
    checkpoint_id = Column(
        String(36), ForeignKey("run_checkpoints.checkpoint_id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    source_run_id = Column(String(36), nullable=False)
    source_sequence = Column(Integer, nullable=False)
    target_conversation_id = Column(String(36), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ApprovalRequestRow(Base):
    """Durable exact-binding approval state; raw tool arguments are never persisted."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','denied','expired','cancelled')",
            name="ck_approval_requests_status",
        ),
        UniqueConstraint(
            "user_id", "run_id", "tool_call_id", name="uq_approval_requests_owner_run_call"
        ),
        Index("ix_approval_requests_owner", "user_id"),
        Index("ix_approval_requests_status", "status"),
        Index("ix_approval_requests_run", "run_id"),
        Index("ix_approval_requests_call", "tool_call_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_call_id: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_classes: Mapped[str] = mapped_column(Text, nullable=False)
    matched_rule_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryScopeRow(Base):
    """Transactionally serialized character accounting for one owner/project scope."""

    __tablename__ = "memory_scopes"
    __table_args__ = (
        CheckConstraint("chars_used >= 0", name="ck_memory_scopes_chars_nonnegative"),
        CheckConstraint("version >= 0", name="ck_memory_scopes_version_nonnegative"),
    )

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    chars_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MemoryKeyStateRow(Base):
    """Global active encryption generation; never stores key material."""

    __tablename__ = "memory_key_state"
    __table_args__ = (
        CheckConstraint("active_version BETWEEN 1 AND 255", name="ck_memory_key_state_active"),
        CheckConstraint("generation >= 1", name="ck_memory_key_state_generation"),
    )

    singleton_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    active_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryFactRow(Base):
    """Encrypted memory fact; content and provenance exist only inside ciphertext."""

    __tablename__ = "memory_facts"
    __table_args__ = (
        CheckConstraint("key_version BETWEEN 1 AND 255", name="ck_memory_facts_key_version"),
        Index("ix_memory_facts_owner_project", "user_id", "project_id"),
        Index("ix_memory_facts_owner", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MCPServerRow(Base):
    """Safe durable MCP configuration (deployment profiles hold process details)."""

    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("owner_id", "project_id", "name", name="uq_mcp_server_scope_name"),
        Index("ix_mcp_servers_scope", "owner_id", "project_id"),
        CheckConstraint("transport = 'stdio'", name="ck_mcp_servers_transport"),
        CheckConstraint(
            "health IN ('unknown','healthy','error','disabled')", name="ck_mcp_servers_health"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transport: Mapped[str] = mapped_column(String(16), nullable=False, default="stdio")
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    health: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MCPToolRow(Base):
    """Bounded discovered metadata. Invocation arguments and results never live here."""

    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("server_id", "name", name="uq_mcp_tool_server_name"),
        Index("ix_mcp_tools_server", "server_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    server_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(String(10_000), nullable=True)
    input_schema_json: Mapped[str] = mapped_column(Text, nullable=False)
    read_only: Mapped[bool] = mapped_column(nullable=False)
    destructive: Mapped[bool] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)


def ensure_private_sqlite_file(database_url: str) -> None:
    """Restrict an on-disk SQLite database to its owner, where applicable."""
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or not url.database or url.database == ":memory:":
        return
    if os.path.exists(url.database):
        os.chmod(url.database, 0o600)


class DatabaseStore:
    """PostgreSQL-backed store for conversations, messages, audit, artifacts.

    Usage:
        store = DatabaseStore("postgresql+asyncpg://user:pass@localhost/archon")
        await store.initialize()
        await store.store("conv-1", {"role": "user", "content": "hello"})
    """

    def __init__(self, database_url: str) -> None:
        connect_args = {}
        if "sqlite" in database_url:
            connect_args["check_same_thread"] = False

        self._engine = create_async_engine(database_url, echo=False, connect_args=connect_args)
        if "sqlite" in database_url:

            @event.listens_for(self._engine.sync_engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def initialize(self) -> None:
        """Create all tables."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        ensure_private_sqlite_file(str(self._engine.url))
        logger.info("database_initialized", tables=len(Base.metadata.tables))

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the supported session-factory integration point for repositories."""
        return self._session_factory

    async def close(self) -> None:
        await self._engine.dispose()

    async def ping(self) -> None:
        """Verify that the configured database can execute a query."""
        async with self._session_factory() as session:
            await session.execute(select(1))

    async def append_runtime_event(self, event: dict[str, Any], *, max_events: int = 1000) -> None:
        """Deprecated compatibility adapter; new code uses ``RunRepository.append``."""
        from app.security.persistence_redactor import PersistenceRedactor
        from app.services.run_ledger import RunRepository

        repository = RunRepository(self._session_factory, PersistenceRedactor())
        await repository.append(
            run_id=str(event["run_id"]),
            user_id=str(event.get("user_id", "default")),
            project_id=str(event.get("project_id", "default")),
            conversation_id=str(event["conversation_id"]),
            correlation_id=str(event["correlation_id"]),
            provider=str(event.get("provider", "unknown")),
            model=str(event.get("model", "unknown")),
            kind=str(event["kind"]),
            iteration=int(event["iteration"]),
            payload=event.get("data", {}),
        )
        # Preserve the historical diagnostic bound without truncating trajectories.
        # Active runs are retained even when they temporarily exceed the budget.
        await repository.prune_terminal_to_event_budget(max_events)

    async def recent_runtime_events(
        self, *, run_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        """Deprecated unscoped diagnostics retained for existing internal callers."""
        async with self._session_factory() as session:
            query = select(RuntimeEventRow)
            if run_id:
                query = query.where(RuntimeEventRow.run_id == run_id)
            result = await session.execute(query.order_by(RuntimeEventRow.id.desc()).limit(limit))
            return [
                {
                    "run_id": row.run_id,
                    "conversation_id": row.conversation_id,
                    "correlation_id": row.correlation_id,
                    "kind": row.kind,
                    "iteration": row.iteration,
                    "data": json.loads(cast(str, row.payload)),
                }
                for row in reversed(result.scalars().all())
            ]

    # --- Authentication ---

    async def create_user(
        self, username: str, password_hash: str, email: str = "", *, is_admin: bool = False
    ) -> dict:
        user_id = str(uuid.uuid4())
        async with self._session_factory() as session:
            row = UserRow(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                is_admin=int(is_admin),
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                msg = f"Username '{username}' already exists"
                raise ValueError(msg) from exc
        return {"user_id": user_id, "username": username, "is_admin": is_admin}

    async def get_user_by_username(self, username: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(UserRow).where(UserRow.username == username))
            row = result.scalar_one_or_none()
            return self._user_dict(row) if row is not None else None

    async def get_user(self, user_id: str) -> dict | None:
        async with self._session_factory() as session:
            row = await session.get(UserRow, user_id)
            return self._user_dict(row) if row is not None else None

    @staticmethod
    def _user_dict(row: UserRow) -> dict:
        return {
            "user_id": row.id,
            "username": row.username,
            "email": row.email,
            "password_hash": row.password_hash,
            "is_admin": bool(row.is_admin),
        }

    async def create_api_key(self, key_id: str, key_hash: str, user_id: str, name: str) -> None:
        async with self._session_factory() as session:
            session.add(ApiKeyRow(id=key_id, key_hash=key_hash, user_id=user_id, name=name))
            await session.commit()

    async def find_api_key_by_hash(self, key_hash: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(ApiKeyRow).where(ApiKeyRow.key_hash == key_hash))
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return {"user_id": row.user_id, "name": row.name}

    # --- Memory Store interface (for agent) ---

    async def store(self, conversation_id: str, message: dict) -> None:
        """Store a message in a conversation."""
        await self.store_message(conversation_id, message["role"], message["content"])

    async def store_message(
        self, conversation_id: str, role: str, content: str, user_id: str = "default"
    ) -> int | None:
        """Store a message and ensure its conversation metadata exists."""
        async with self._session_factory() as session:
            conversation = await session.get(ConversationRow, conversation_id)
            now = datetime.now(tz=UTC)
            if conversation is None:
                conversation = ConversationRow(
                    id=conversation_id, title="New Conversation", user_id=user_id
                )
                session.add(conversation)
            else:
                if conversation.user_id != user_id:
                    return
                conversation.is_active = 1
                conversation.updated_at = now
            row = MessageRow(
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=now,
            )
            session.add(row)
            await session.flush()
            message_id = int(row.id)
            await session.commit()
            return message_id

    async def retrieve(
        self, conversation_id: str, limit: int = 50, user_id: str | None = None
    ) -> list[dict]:
        """Retrieve messages for a conversation, optionally constrained to its owner."""
        async with self._session_factory() as session:
            query = select(MessageRow).where(MessageRow.conversation_id == conversation_id)
            if user_id is not None:
                query = query.join(
                    ConversationRow, ConversationRow.id == MessageRow.conversation_id
                ).where(ConversationRow.user_id == user_id)
            result = await session.execute(query.order_by(MessageRow.id).limit(limit))
            rows = result.scalars().all()
            return [{"role": r.role, "content": r.content} for r in rows]

    async def retrieve_with_metadata(
        self, conversation_id: str, limit: int = 50, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve message content plus stable source IDs for context provenance."""
        async with self._session_factory() as session:
            query = select(MessageRow).where(MessageRow.conversation_id == conversation_id)
            if user_id is not None:
                query = query.join(
                    ConversationRow, ConversationRow.id == MessageRow.conversation_id
                ).where(ConversationRow.user_id == user_id)
            rows = list(
                reversed(
                    (await session.scalars(query.order_by(MessageRow.id.desc()).limit(limit))).all()
                )
            )
            return [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    async def retrieve_through(
        self,
        conversation_id: str,
        through: datetime,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve an owner's messages at or before a timestamp in stable order."""
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(MessageRow)
                    .join(ConversationRow, ConversationRow.id == MessageRow.conversation_id)
                    .where(
                        MessageRow.conversation_id == conversation_id,
                        ConversationRow.user_id == user_id,
                        MessageRow.created_at <= through,
                    )
                    .order_by(MessageRow.created_at, MessageRow.id)
                    .limit(limit)
                )
            ).all()
            return [{"role": row.role, "content": row.content} for row in rows]

    async def get_message_count(self, conversation_id: str) -> int:
        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count(MessageRow.id)).where(
                    MessageRow.conversation_id == conversation_id
                )
            )
            return result.scalar_one()

    async def search_conversations(self, user_id: str, query: str, *, limit: int = 3) -> list[dict]:
        """Search only conversations owned by ``user_id`` using persisted DB messages."""
        terms = tuple(dict.fromkeys(word.casefold() for word in query.split() if len(word) > 2))
        if not terms:
            return []
        predicates = [
            func.lower(ConversationRow.title).contains(term)
            | func.lower(MessageRow.content).contains(term)
            for term in terms
        ]
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow, MessageRow)
                .join(MessageRow, MessageRow.conversation_id == ConversationRow.id)
                .where(ConversationRow.user_id == user_id)
                .where(*predicates)
                .order_by(ConversationRow.updated_at.desc(), MessageRow.id)
                .limit(min(max(limit, 1), 20) * 20)
            )
            grouped: dict[str, dict] = {}
            for conversation, message in result.all():
                item = grouped.setdefault(
                    conversation.id,
                    {
                        "conversation_id": conversation.id,
                        "title": conversation.title,
                        "saved_at": conversation.updated_at.isoformat(),
                        "message_count": 0,
                        "snippets": [],
                    },
                )
                item["message_count"] += 1
                item["snippets"].append(f"[{message.role}] {message.content}")
            return [
                {
                    "conversation_id": item["conversation_id"],
                    "title": item["title"],
                    "saved_at": item["saved_at"],
                    "message_count": item["message_count"],
                    "snippet": "\n".join(item["snippets"])[:300],
                }
                for item in list(grouped.values())[:limit]
            ]

    # --- Conversation CRUD ---

    async def create_conversation(self, conv_id: str, title: str, user_id: str = "default") -> dict:
        async with self._session_factory() as session:
            row = ConversationRow(id=conv_id, title=title, user_id=user_id)
            session.add(row)
            await session.commit()
            return {"id": conv_id, "title": title, "user_id": user_id}

    async def list_conversations(self, user_id: str = "default") -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ConversationRow, func.count(MessageRow.id))
                .outerjoin(MessageRow, MessageRow.conversation_id == ConversationRow.id)
                .where(ConversationRow.user_id == user_id)
                .where(ConversationRow.is_active == 1)
                .group_by(ConversationRow.id)
                .order_by(ConversationRow.updated_at.desc())
            )
            rows = result.all()
            return [
                {
                    "id": conversation.id,
                    "title": conversation.title,
                    "created_at": conversation.created_at.isoformat(),
                    "message_count": message_count,
                }
                for conversation, message_count in rows
            ]

    async def get_conversation(self, conv_id: str, user_id: str | None = None) -> dict | None:
        async with self._session_factory() as session:
            query = select(ConversationRow).where(ConversationRow.id == conv_id)
            if user_id is not None:
                query = query.where(ConversationRow.user_id == user_id)
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat()}

    async def delete_conversation(self, conv_id: str, user_id: str | None = None) -> bool:
        async with self._session_factory() as session:
            query = select(ConversationRow).where(ConversationRow.id == conv_id)
            if user_id is not None:
                query = query.where(ConversationRow.user_id == user_id)
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            if row:
                await session.execute(
                    delete(MessageRow).where(MessageRow.conversation_id == conv_id)
                )
                await session.delete(row)
                await session.commit()
                return True
            return False

    # --- Audit ---

    async def log_audit(self, entry: dict) -> None:
        async with self._session_factory() as session:
            row = AuditRow(
                timestamp=entry.get("timestamp", ""),
                agent_id=entry.get("agent_id", ""),
                action=entry.get("action", ""),
                resource=entry.get("resource", ""),
                parameters=json.dumps(entry.get("parameters", {})),
                result=entry.get("result", "success"),
                security_level=entry.get("security_level", "info"),
                correlation_id=entry.get("correlation_id", ""),
            )
            session.add(row)
            await session.commit()

    async def get_audit_entries(self, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
            )
            rows = result.scalars().all()
            return [
                {
                    "timestamp": r.timestamp,
                    "agent_id": r.agent_id,
                    "action": r.action,
                    "resource": r.resource,
                    "result": r.result,
                    "security_level": r.security_level,
                    "correlation_id": r.correlation_id,
                }
                for r in rows
            ]

    # --- Artifacts ---

    async def save_artifact(self, artifact: dict) -> dict:
        async with self._session_factory() as session:
            row = ArtifactRow(
                id=artifact["id"],
                conversation_id=artifact.get("conversation_id", ""),
                message_id=artifact.get("message_id", ""),
                title=artifact["title"],
                artifact_type=artifact["type"],
                language=artifact.get("language", ""),
                content=artifact["content"],
                version=artifact.get("version", 1),
            )
            session.add(row)
            await session.commit()
            return artifact

    async def get_artifact(self, artifact_id: str) -> dict | None:
        async with self._session_factory() as session:
            result = await session.execute(select(ArtifactRow).where(ArtifactRow.id == artifact_id))
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "title": row.title,
                "type": row.artifact_type,
                "language": row.language,
                "content": row.content,
                "version": row.version,
            }

    async def list_artifacts(self, conversation_id: str = "") -> list[dict]:
        async with self._session_factory() as session:
            q = select(ArtifactRow)
            if conversation_id:
                q = q.where(ArtifactRow.conversation_id == conversation_id)
            q = q.order_by(ArtifactRow.created_at.desc())
            result = await session.execute(q)
            rows = result.scalars().all()
            return [
                {
                    "id": r.id,
                    "conversation_id": r.conversation_id,
                    "title": r.title,
                    "type": r.artifact_type,
                    "language": r.language,
                    "content_length": len(r.content),
                    "version": r.version,
                }
                for r in rows
            ]
