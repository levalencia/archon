from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.research import (
    Claim,
    Draft,
    Evidence,
    Plan,
    ResearchWorkflow,
    SearchResult,
    Stage,
    Usage,
    WorkflowConfig,
    evaluate,
)
from app.research.api import router


class Planner:
    async def plan(self, question: str, max_queries: int) -> tuple[Plan, Usage]:
        return Plan(question, ("liquid cooling", "free cooling", "unused")[:max_queries]), Usage(
            10, 4, 0.001
        )


class Search:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.peak = 0

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        self.calls.append(query)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.001)
        self.active -= 1
        records = {
            "liquid cooling": SearchResult(
                "https://example.org/liquid?utm=x",
                "Liquid cooling",
                "Liquid cooling saves energy.",
                "Liquid cooling saves energy.",
            ),
            "free cooling": SearchResult(
                "https://example.org/free/",
                "Free cooling",
                "Free cooling reduces chiller use.",
                "Free cooling reduces chiller use.",
            ),
            "unused": SearchResult(
                "https://example.org/unused", "Unused", "Unused evidence.", "Unused evidence."
            ),
        }
        return [records[query]][:limit]


class Synthesizer:
    async def synthesize(self, question: str, evidence: tuple[Evidence, ...]) -> Draft:
        del question
        ids = {item.url: item.id for item in evidence}
        return Draft(
            (
                Claim("Liquid cooling saves energy.", (ids["https://example.org/liquid"],)),
                Claim("Free cooling reduces chiller use.", (ids["https://example.org/free"],)),
                Claim("This is unsupported.", ("missing",)),
            ),
            Usage(40, 20, 0.004),
        )


class UnsupportedTextSynthesizer:
    async def synthesize(self, question: str, evidence: tuple[Evidence, ...]) -> Draft:
        del question
        return Draft((Claim("Mars is made entirely of cheese.", (evidence[0].id,)),))


@pytest.mark.asyncio
async def test_verifier_rejects_semantically_unsupported_claim_with_valid_citation() -> None:
    run = await ResearchWorkflow(
        Planner(), Search(), UnsupportedTextSynthesizer(), WorkflowConfig(max_tool_calls=1)
    ).run("cooling")
    assert run.claims == ()
    assert run.citations == ()
    assert run.unsupported_claims == ("Mars is made entirely of cheese.",)


@pytest.mark.asyncio
async def test_pipeline_is_bounded_grounded_ranked_and_observable() -> None:
    search = Search()
    workflow = ResearchWorkflow(
        Planner(),
        search,
        Synthesizer(),
        WorkflowConfig(max_queries=3, max_tool_calls=2, max_concurrency=2),
    )
    run = await workflow.run("What cooling saves energy?")

    assert [trace.stage for trace in run.trajectory] == list(Stage)
    assert search.calls == ["liquid cooling", "free cooling"]
    assert search.peak == 2
    assert run.metadata.tool_calls == 2
    assert run.metadata.llm_calls == 2
    assert run.metadata.max_concurrency == 2
    assert run.metadata.peak_concurrency == 2
    assert run.metadata.search_tasks == 2
    assert (run.metadata.input_tokens, run.metadata.output_tokens, run.metadata.cost_usd) == (
        50,
        24,
        0.005,
    )
    assert run.unsupported_claims == ("This is unsupported.",)
    assert len(run.claims) == len(run.citations) == 2
    assert all(
        citation.quote and f"[{citation.evidence_id}]" in run.answer for citation in run.citations
    )
    assert {citation.url for citation in run.citations} == {
        "https://example.org/liquid",
        "https://example.org/free",
    }


class DuplicateSearch:
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                "https://EXAMPLE.org/article/?utm_source=test",
                "Original",
                "Grounded duplicate content.",
                "Grounded duplicate content.",
            ),
            SearchResult(
                "https://example.org/article",
                "Duplicate",
                "Grounded duplicate content.",
                "Grounded duplicate content.",
            ),
        ][:limit]


@pytest.mark.asyncio
async def test_duplicate_urls_are_collapsed_before_ranking() -> None:
    run = await ResearchWorkflow(
        Planner(), DuplicateSearch(), UnsupportedTextSynthesizer(), WorkflowConfig(max_tool_calls=1)
    ).run("duplicate")
    assert len(run.evidence) == 1
    assert run.evidence[0].url == "https://example.org/article"


def test_workflow_config_rejects_unbounded_or_zero_limits() -> None:
    with pytest.raises(ValueError, match="positive"):
        WorkflowConfig(max_tool_calls=0)


def test_registered_offline_api_runs_full_vertical_slice() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post(
        "/v1/research",
        json={
            "question": "What saves cooling energy?",
            "sources": [
                {
                    "url": "https://example.org/cooling?tracking=1",
                    "title": "Cooling",
                    "content": (
                        "Liquid cooling saves cooling energy. "
                        "A second sentence is omitted from the claim."
                    ),
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Liquid cooling saves cooling energy. [E1]"
    assert payload["citations"][0]["url"] == "https://example.org/cooling"
    assert [item["stage"] for item in payload["trajectory"]] == [stage.value for stage in Stage]
    assert payload["metadata"]["tool_calls"] == 1


def test_api_validates_source_and_bounds() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.post("/v1/research", json={"question": "", "sources": []}).status_code == 422
    assert (
        client.post(
            "/v1/research",
            json={"question": "q", "sources": [{"url": "not-a-url", "title": "x", "content": "x"}]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "case",
    json.loads((Path(__file__).parent / "fixtures/research_golden.json").read_text()),
    ids=lambda case: case["id"],
)
def test_deterministic_golden_research_cases(case: dict) -> None:
    app = FastAPI()
    app.include_router(router)
    payload = (
        TestClient(app)
        .post("/v1/research", json={"question": case["question"], "sources": case["sources"]})
        .json()
    )

    assert all(term.lower() in payload["answer"].lower() for term in case["expected_terms"])
    assert {citation["url"] for citation in payload["citations"]} == set(case["expected_urls"])
    assert payload["unsupported_claims"] == []
    assert payload["metadata"]["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_evaluation_scores_source_and_citation_coverage() -> None:
    run = await ResearchWorkflow(
        Planner(), Search(), Synthesizer(), WorkflowConfig(max_tool_calls=2)
    ).run("cooling")
    result = evaluate(run, {"https://example.org/liquid", "https://example.org/free"})
    assert result.source_coverage == 1.0
    assert result.citation_coverage == pytest.approx(2 / 3)
    assert result.unsupported_claim_rate == pytest.approx(1 / 3)
    assert not result.passed
