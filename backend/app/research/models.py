from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Stage(StrEnum):
    PLAN = "plan"
    SEARCH = "search"
    EXTRACT = "extract"
    DEDUPLICATE = "deduplicate"
    RANK = "rank"
    SYNTHESIZE = "synthesize"
    VERIFY = "verify"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class Plan:
    question: str
    queries: tuple[str, ...]


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str
    content: str


@dataclass(frozen=True)
class Evidence:
    id: str
    url: str
    title: str
    quote: str
    score: float = 0.0


@dataclass(frozen=True)
class Claim:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Draft:
    claims: tuple[Claim, ...]
    usage: Usage = Usage()


@dataclass(frozen=True)
class Citation:
    evidence_id: str
    url: str
    title: str
    quote: str


@dataclass(frozen=True)
class StageTrace:
    stage: Stage
    duration_ms: float
    input_count: int
    output_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunMetadata:
    latency_ms: float
    tool_calls: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    max_concurrency: int
    peak_concurrency: int = 0
    search_tasks: int = 0


@dataclass(frozen=True)
class ResearchRun:
    question: str
    answer: str
    claims: tuple[Claim, ...]
    citations: tuple[Citation, ...]
    evidence: tuple[Evidence, ...]
    unsupported_claims: tuple[str, ...]
    trajectory: tuple[StageTrace, ...]
    metadata: RunMetadata

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
