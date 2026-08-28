"""Deterministic evaluation of completed, owner-scoped recorded runs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from app.eval.fixtures import EvaluationFixture, EvaluationFixtureCase, load_evaluation_fixture
from app.eval.persistence import EvaluationRepository, EvaluationRun, JSONValue
from app.runtime.run_models import RunEventRecord, RunRecord
from app.services.run_ledger import RunRepository

_DEFAULT_DATASET_PATH = Path(__file__).with_name("datasets") / "grounded-v1.json"
_CONFIG_REVISION = "runtime-schema-v1"


class EvaluationRequestError(ValueError):
    """The requested dataset, mapping, or source run is invalid."""


class SourceRunNotFoundError(EvaluationRequestError):
    """A source run is absent or outside the caller's owner/project scope."""


class SourceRunNotCompletedError(EvaluationRequestError):
    """A source run exists but is not successfully completed."""


@dataclass(frozen=True, slots=True)
class EvaluationItem:
    run_id: str
    case_key: str


@dataclass(frozen=True, slots=True)
class _ComputedCase:
    source_run_id: str
    case_key: str
    passed: bool
    score: float
    metrics: Mapping[str, object]
    checks: tuple[Mapping[str, object], ...]


class EvaluationService:
    """Evaluate immutable ledger data without invoking a model, retriever, or tool."""

    def __init__(
        self,
        runs: RunRepository,
        evaluations: EvaluationRepository,
        *,
        dataset_paths: Mapping[str, Path] | None = None,
    ) -> None:
        self._runs = runs
        self._evaluations = evaluations
        self._dataset_paths = dict(dataset_paths or {"grounded-v1": _DEFAULT_DATASET_PATH})

    async def evaluate(
        self,
        owner_id: str,
        *,
        project_id: str,
        dataset_id: str,
        threshold: float,
        items: Sequence[EvaluationItem],
    ) -> EvaluationRun:
        if not owner_id or not project_id:
            raise EvaluationRequestError("owner and project are required")
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise EvaluationRequestError("threshold must be finite and between zero and one")
        fixture = self._load_dataset(dataset_id)
        mapping = self._validate_mapping(fixture, items)

        computed: list[_ComputedCase] = []
        revisions: set[tuple[str, str]] = set()
        for item in mapping:
            run = await self._runs.get(owner_id, item.run_id)
            if run is None or run.project_id != project_id:
                raise SourceRunNotFoundError("source run not found")
            if run.status != "completed" or run.completed_at is None:
                raise SourceRunNotCompletedError("source run must be completed")
            revisions.add((run.model, run.provider))
            events = await self._stored_events(owner_id, item.run_id)
            computed.append(
                self._evaluate_case(
                    run,
                    events,
                    next(case for case in fixture.cases if case.key == item.case_key),
                    threshold,
                )
            )

        if len(revisions) != 1:
            raise EvaluationRequestError("all cohort runs must use one model/provider revision")
        inferred_model, inferred_provider = next(iter(revisions))
        evaluation = await self._evaluations.create(
            owner_id,
            project_id=project_id,
            dataset_id=fixture.dataset_id,
            dataset_version=fixture.version,
            dataset_hash=fixture.content_hash,
            source_run_ids=tuple(item.run_id for item in mapping),
            threshold=threshold,
            model_revision=inferred_model,
            provider_revision=inferred_provider,
            config_revision=_CONFIG_REVISION,
        )
        try:
            for result in computed:
                await self._evaluations.append_case(
                    owner_id,
                    evaluation.id,
                    source_run_id=result.source_run_id,
                    case_key=result.case_key,
                    passed=result.passed,
                    score=result.score,
                    metrics=result.metrics,
                    checks=result.checks,
                )
            aggregate = self._aggregate(computed)
            return await self._evaluations.finalize(
                owner_id,
                evaluation.id,
                status="completed",
                passed=all(item.passed for item in computed),
                aggregate_metrics=aggregate,
            )
        except Exception:
            # Once an evaluation ID exists, every handled failure is made terminal. The
            # finalize update is itself atomic and owner/status guarded.
            current = await self._evaluations.get(owner_id, evaluation.id)
            if current is not None and current.status == "running":
                await self._evaluations.finalize(
                    owner_id,
                    evaluation.id,
                    status="failed",
                    passed=None,
                    aggregate_metrics={"case_count": len(current.cases)},
                )
            raise

    async def _stored_events(self, owner_id: str, run_id: str) -> tuple[RunEventRecord, ...]:
        """Read the complete immutable trajectory through the owner-scoped ledger API."""
        events: list[RunEventRecord] = []
        after_sequence = 0
        while True:
            page = await self._runs.events(
                owner_id,
                run_id,
                limit=100,
                after_sequence=after_sequence,
            )
            if page is None:  # Preserve non-disclosing owner semantics if the run disappeared.
                raise SourceRunNotFoundError("source run not found")
            events.extend(page.items)
            if len(page.items) < page.limit:
                return tuple(events)
            after_sequence = page.items[-1].sequence

    async def get(self, owner_id: str, evaluation_id: str) -> EvaluationRun | None:
        return await self._evaluations.get(owner_id, evaluation_id)

    async def list(
        self,
        owner_id: str,
        *,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[EvaluationRun, ...]:
        return cast(
            tuple[EvaluationRun, ...],
            await self._evaluations.list(
                owner_id, project_id=project_id, limit=limit, offset=offset
            ),
        )

    async def compare(self, owner_id: str, a: str, b: str) -> dict[str, JSONValue] | None:
        left = await self.get(owner_id, a)
        right = await self.get(owner_id, b)
        if left is None or right is None:
            return None
        numeric_keys = sorted(set(left.aggregate_metrics) | set(right.aggregate_metrics))
        delta: dict[str, JSONValue] = {}
        for key in numeric_keys:
            left_value = left.aggregate_metrics.get(key)
            right_value = right.aggregate_metrics.get(key)
            if (
                isinstance(left_value, int | float)
                and not isinstance(left_value, bool)
                and isinstance(right_value, int | float)
                and not isinstance(right_value, bool)
            ):
                delta[key] = round(float(right_value) - float(left_value), 6)
        return {
            "a_id": left.id,
            "b_id": right.id,
            "a_passed": left.passed,
            "b_passed": right.passed,
            "metric_delta_b_minus_a": delta,
        }

    def _load_dataset(self, dataset_id: str) -> EvaluationFixture:
        path = self._dataset_paths.get(dataset_id)
        if path is None:
            raise EvaluationRequestError("dataset is not allowlisted")
        fixture = load_evaluation_fixture(path)
        if fixture.dataset_id != dataset_id:
            raise EvaluationRequestError("dataset identity does not match its allowlist entry")
        return fixture

    @staticmethod
    def _validate_mapping(
        fixture: EvaluationFixture, items: Sequence[EvaluationItem]
    ) -> tuple[EvaluationItem, ...]:
        provided = tuple(items)
        expected_keys = {case.key for case in fixture.cases}
        case_keys = [item.case_key for item in provided]
        run_ids = [item.run_id for item in provided]
        if any(not item.run_id or not item.case_key for item in provided):
            raise EvaluationRequestError("run_id and case_key are required")
        if len(case_keys) != len(set(case_keys)) or set(case_keys) != expected_keys:
            raise EvaluationRequestError("items must map every dataset case key exactly once")
        if len(run_ids) != len(set(run_ids)):
            raise EvaluationRequestError("source run IDs must be unique")
        # Fixture order makes persistence and aggregate output stable regardless of request order.
        by_case = {item.case_key: item for item in provided}
        return tuple(by_case[case.key] for case in fixture.cases)

    @staticmethod
    def _evaluate_case(
        run: RunRecord,
        events: tuple[RunEventRecord, ...],
        case: EvaluationFixtureCase,
        threshold: float,
    ) -> _ComputedCase:
        evidence_count = 0
        supported_count = 0
        unsupported_count = 0
        citation_count = 0
        grounded_event_seen = False
        safety_failure = False
        for event in events:
            payload = event.payload
            if event.kind in {"policy_denied", "safety_failure", "compliance_blocked"}:
                safety_failure = True
            if event.kind == "evidence_retrieved":
                evidence_count = _nonnegative_int(payload.get("evidence_count", 0))
            elif event.kind == "claim_verified":
                supported_count = _nonnegative_int(payload.get("supported_count", 0))
                unsupported_count = _nonnegative_int(payload.get("unsupported_count", 0))
            elif event.kind == "grounded_answer":
                grounded_event_seen = True
                supported_count = _nonnegative_int(payload.get("supported_count", supported_count))
                unsupported_count = _nonnegative_int(
                    payload.get("unsupported_count", unsupported_count)
                )
                citations = payload.get("citation_ids", ())
                citation_count = len(citations) if isinstance(citations, list | tuple) else 0

        total_claims = supported_count + unsupported_count
        support_rate = supported_count / total_claims if total_claims else 1.0
        unsupported_rate = unsupported_count / total_claims if total_claims else 0.0
        citation_rate = (
            min(citation_count, supported_count) / supported_count if supported_count else 1.0
        )
        actual_grounded = grounded_event_seen and supported_count > 0 and unsupported_count == 0
        summary = run.answer_summary or ""
        folded = summary.casefold()
        checks: list[dict[str, object]] = [
            {"name": "grounded", "passed": actual_grounded is case.grounded}
        ]
        checks.extend(
            {
                "name": f"contains:{index}",
                "passed": expected.casefold() in folded,
            }
            for index, expected in enumerate(case.expected_contains)
        )
        checks.extend(
            {
                "name": f"not_contains:{index}",
                "passed": unexpected.casefold() not in folded,
            }
            for index, unexpected in enumerate(case.expected_not_contains)
        )
        score = sum(bool(check["passed"]) for check in checks) / len(checks)
        metrics: dict[str, object] = {
            "grounded": actual_grounded,
            "evidence_count": evidence_count,
            "supported_count": supported_count,
            "unsupported_count": unsupported_count,
            "citation_count": citation_count,
            "citation_rate": round(citation_rate, 6),
            "support_rate": round(support_rate, 6),
            "unsupported_rate": round(unsupported_rate, 6),
            "abstained": not grounded_event_seen and supported_count == 0,
            "safety_failure": safety_failure,
            "latency_ms": run.latency_ms,
            "cost_usd": run.cost_usd,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "total_tokens": run.total_tokens,
        }
        return _ComputedCase(
            source_run_id=run.run_id,
            case_key=case.key,
            passed=score >= threshold,
            score=round(score, 6),
            metrics=metrics,
            checks=tuple(checks),
        )

    @staticmethod
    def _aggregate(cases: Sequence[_ComputedCase]) -> dict[str, object]:
        count = len(cases)
        metric_names = ("citation_rate", "support_rate", "unsupported_rate")
        aggregate: dict[str, object] = {
            "case_count": count,
            "passed_count": sum(item.passed for item in cases),
            "failed_count": sum(not item.passed for item in cases),
            "pass_rate": round(sum(item.passed for item in cases) / count, 6),
            "mean_score": round(sum(item.score for item in cases) / count, 6),
            "total_tokens": sum(cast(int, item.metrics["total_tokens"]) for item in cases),
            "total_cost_usd": round(
                sum(float(cast(float | None, item.metrics["cost_usd"]) or 0.0) for item in cases),
                6,
            ),
        }
        latencies = [
            cast(float, item.metrics["latency_ms"])
            for item in cases
            if item.metrics["latency_ms"] is not None
        ]
        aggregate["mean_latency_ms"] = (
            round(sum(latencies) / len(latencies), 6) if latencies else None
        )
        for name in metric_names:
            aggregate[f"mean_{name}"] = round(
                sum(cast(float, item.metrics[name]) for item in cases) / count, 6
            )
        return aggregate


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value
