"""Deterministic drift summaries and durable owner-scoped comparisons.

Warnings are fixed threshold rules, not hypothesis tests.  This module deliberately
uses no p-values or statistical-significance terminology.
"""
# ruff: noqa: B008 -- immutable threshold defaults are safe and intentional.

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.eval.persistence import EvaluationRepository, EvaluationRun, JSONValue
from app.services.db_store import EvalDriftReportRow


@dataclass(frozen=True, slots=True)
class DriftThresholds:
    minimum_sample_size: int = 20
    pass_rate_drop: float = 0.05
    mean_score_drop: float = 0.05
    score_p10_drop: float = 0.10
    latency_increase_ratio: float = 0.20
    token_increase_ratio: float = 0.20
    cost_increase_ratio: float = 0.20
    abstention_increase: float = 0.05
    citation_coverage_drop: float = 0.05
    unsupported_claim_increase: float = 0.02
    safety_failure_increase: float = 0.01

    def __post_init__(self) -> None:
        if not 2 <= self.minimum_sample_size <= 10_000:
            raise ValueError("minimum_sample_size must be between 2 and 10000")
        for name, value in asdict(self).items():
            if name != "minimum_sample_size" and (not math.isfinite(value) or value < 0):
                raise ValueError("warning thresholds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class DriftWarning:
    metric: str
    direction: str
    delta: float
    threshold: float


@dataclass(frozen=True, slots=True)
class DriftReport:
    id: str
    owner_id: str
    project_id: str
    baseline_eval_id: str
    candidate_eval_id: str
    baseline_identity: Mapping[str, JSONValue]
    candidate_identity: Mapping[str, JSONValue]
    baseline_summary: Mapping[str, JSONValue]
    candidate_summary: Mapping[str, JSONValue]
    deltas: Mapping[str, JSONValue]
    warnings: tuple[Mapping[str, JSONValue], ...]
    minimum_sample_size: int
    created_at: datetime


_METRICS = (
    "pass_rate",
    "mean_score",
    "score_p10",
    "score_p50",
    "score_p90",
    "mean_latency_ms",
    "mean_tokens",
    "mean_cost_usd",
    "abstention_rate",
    "citation_coverage",
    "unsupported_claim_rate",
    "safety_failure_rate",
)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if not isinstance(value, int | float):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _quantile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank with a stable zero-based index; no interpolation/library drift.
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 6)


def summarize(evaluation: EvaluationRun) -> dict[str, JSONValue]:
    """Return a fixed, metadata-only summary of an immutable evaluation."""
    if evaluation.status != "completed" or not evaluation.cases:
        raise ValueError("drift comparison requires completed evaluations with cases")
    scores = [case.score for case in evaluation.cases]

    def values(key: str) -> list[float]:
        return [
            item
            for case in evaluation.cases
            if (item := _number(case.metrics.get(key))) is not None
        ]

    citations = values("citation_rate")
    unsupported = values("unsupported_rate")
    latencies = values("latency_ms")
    tokens = values("total_tokens")
    costs = values("cost_usd")
    abstentions = values("abstained")
    safety = values("safety_failure")
    count = len(evaluation.cases)
    return {
        "sample_count": count,
        "pass_rate": round(sum(case.passed for case in evaluation.cases) / count, 6),
        "mean_score": _mean(scores),
        "score_min": round(min(scores), 6),
        "score_p10": _quantile(scores, 0.10),
        "score_p50": _quantile(scores, 0.50),
        "score_p90": _quantile(scores, 0.90),
        "score_max": round(max(scores), 6),
        "mean_latency_ms": _mean(latencies),
        "mean_tokens": _mean(tokens),
        "mean_cost_usd": _mean(costs),
        "abstention_rate": _mean(abstentions),
        "citation_coverage": _mean(citations),
        "unsupported_claim_rate": _mean(unsupported),
        "safety_failure_rate": _mean(safety),
    }


def identity(evaluation: EvaluationRun) -> dict[str, JSONValue]:
    return {
        "dataset_id": evaluation.dataset_id,
        "dataset_version": evaluation.dataset_version,
        "dataset_hash": evaluation.dataset_hash,
        "model_revision": evaluation.model_revision,
        "provider_revision": evaluation.provider_revision,
        "config_revision": evaluation.config_revision,
    }


