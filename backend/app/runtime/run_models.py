"""Immutable public models for the durable run ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    user_id: str
    project_id: str
    conversation_id: str
    correlation_id: str
    provider: str
    model: str
    schema_version: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    stop_reason: str | None = None
    answer_summary: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: float | None = None
    iterations: int = 0
    parent_run_id: str | None = None
    fork_source_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    run_id: str
    project_id: str
    conversation_id: str
    correlation_id: str
    sequence: int
    event_at: datetime
    kind: str
    schema_version: int
    iteration: int
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunPage:
    items: tuple[RunRecord, ...]
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class EventPage:
    items: tuple[RunEventRecord, ...]
    limit: int
    after_sequence: int
