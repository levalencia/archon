from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .models import Claim, Draft, Evidence, Plan, SearchResult, Usage
from .workflow import ResearchWorkflow, WorkflowConfig

router = APIRouter(prefix="/v1/research", tags=["research"])


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20_000)


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    sources: list[SourceInput] = Field(min_length=1, max_length=20)
    max_evidence: int = Field(default=6, ge=1, le=10)


@dataclass(frozen=True)
class _OfflinePlanner:
    async def plan(self, question: str, max_queries: int) -> tuple[Plan, Usage]:
        return Plan(question=question, queries=(question,)[:max_queries]), Usage()


@dataclass(frozen=True)
class _RequestSearch:
    sources: tuple[SourceInput, ...]

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url=str(source.url),
                title=source.title,
                snippet=source.content[:500],
                content=source.content,
            )
            for source in self.sources[:limit]
        ]


@dataclass(frozen=True)
class _ExtractiveSynthesizer:
    async def synthesize(self, question: str, evidence: tuple[Evidence, ...]) -> Draft:
        del question
        claims = []
        for item in evidence:
            sentence = re.split(r"(?<=[.!?])\s+", item.quote.strip(), maxsplit=1)[0]
            claims.append(Claim(text=sentence, evidence_ids=(item.id,)))
        return Draft(claims=tuple(claims), usage=Usage())


@router.post("")
async def research(request: ResearchRequest) -> dict:
    """Run bounded, deterministic research over caller-supplied sources.

    This endpoint performs no network access and needs no credentials. Production
    search and LLM adapters can implement the same typed ports.
    """
    workflow = ResearchWorkflow(
        planner=_OfflinePlanner(),
        search=_RequestSearch(tuple(request.sources)),
        synthesizer=_ExtractiveSynthesizer(),
        config=WorkflowConfig(
            max_queries=1,
            results_per_query=min(len(request.sources), 20),
            max_tool_calls=1,
            max_concurrency=1,
            max_evidence=request.max_evidence,
        ),
    )
    return (await workflow.run(request.question.strip())).to_dict()