def detect_drift(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    thresholds: DriftThresholds = DriftThresholds(),
) -> tuple[
    dict[str, JSONValue],
    dict[str, JSONValue],
    dict[str, JSONValue],
    tuple[dict[str, JSONValue], ...],
]:
    """Compare cohorts using only stable arithmetic and explicit warning thresholds."""
    before, after = summarize(baseline), summarize(candidate)
    deltas: dict[str, JSONValue] = {}
    for metric in _METRICS:
        left, right = _number(before.get(metric)), _number(after.get(metric))
        deltas[metric] = None if left is None or right is None else round(right - left, 6)
    deltas["dataset_revision_changed"] = (
        identity(baseline)["dataset_hash"] != identity(candidate)["dataset_hash"]
    )
    deltas["runtime_revision_changed"] = any(
        identity(baseline)[key] != identity(candidate)[key]
        for key in ("model_revision", "provider_revision", "config_revision")
    )
    if (
        int(before["sample_count"]) < thresholds.minimum_sample_size
        or int(after["sample_count"]) < thresholds.minimum_sample_size
    ):
        return (
            before,
            after,
            deltas,
            (
                {
                    "metric": "sample_count",
                    "direction": "insufficient_sample",
                    "baseline_count": before["sample_count"],
                    "candidate_count": after["sample_count"],
                    "threshold": thresholds.minimum_sample_size,
                },
            ),
        )

    rules = (
        ("pass_rate", "decrease", thresholds.pass_rate_drop),
        ("mean_score", "decrease", thresholds.mean_score_drop),
        ("score_p10", "decrease", thresholds.score_p10_drop),
        ("mean_latency_ms", "ratio_increase", thresholds.latency_increase_ratio),
        ("mean_tokens", "ratio_increase", thresholds.token_increase_ratio),
        ("mean_cost_usd", "ratio_increase", thresholds.cost_increase_ratio),
        ("abstention_rate", "increase", thresholds.abstention_increase),
        ("citation_coverage", "decrease", thresholds.citation_coverage_drop),
        ("unsupported_claim_rate", "increase", thresholds.unsupported_claim_increase),
        ("safety_failure_rate", "increase", thresholds.safety_failure_increase),
    )
    warnings: list[dict[str, JSONValue]] = []
    for metric, direction, threshold in rules:
        left, right = _number(before[metric]), _number(after[metric])
        if left is None or right is None:
            continue
        delta = right - left
        observed = delta
        triggered = delta >= threshold if direction == "increase" else -delta >= threshold
        if direction == "ratio_increase":
            observed = 0.0 if left == 0 and right == 0 else math.inf if left == 0 else delta / left
            triggered = observed >= threshold
        if triggered:
            warnings.append(
                {
                    "metric": metric,
                    "direction": direction,
                    "delta": round(delta, 6),
                    "observed_ratio": None if not math.isfinite(observed) else round(observed, 6),
                    "threshold": threshold,
                }
            )
    return before, after, deltas, tuple(warnings)


class DriftService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], evaluations: EvaluationRepository
    ) -> None:
        self._sessions, self._evaluations = sessions, evaluations

    async def compare(
        self,
        owner_id: str,
        *,
        project_id: str,
        baseline_eval_id: str,
        candidate_eval_id: str,
        thresholds: DriftThresholds = DriftThresholds(),
    ) -> DriftReport:
        if baseline_eval_id == candidate_eval_id:
            raise ValueError("baseline and candidate evaluations must differ")
        if thresholds != DriftThresholds(minimum_sample_size=thresholds.minimum_sample_size):
            raise ValueError("custom drift thresholds are not supported")
        baseline = await self._evaluations.get(owner_id, baseline_eval_id)
        candidate = await self._evaluations.get(owner_id, candidate_eval_id)
        if (
            baseline is None
            or candidate is None
            or baseline.project_id != project_id
            or candidate.project_id != project_id
        ):
            raise LookupError("evaluation cohort not found")
        if any(
            value == "unknown" or value.endswith("-unresolved")
            for value in (
                baseline.model_revision,
                baseline.provider_revision,
                baseline.config_revision,
                candidate.model_revision,
                candidate.provider_revision,
                candidate.config_revision,
            )
        ):
            raise ValueError("drift comparison requires versioned cohort identities")
        before, after, deltas, warnings = detect_drift(baseline, candidate, thresholds)
        row = EvalDriftReportRow(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            project_id=project_id,
            baseline_eval_id=baseline.id,
            candidate_eval_id=candidate.id,
            baseline_identity_json=identity(baseline),
            candidate_identity_json=identity(candidate),
            baseline_summary_json=before,
            candidate_summary_json=after,
            deltas_json=deltas,
            warnings_json=list(warnings),
            minimum_sample_size=thresholds.minimum_sample_size,
            created_at=datetime.now(tz=UTC),
        )
        async with self._sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(EvalDriftReportRow).where(
                        EvalDriftReportRow.owner_id == owner_id,
                        EvalDriftReportRow.project_id == project_id,
                        EvalDriftReportRow.baseline_eval_id == baseline.id,
                        EvalDriftReportRow.candidate_eval_id == candidate.id,
                        EvalDriftReportRow.minimum_sample_size == thresholds.minimum_sample_size,
                    )
                )
                if existing is None:
                    raise
                row = existing
        return self._model(row)

    async def get(
        self, owner_id: str, report_id: str, *, project_id: str | None = None
    ) -> DriftReport | None:
        query = select(EvalDriftReportRow).where(
            EvalDriftReportRow.id == report_id, EvalDriftReportRow.owner_id == owner_id
        )
        if project_id is not None:
            query = query.where(EvalDriftReportRow.project_id == project_id)
        async with self._sessions() as session:
            row = await session.scalar(query)
        return None if row is None else self._model(row)

    @staticmethod
    def _model(row: EvalDriftReportRow) -> DriftReport:
        return DriftReport(
            id=str(row.id),
            owner_id=str(row.owner_id),
            project_id=str(row.project_id),
            baseline_eval_id=str(row.baseline_eval_id),
            candidate_eval_id=str(row.candidate_eval_id),
            baseline_identity=cast(dict[str, JSONValue], row.baseline_identity_json),
            candidate_identity=cast(dict[str, JSONValue], row.candidate_identity_json),
            baseline_summary=cast(dict[str, JSONValue], row.baseline_summary_json),
            candidate_summary=cast(dict[str, JSONValue], row.candidate_summary_json),
            deltas=cast(dict[str, JSONValue], row.deltas_json),
            warnings=tuple(cast(list[dict[str, JSONValue]], row.warnings_json)),
            minimum_sample_size=int(row.minimum_sample_size),
            created_at=cast(datetime, row.created_at),
        )
