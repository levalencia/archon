"""Contracts for the versioned learning-tutor evaluation dataset."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.learning_tutor.evaluation import load_tutor_eval_dataset, score_tutor_response

_DATASET = Path(__file__).parents[2] / "evals/learning_tutor/concepts-v1.json"


def test_learning_tutor_eval_dataset_has_balanced_unique_cases() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)

    assert len(dataset.cases) == 90
    assert Counter(case.difficulty for case in dataset.cases) == {
        "basic": 30,
        "medium": 30,
        "hard": 30,
    }
    assert len({case.id for case in dataset.cases}) == 90


def test_basic_dataset_covers_beginner_vocabulary_regressions() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)
    basic_questions = " ".join(
        case.question.casefold() for case in dataset.cases if case.difficulty == "basic"
    )

    for required in (
        "object-oriented programming",
        "dependency injection",
        "factory",
        "preflight",
        "observability",
        "policy in cogentrex",
    ):
        assert required in basic_questions


def test_preflight_case_preserves_the_reported_video_context() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)
    case = next(case for case in dataset.cases if "preflight check" in case.question.casefold())

    assert case.context == {
        "view": "present",
        "artifact_id": "code-first-video-01",
        "playback_seconds": 235.708,
    }
    assert case.rubric.definition_first is True
    assert case.rubric.minimum_citations == 1
    assert "what is what is preflight?" in case.variants


def test_basic_dataset_includes_colloquial_beginner_variants() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)
    variants = {variant.casefold() for case in dataset.cases for variant in case.variants}

    assert {
        "what's factory?",
        "what's di?",
        "what's observability?",
        "what's a policy in cogentrex?",
        "what is oop?",
    } <= variants


def test_deterministic_score_rejects_fallback_and_missing_required_web() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)
    case = next(case for case in dataset.cases if case.web_policy == "required")

    fallback = score_tutor_response(
        case,
        {
            "answer_markdown": "I could not verify an answer from the indexed learning sources.",
            "grounded": False,
            "citations": [],
        },
    )
    local_only = score_tutor_response(
        case,
        {
            "answer_markdown": "A concise grounded explanation.",
            "grounded": True,
            "citations": [{"kind": "documentation"}],
        },
    )

    assert fallback.deterministic_pass is False
    assert fallback.non_fallback is False
    assert local_only.web_policy_met is False


def test_deterministic_score_accepts_grounded_required_web_response() -> None:
    dataset = load_tutor_eval_dataset(_DATASET)
    case = next(case for case in dataset.cases if case.web_policy == "required")

    score = score_tutor_response(
        case,
        {
            "answer_markdown": "A concise grounded explanation with a Cogentrex application.",
            "grounded": True,
            "citations": [{"kind": "web"}],
        },
    )

    assert score.deterministic_pass is True
    assert score.manual_checks
