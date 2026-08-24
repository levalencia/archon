from __future__ import annotations

from typing import Protocol

from .models import Draft, Evidence, Plan, SearchResult, Usage


class Planner(Protocol):
    async def plan(self, question: str, max_queries: int) -> tuple[Plan, Usage]: ...


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...


class Synthesizer(Protocol):
    async def synthesize(self, question: str, evidence: tuple[Evidence, ...]) -> Draft: ...
