"""Deterministic warning rules for immutable evaluation cohorts."""

from __future__ import annotations

from datetime import UTC, datetime

from app.eval.drift import DriftThresholds, detect_drift, identity, summarize
from app.eval.persistence import EvaluationCaseResult, EvaluationRun


def _cohort(*, revision: str, scores: list[float], degraded: bool = False) -> EvaluationRun:
    now = datetime.now(tz=UTC)
    cases = tuple(
        EvaluationCaseResult(
            id=f"case-{index}",
            evaluation_id=f"eval-{revision}",
            source_run_id=f"run-{index}",
            case_key=f"key-{index}",
            passed=score >= 0.8,
            score=score,
            metrics={
                "latency_ms": 200 if degraded else 100,
                "total_tokens": 200 if degraded else 100,
                "cost_usd": 0.02 if degraded else 0.01,
                "abstained": degraded,
                "citation_rate": 0.5 if degraded else 1.0,
                "unsupported_rate": 0.2 if degraded else 0.0,
                "safety_failure": degraded,
            },
            checks=(),
            created_at=now,
        )
        for index, score in enumerate(scores)
    )
    return EvaluationRun(
        id=f"eval-{revision}",
        owner_id="owner",
        project_id="project",
        dataset_id="fixture",
        dataset_version="1",
        dataset_hash="a" * 64,
        model_revision=f"model-{revision}",
        provider_revision="provider-1",
        config_revision=f"config-{revision}",
        source_run_ids=tuple(c.source_run_id for c in cases),
        threshold=0.8,
        status="completed",
        passed=all(c.passed for c in cases),
        aggregate_metrics={},
        created_at=now,
        updated_at=now,
        completed_at=now,
        cases=cases,
    )


def test_drift_summary_covers_required_deterministic_metrics() -> None:
    cohort = _cohort(revision="a", scores=[0.1, 0.5, 0.9, 1.0])
    result = summarize(cohort)
    assert result == {
        "sample_count": 4,
        "pass_rate": 0.5,
        "mean_score": 0.625,
        "score_min": 0.1,
        "score_p10": 0.1,
        "score_p50": 0.5,
        "score_p90": 1.0,
        "score_max": 1.0,
        "mean_latency_ms": 100.0,
        "mean_tokens": 100.0,
        "mean_cost_usd": 0.01,
        "abstention_rate": 0.0,
        "citation_coverage": 1.0,
        "unsupported_claim_rate": 0.0,
        "safety_failure_rate": 0.0,
    }
    assert identity(cohort)["config_revision"] == "config-a"


def test_drift_has_explicit_minimum_sample_and_stable_warning_rules() -> None:
    baseline = _cohort(revision="a", scores=[1.0] * 5)
    candidate = _cohort(revision="b", scores=[0.5] * 5, degraded=True)
    _, _, _, too_small = detect_drift(baseline, candidate, DriftThresholds(minimum_sample_size=6))
    assert too_small == (
        {
            "metric": "sample_count",
            "direction": "insufficient_sample",
            "baseline_count": 5,
            "candidate_count": 5,
            "threshold": 6,
        },
    )

    _, _, deltas, warnings = detect_drift(
        baseline, candidate, DriftThresholds(minimum_sample_size=5)
    )
    metrics = {warning["metric"] for warning in warnings}
    assert metrics == {
        "pass_rate",
        "mean_score",
        "score_p10",
        "mean_latency_ms",
        "mean_tokens",
        "mean_cost_usd",
        "abstention_rate",
        "citation_coverage",
        "unsupported_claim_rate",
        "safety_failure_rate",
    }
    assert deltas["runtime_revision_changed"] is True
    assert all("p_value" not in warning and "significance" not in warning for warning in warnings)
