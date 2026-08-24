from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import TypeVar
from urllib.parse import urlsplit, urlunsplit

from .models import (
    Citation,
    Claim,
    Evidence,
    ResearchRun,
    RunMetadata,
    SearchResult,
    Stage,
    StageTrace,
    Usage,
)
from .ports import Planner, SearchProvider, Synthesizer

T = TypeVar("T")


@dataclass(frozen=True)
class WorkflowConfig:
    max_queries: int = 3
    results_per_query: int = 4
    max_tool_calls: int = 8
    max_concurrency: int = 3
    max_evidence: int = 6

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if value < 1:
                raise ValueError(f"{name} must be positive")


class ResearchWorkflow:
    def __init__(
        self,
        planner: Planner,
        search: SearchProvider,
        synthesizer: Synthesizer,
        config: WorkflowConfig | None = None,
    ) -> None:
        self.planner = planner
        self.search = search
        self.synthesizer = synthesizer
        self.config = config or WorkflowConfig()

    async def run(self, question: str) -> ResearchRun:
        started = perf_counter()
        traces: list[StageTrace] = []
        usage = Usage()

        async def stage(name: Stage, input_count: int, operation: Callable[[], Awaitable[T]]) -> T:
            stage_started = perf_counter()
            result = await operation()
            output_count = len(result) if isinstance(result, Sequence) else 1
            traces.append(
                StageTrace(name, (perf_counter() - stage_started) * 1000, input_count, output_count)
            )
            return result

        plan, plan_usage = await stage(
            Stage.PLAN, 1, lambda: self.planner.plan(question, self.config.max_queries)
        )
        queries = plan.queries[: min(self.config.max_queries, self.config.max_tool_calls)]

        search_active = 0
        search_peak = 0

        async def search_all() -> list[SearchResult]:
            nonlocal search_active, search_peak
            semaphore = asyncio.Semaphore(self.config.max_concurrency)

            async def one(query: str) -> list[SearchResult]:
                nonlocal search_active, search_peak
                async with semaphore:
                    search_active += 1
                    search_peak = max(search_peak, search_active)
                    try:
                        return await self.search.search(query, self.config.results_per_query)
                    finally:
                        search_active -= 1

            batches = await asyncio.gather(*(one(query) for query in queries))
            return [item for batch in batches for item in batch]

        results = await stage(Stage.SEARCH, len(queries), search_all)
        extracted = await stage(Stage.EXTRACT, len(results), lambda: _extract(results))
        unique = await stage(Stage.DEDUPLICATE, len(extracted), lambda: _deduplicate(extracted))
        ranked = await stage(
            Stage.RANK,
            len(unique),
            lambda: _rank(question, unique, self.config.max_evidence),
        )
        draft = await stage(
            Stage.SYNTHESIZE,
            len(ranked),
            lambda: self.synthesizer.synthesize(question, tuple(ranked)),
        )
        usage = _add_usage(_add_usage(usage, plan_usage), draft.usage)
        claims, citations, unsupported = await stage(
            Stage.VERIFY, len(draft.claims), lambda: _verify(draft.claims, ranked)
        )
        answer = "\n".join(
            f"{claim.text} " + " ".join(f"[{evidence_id}]" for evidence_id in claim.evidence_ids)
            for claim in claims
        )
        return ResearchRun(
            question=question,
            answer=answer,
            claims=claims,
            citations=citations,
            evidence=tuple(ranked),
            unsupported_claims=unsupported,
            trajectory=tuple(traces),
            metadata=RunMetadata(
                latency_ms=(perf_counter() - started) * 1000,
                tool_calls=len(queries),
                llm_calls=2,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=usage.cost_usd,
                max_concurrency=self.config.max_concurrency,
                peak_concurrency=search_peak,
                search_tasks=len(queries),
            ),
        )


async def _extract(results: list[SearchResult]) -> list[Evidence]:
    return [
        Evidence(f"E{index}", item.url, item.title, item.content.strip() or item.snippet.strip())
        for index, item in enumerate(results, 1)
        if item.content.strip() or item.snippet.strip()
    ]


async def _deduplicate(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    unique: list[Evidence] = []
    for item in evidence:
        parts = urlsplit(item.url)
        canonical = urlunsplit(
            (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
        )
        key = (canonical, " ".join(item.quote.lower().split()))
        if key not in seen:
            seen.add(key)
            unique.append(replace(item, url=canonical))
    return [replace(item, id=f"E{index}") for index, item in enumerate(unique, 1)]


async def _rank(question: str, evidence: list[Evidence], limit: int) -> list[Evidence]:
    terms = set(re.findall(r"[a-z0-9]+", question.lower()))
    scored = [
        replace(
            item,
            score=len(terms & set(re.findall(r"[a-z0-9]+", f"{item.title} {item.quote}".lower())))
            / max(len(terms), 1),
        )
        for item in evidence
    ]
    return sorted(scored, key=lambda item: (-item.score, item.url))[:limit]


async def _verify(
    claims: tuple[Claim, ...], evidence: list[Evidence]
) -> tuple[tuple[Claim, ...], tuple[Citation, ...], tuple[str, ...]]:
    by_id = {item.id: item for item in evidence}
    supported: list[Claim] = []
    unsupported: list[str] = []
    for claim in claims:
        sources = [by_id[key] for key in claim.evidence_ids if key in by_id]
        claim_terms = set(re.findall(r"[a-z0-9]+", claim.text.lower()))
        grounded = any(
            len(claim_terms & set(re.findall(r"[a-z0-9]+", source.quote.lower())))
            / max(len(claim_terms), 1)
            >= 0.5
            for source in sources
        )
        if sources and len(sources) == len(claim.evidence_ids) and grounded:
            supported.append(claim)
        else:
            unsupported.append(claim.text)
    cited_ids = dict.fromkeys(key for claim in supported for key in claim.evidence_ids)
    citations = tuple(
        Citation(key, by_id[key].url, by_id[key].title, by_id[key].quote) for key in cited_ids
    )
    return tuple(supported), citations, tuple(unsupported)


def _add_usage(left: Usage, right: Usage) -> Usage:
    return Usage(
        left.input_tokens + right.input_tokens,
        left.output_tokens + right.output_tokens,
        round(left.cost_usd + right.cost_usd, 8),
    )
