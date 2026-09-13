"""Versioned evaluation dataset and deterministic tutor-response checks."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_FALLBACK = "I could not verify an answer from the indexed learning sources."


class TutorEvalRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_first: bool
    cogentrex_application: bool
    minimum_citations: int = Field(ge=0, le=20)


class TutorEvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    difficulty: Literal["basic", "medium", "hard"]
    question: str = Field(min_length=3, max_length=2_000)
    variants: list[str] = Field(default_factory=list, max_length=5)
    expected_concepts: list[str] = Field(min_length=1)
    web_policy: Literal["required", "allowed", "forbidden"]
    expected_source_areas: list[str] = Field(min_length=1)
    forbidden_misconceptions: list[str] = Field(min_length=1)
    rubric: TutorEvalRubric
    context: dict[str, Any]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if re.fullmatch(r"(?:BASIC|MEDIUM|HARD)-\d{3}", value) is None:
            raise ValueError("invalid evaluation case ID")
        return value


class TutorEvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal["cogentrex.learning-tutor-eval"] = Field(alias="schema")
    version: int = Field(ge=1)
    cases: list[TutorEvalCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def validate_unique_ids(cls, cases: list[TutorEvalCase]) -> list[TutorEvalCase]:
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case IDs must be unique")
        return cases


class TutorEvalScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    non_fallback: bool
    grounded: bool
    citation_count: int
    citation_requirement_met: bool
    web_policy_met: bool
    forbidden_phrase_absent: bool
    deterministic_pass: bool
    manual_checks: list[str]
    retrieval_recall: dict[str, float] | None = None


def load_tutor_eval_dataset(path: str | Path) -> TutorEvalDataset:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return TutorEvalDataset.model_validate(payload)


def score_tutor_response(case: TutorEvalCase, response: dict[str, Any]) -> TutorEvalScore:
    answer = str(response.get("answer_markdown") or "").strip()
    raw_citations = response.get("citations")
    citations: list[dict[str, Any]] = (
        [item for item in raw_citations if isinstance(item, dict)]
        if isinstance(raw_citations, list)
        else []
    )
    web_count = sum(
        1 for citation in citations if isinstance(citation, dict) and citation.get("kind") == "web"
    )
    citation_requirement_met = len(citations) >= case.rubric.minimum_citations
    web_policy_met = (
        web_count > 0
        if case.web_policy == "required"
        else web_count == 0
        if case.web_policy == "forbidden"
        else True
    )
    answer_folded = answer.casefold()
    forbidden_phrase_absent = not any(
        misconception.casefold() in answer_folded for misconception in case.forbidden_misconceptions
    )
    non_fallback = bool(answer) and answer != _FALLBACK
    grounded = response.get("grounded") is True
    deterministic_pass = all(
        (non_fallback, grounded, citation_requirement_met, web_policy_met, forbidden_phrase_absent)
    )
    manual_checks: list[str] = []
    if case.rubric.definition_first:
        manual_checks.append("The answer begins with a plain-language definition.")
    if case.rubric.cogentrex_application:
        manual_checks.append(
            "The answer distinguishes general knowledge from Cogentrex-specific evidence."
        )
    manual_checks.append(
        "The answer covers the expected concepts without introducing unsupported claims."
    )
    # Compute retrieval recall when diagnostics are provided
    retrieval_recall: dict[str, float] | None = None
    diagnostics = response.get("retrieval_diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        retrieval_recall = compute_retrieval_recall(case, diagnostics)
    elif citations:
        # Fall back to citation paths if no explicit diagnostics
        diag_from_citations = [c for c in citations if isinstance(c, dict) and c.get("source_path")]
        if diag_from_citations:
            retrieval_recall = compute_retrieval_recall(case, diag_from_citations)
    return TutorEvalScore(
        case_id=case.id,
        non_fallback=non_fallback,
        grounded=grounded,
        citation_count=len(citations),
        citation_requirement_met=citation_requirement_met,
        web_policy_met=web_policy_met,
        forbidden_phrase_absent=forbidden_phrase_absent,
        deterministic_pass=deterministic_pass,
        manual_checks=manual_checks,
        retrieval_recall=retrieval_recall,
    )


def compute_retrieval_recall(
    case: TutorEvalCase,
    retrieved: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute recall@1, recall@3, recall@10 against expected_source_areas.

    Each retrieved item should have a 'source_path' key. Matching is prefix-based:
    a retrieved path 'docs/oop.md#section' matches expected 'docs/oop.md'.
    """
    expected = set(case.expected_source_areas)
    if not expected:
        return {"recall@1": 0.0, "recall@3": 0.0, "recall@10": 0.0}

    def _found_at_k(k: int) -> float:
        top_paths = [str(item.get("source_path") or "") for item in retrieved[:k]]
        found = sum(
            1
            for exp in expected
            if any(p.startswith(exp) or p == exp for p in top_paths)
        )
        return found / len(expected)

    return {
        "recall@1": round(_found_at_k(1), 4),
        "recall@3": round(_found_at_k(3), 4),
        "recall@10": round(_found_at_k(10), 4),
    }
