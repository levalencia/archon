"""Evaluation harness for agent quality testing.

Runs the agent against a set of test cases and measures quality metrics.
Can be used in CI to block deployments if quality drops.

Metrics: correctness, relevance, safety, latency, cost

See: https://github.com/levalencia/production-ai-agents/
Concept: Evaluation framework (Phase 7 in plan, implemented early)
Course reference: Advanced Architectures L44, L63-L64
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger()


@dataclass
class EvalCase:
    """A single evaluation test case."""

    id: str
    input: str
    expected_output: str | None = None
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    max_latency_ms: float | None = None


@dataclass
class EvalResult:
    """Result of evaluating a single test case."""

    case_id: str
    passed: bool
    score: float  # 0.0 to 1.0
    response: str
    latency_ms: float
    checks: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class EvalSummary:
    """Summary of an evaluation run."""

    total: int
    passed: int
    failed: int
    avg_score: float
    avg_latency_ms: float
    pass_rate: float
    results: list[EvalResult] = field(default_factory=list)
    tags: dict[str, dict] = field(default_factory=dict)


class EvalHarness:
    """Evaluation harness for testing agent quality.

    Usage:
        harness = EvalHarness(agent_fn=my_agent.run)
        harness.add_case(EvalCase(id="q1", input="What is 2+2?", expected_contains=["4"]))
        summary = await harness.run()
        assert summary.pass_rate >= 0.85  # Quality gate
    """

    def __init__(
        self,
        agent_fn: object,
        quality_threshold: float = 0.85,
    ) -> None:
        self._agent_fn = agent_fn
        self._cases: list[EvalCase] = []
        self._quality_threshold = quality_threshold

    def add_case(self, case: EvalCase) -> None:
        """Add a test case."""
        self._cases.append(case)

    def add_cases(self, cases: list[EvalCase]) -> None:
        """Add multiple test cases."""
        self._cases.extend(cases)

    async def run(self) -> EvalSummary:
        """Run all evaluation cases and return summary."""
        results: list[EvalResult] = []

        for case in self._cases:
            result = await self._eval_case(case)
            results.append(result)

        # Calculate summary
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        avg_score = sum(r.score for r in results) / max(len(results), 1)
        avg_latency = sum(r.latency_ms for r in results) / max(len(results), 1)
        pass_rate = passed / max(len(results), 1)

        # Group by tags
        tag_stats: dict[str, dict] = {}
        for result in results:
            case = next(c for c in self._cases if c.id == result.case_id)
            for tag in case.tags:
                if tag not in tag_stats:
                    tag_stats[tag] = {"total": 0, "passed": 0}
                tag_stats[tag]["total"] += 1
                if result.passed:
                    tag_stats[tag]["passed"] += 1

        summary = EvalSummary(
            total=len(results),
            passed=passed,
            failed=failed,
            avg_score=round(avg_score, 4),
            avg_latency_ms=round(avg_latency, 2),
            pass_rate=round(pass_rate, 4),
            results=results,
            tags=tag_stats,
        )

        logger.info(
            "eval_run_complete",
            total=summary.total,
            passed=summary.passed,
            failed=summary.failed,
            pass_rate=summary.pass_rate,
            avg_score=summary.avg_score,
        )

        return summary

    async def _eval_case(self, case: EvalCase) -> EvalResult:
        """Evaluate a single test case."""
        checks: dict[str, bool] = {}
        start = time.monotonic()

        try:
            # Call the agent function
            if callable(self._agent_fn):
                response = await self._agent_fn(case.input)  # type: ignore[misc]
            else:
                response = str(self._agent_fn)

            latency_ms = (time.monotonic() - start) * 1000

            # Extract text from response
            if isinstance(response, dict):
                text = response.get("response", str(response))
            elif hasattr(response, "response"):
                text = response.response  # type: ignore[union-attr]
            else:
                text = str(response)

            # Run checks
            if case.expected_output:
                checks["exact_match"] = text.strip() == case.expected_output.strip()

            for phrase in case.expected_contains:
                checks[f"contains_{phrase[:20]}"] = phrase.lower() in text.lower()

            for phrase in case.expected_not_contains:
                checks[f"not_contains_{phrase[:20]}"] = phrase.lower() not in text.lower()

            if case.max_latency_ms:
                checks["latency"] = latency_ms <= case.max_latency_ms

            # Calculate score
            score = sum(1 for v in checks.values() if v) / len(checks) if checks else 1.0

            passed = all(checks.values()) if checks else True

            return EvalResult(
                case_id=case.id,
                passed=passed,
                score=round(score, 4),
                response=text,
                latency_ms=round(latency_ms, 2),
                checks=checks,
            )

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return EvalResult(
                case_id=case.id,
                passed=False,
                score=0.0,
                response="",
                latency_ms=round(latency_ms, 2),
                checks=checks,
                error=str(e),
            )

    def quality_gate(self, summary: EvalSummary) -> bool:
        """Check if the evaluation passes the quality gate.

        Returns True if pass_rate >= threshold.
        Use in CI: assert harness.quality_gate(summary)
        """
        passed = summary.pass_rate >= self._quality_threshold

        if not passed:
            logger.error(
                "quality_gate_failed",
                pass_rate=summary.pass_rate,
                threshold=self._quality_threshold,
            )

        return passed
