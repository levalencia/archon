"""Tests for retrieval recall metrics in the evaluation framework."""

from __future__ import annotations

from app.learning_tutor.evaluation import (
    TutorEvalCase,
    TutorEvalRubric,
    TutorEvalScore,
    score_tutor_response,
    compute_retrieval_recall,
)


def _make_case(*, expected_source_areas: list[str] | None = None) -> TutorEvalCase:
    return TutorEvalCase(
        id="BASIC-001",
        difficulty="basic",
        question="What is OOP?",
        expected_concepts=["oop"],
        web_policy="allowed",
        expected_source_areas=expected_source_areas or ["docs/oop.md"],
        forbidden_misconceptions=["OOP means every function must be in a class"],
        rubric=TutorEvalRubric(
            definition_first=True, cogentrex_application=False, minimum_citations=1
        ),
        context={"view": "roadmap"},
    )


def test_compute_retrieval_recall_perfect_at_1() -> None:
    """When the expected source is the first citation, recall@1=1.0."""
    case = _make_case(expected_source_areas=["docs/oop.md"])
    citations = [
        {"source_path": "docs/oop.md", "kind": "documentation"},
        {"source_path": "docs/di.md", "kind": "documentation"},
    ]
    recall = compute_retrieval_recall(case, citations)
    assert recall["recall@1"] == 1.0
    assert recall["recall@3"] == 1.0
    assert recall["recall@10"] == 1.0


def test_compute_retrieval_recall_at_3_but_not_1() -> None:
    """Expected source at position 3: recall@1=0, recall@3=1.0."""
    case = _make_case(expected_source_areas=["docs/oop.md"])
    citations = [
        {"source_path": "docs/di.md", "kind": "documentation"},
        {"source_path": "docs/factory.md", "kind": "documentation"},
        {"source_path": "docs/oop.md", "kind": "documentation"},
    ]
    recall = compute_retrieval_recall(case, citations)
    assert recall["recall@1"] == 0.0
    assert recall["recall@3"] == 1.0
    assert recall["recall@10"] == 1.0


def test_compute_retrieval_recall_miss() -> None:
    """No expected source found at all."""
    case = _make_case(expected_source_areas=["docs/oop.md"])
    citations = [
        {"source_path": "docs/di.md", "kind": "documentation"},
    ]
    recall = compute_retrieval_recall(case, citations)
    assert recall["recall@1"] == 0.0
    assert recall["recall@3"] == 0.0
    assert recall["recall@10"] == 0.0


def test_compute_retrieval_recall_multiple_expected() -> None:
    """When multiple expected areas exist, recall is the fraction found."""
    case = _make_case(expected_source_areas=["docs/oop.md", "docs/di.md"])
    citations = [
        {"source_path": "docs/oop.md", "kind": "documentation"},
    ]
    recall = compute_retrieval_recall(case, citations)
    assert recall["recall@1"] == 0.5
    assert recall["recall@3"] == 0.5


def test_compute_retrieval_recall_partial_path_match() -> None:
    """Source path containing the expected area should count (prefix match)."""
    case = _make_case(expected_source_areas=["docs/oop.md"])
    citations = [
        {"source_path": "docs/oop.md#section", "kind": "documentation"},
    ]
    recall = compute_retrieval_recall(case, citations)
    assert recall["recall@1"] == 1.0


def test_compute_retrieval_recall_empty_citations() -> None:
    recall = compute_retrieval_recall(
        _make_case(), []
    )
    assert recall["recall@1"] == 0.0
    assert recall["recall@3"] == 0.0
    assert recall["recall@10"] == 0.0


def test_score_tutor_response_preserves_old_fields() -> None:
    """Ensure existing TutorEvalScore fields are untouched by new recall additions."""
    case = _make_case()
    response = {
        "answer_markdown": "OOP means classes and objects.",
        "grounded": True,
        "citations": [{"kind": "documentation"}],
    }
    score = score_tutor_response(case, response)
    assert isinstance(score, TutorEvalScore)
    assert score.non_fallback is True
    assert score.grounded is True
    assert score.citation_count == 1


def test_score_with_retrieval_diagnostics_includes_recall() -> None:
    """When response includes retrieval_diagnostics, score should carry recall metrics."""
    case = _make_case(expected_source_areas=["docs/oop.md"])
    response = {
        "answer_markdown": "OOP means classes and objects.",
        "grounded": True,
        "citations": [{"kind": "documentation", "source_path": "docs/oop.md"}],
        "retrieval_diagnostics": [
            {"source_path": "docs/oop.md", "score": 0.9, "score_components": {"dense": 0.8, "lexical": 0.9, "context": 1.0, "exact_symbol": 0.0, "final": 0.9}},
        ],
    }
    score = score_tutor_response(case, response)
    assert score.deterministic_pass is True
    # retrieval_recall should be present when diagnostics are provided
    assert hasattr(score, "retrieval_recall")
    assert score.retrieval_recall is not None
    assert score.retrieval_recall["recall@1"] == 1.0
