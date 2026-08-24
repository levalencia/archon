from __future__ import annotations

from dataclasses import dataclass

from .models import ResearchRun


@dataclass(frozen=True)
class Evaluation:
    source_coverage: float
    citation_coverage: float
    unsupported_claim_rate: float
    latency_ms: float
    cost_usd: float
    passed: bool


def evaluate(run: ResearchRun, expected_source_urls: set[str]) -> Evaluation:
    actual_urls = {citation.url for citation in run.citations}
    source_coverage = (
        len(actual_urls & expected_source_urls) / len(expected_source_urls)
        if expected_source_urls
        else 1.0
    )
    total_claims = len(run.claims) + len(run.unsupported_claims)
    citation_coverage = len(run.claims) / total_claims if total_claims else 1.0
    unsupported_rate = len(run.unsupported_claims) / total_claims if total_claims else 0.0
    return Evaluation(
        source_coverage=source_coverage,
        citation_coverage=citation_coverage,
        unsupported_claim_rate=unsupported_rate,
        latency_ms=run.metadata.latency_ms,
        cost_usd=run.metadata.cost_usd,
        passed=source_coverage == 1.0 and citation_coverage == 1.0 and unsupported_rate == 0.0,
    )
