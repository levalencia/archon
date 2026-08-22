"""Evaluation upgrades: faithfulness, relevance, batch runner, CI gate.

Adds production evaluators beyond the basic contains/not_contains checks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class EvalScore:
    name: str
    score: float  # 0.0 to 1.0
    reason: str = ""


def evaluate_faithfulness(answer: str, context: str) -> EvalScore:
    """Check if the answer is grounded in the provided context.

    Heuristic: what % of answer sentences can be found (paraphrased) in context.
    For production: use LLM-as-judge.
    """
    if not context or not answer:
        return EvalScore("faithfulness", 0.0, "Empty context or answer")

    answer_sentences = re.split(r"[.!?]+", answer)
    answer_sentences = [s.strip() for s in answer_sentences if len(s.strip()) > 10]

    if not answer_sentences:
        return EvalScore("faithfulness", 1.0, "No substantive claims")

    context_lower = context.lower()
    grounded = 0
    for sentence in answer_sentences:
        # Check if key words from sentence appear in context
        words = set(sentence.lower().split())
        important_words = {w for w in words if len(w) > 3}
        if not important_words:
            grounded += 1
            continue
        overlap = sum(1 for w in important_words if w in context_lower)
        if overlap / len(important_words) > 0.3:
            grounded += 1

    score = grounded / len(answer_sentences)
    return EvalScore(
        "faithfulness",
        round(score, 2),
        f"{grounded}/{len(answer_sentences)} sentences grounded",
    )


def evaluate_relevance(answer: str, question: str) -> EvalScore:
    """Check if the answer is relevant to the question.

    Heuristic: keyword overlap between question and answer.
    """
    if not answer or not question:
        return EvalScore("relevance", 0.0, "Empty answer or question")

    q_words = set(question.lower().split())
    a_words = set(answer.lower().split())
    important_q = {w for w in q_words if len(w) > 3}

    if not important_q:
        return EvalScore("relevance", 1.0, "No important question words")

    overlap = important_q & a_words
    score = len(overlap) / len(important_q)

    return EvalScore(
        "relevance",
        round(min(score * 1.5, 1.0), 2),  # Boost since partial overlap is OK
        f"{len(overlap)}/{len(important_q)} key terms addressed",
    )


def evaluate_safety(answer: str) -> EvalScore:
    """Check if the answer contains unsafe content or PII."""
    from app.security.pii_detector import PIIDetector

    detector = PIIDetector()
    entities = detector.detect(answer)

    if not entities:
        return EvalScore("safety", 1.0, "No PII detected")

    high_risk = [e for e in entities if e.risk_level == "high"]
    if high_risk:
        return EvalScore("safety", 0.0, f"{len(high_risk)} high-risk PII entities")

    return EvalScore(
        "safety",
        0.5,
        f"{len(entities)} low-risk PII entities",
    )


def evaluate_cost(tokens_used: int, max_expected: int = 2000) -> EvalScore:
    """Check token efficiency."""
    if tokens_used <= max_expected:
        score = 1.0
    else:
        score = max(0.0, 1.0 - (tokens_used - max_expected) / max_expected)

    return EvalScore(
        "cost",
        round(score, 2),
        f"{tokens_used} tokens (budget: {max_expected})",
    )


@dataclass
class BatchEvalResult:
    """Result of a batch evaluation run."""

    total_cases: int
    avg_faithfulness: float
    avg_relevance: float
    avg_safety: float
    avg_cost: float
    overall_score: float
    passed_quality_gate: bool
    details: list[dict]


async def run_batch_eval(
    agent_fn: object,
    cases: list[dict],
    quality_threshold: float = 0.7,
) -> BatchEvalResult:
    """Run batch evaluation on multiple test cases.

    Each case: {question, context (optional), max_tokens (optional)}
    """
    results = []
    scores = {"faithfulness": [], "relevance": [], "safety": [], "cost": []}

    for case in cases:
        question = case["question"]
        context = case.get("context", "")
        max_tokens = case.get("max_tokens", 2000)

        try:
            if callable(agent_fn):
                response = await agent_fn(question)
            else:
                response = {"response": str(agent_fn), "tokens_used": 0}

            answer = (
                response.get("response", str(response))
                if isinstance(response, dict)
                else str(response)
            )
            tokens = (
                response.get("tokens_used", len(answer) // 4)
                if isinstance(response, dict)
                else len(answer) // 4
            )

            faith = evaluate_faithfulness(answer, context)
            relevance = evaluate_relevance(answer, question)
            safety = evaluate_safety(answer)
            cost = evaluate_cost(tokens, max_tokens)

            scores["faithfulness"].append(faith.score)
            scores["relevance"].append(relevance.score)
            scores["safety"].append(safety.score)
            scores["cost"].append(cost.score)

            results.append(
                {
                    "question": question,
                    "answer": answer[:200],
                    "faithfulness": faith.score,
                    "relevance": relevance.score,
                    "safety": safety.score,
                    "cost": cost.score,
                }
            )

        except Exception as e:
            results.append(
                {
                    "question": question,
                    "error": str(e),
                    "faithfulness": 0,
                    "relevance": 0,
                    "safety": 0,
                    "cost": 0,
                }
            )

    def avg(lst: list) -> float:
        return round(sum(lst) / max(len(lst), 1), 2)

    overall = avg([avg(scores[k]) for k in scores])

    return BatchEvalResult(
        total_cases=len(cases),
        avg_faithfulness=avg(scores["faithfulness"]),
        avg_relevance=avg(scores["relevance"]),
        avg_safety=avg(scores["safety"]),
        avg_cost=avg(scores["cost"]),
        overall_score=overall,
        passed_quality_gate=overall >= quality_threshold,
        details=results,
    )
