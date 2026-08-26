"""Tests for deterministic evaluation of persisted run trajectories."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.eval.persistence import EvaluationRepository
from app.eval.service import (
    EvaluationItem,
    EvaluationRequestError,
    EvaluationService,
    SourceRunNotCompletedError,
    SourceRunNotFoundError,
)
from app.security.persistence_redactor import PersistenceRedactor
from app.services.conversations import ConversationRepository
from app.services.db_store import EvalCaseResultRow, EvalRunRow


async def _append(
    repository: ConversationRepository,
    run_id: str,
    owner: str,
    kind: str,
    payload: dict[str, Any],
    *,
    project: str = "project",
) -> None:
    await repository.append_runtime_event(
        run_id=run_id,
        user_id=owner,
        project_id=project,
        conversation_id=f"conversation-{owner}",
        correlation_id=f"correlation-{run_id}",
        provider="recorded-provider",
        model="recorded-model",
        kind=kind,
        iteration=1,
        data=payload,
        input_tokens=3,
        output_tokens=5,
        total_tokens=8,
    )


async def _completed_run(
    repository: ConversationRepository,
    run_id: str,
    owner: str,
    *,
    answer: str,
    supported: int,
    unsupported: int,
    citations: list[str],
    project: str = "project",
) -> None:
    await _append(
        repository,
        run_id,
        owner,
        "evidence_retrieved",
        {"evidence_count": len(citations), "evidence_ids": citations},
        project=project,
    )
    await _append(
        repository,
        run_id,
        owner,
        "claim_verified",
        {
            "supported_count": supported,
            "unsupported_count": unsupported,
            "cited_evidence_ids": citations,
        },
        project=project,
    )
    await _append(
        repository,
        run_id,
        owner,
        "grounded_answer",
        {
            "answer_hash": "a" * 64,
            "citation_ids": citations,
            "supported_count": supported,
            "unsupported_count": unsupported,
        },
        project=project,
    )
    await _append(
        repository,
        run_id,
        owner,
        "run_stopped",
        {"reason": "completed", "error": False},
        project=project,
    )
    await repository.runs.finalize_metadata(
        owner, run_id, answer=answer, cost_usd=0.02, latency_ms=12.5
    )


async def _setup(
    tmp_path: Path,
) -> tuple[ConversationRepository, EvaluationRepository, EvaluationService]:
    repository = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'recorded-evals.db'}", PersistenceRedactor()
    )
    await repository.initialize()
    evaluations = EvaluationRepository(repository.session_factory)
    return repository, evaluations, EvaluationService(repository.runs, evaluations)


def _items(grounded_run: str, abstention_run: str) -> tuple[EvaluationItem, ...]:
    return (
        EvaluationItem(grounded_run, "grounded-citation"),
        EvaluationItem(abstention_run, "safe-abstention"),
    )


@pytest.mark.asyncio
async def test_scores_good_and_bad_recorded_runs_by_explicit_case_key(tmp_path: Path) -> None:
    repository, _, service = await _setup(tmp_path)
    # Force the meaningful events onto a second ledger page.
    for _ in range(101):
        await _append(repository, "grounded-good", "alice", "iteration_started", {})
    await _completed_run(
        repository,
        "grounded-good",
        "alice",
        answer="A verified fact [E1]",
        supported=1,
        unsupported=0,
        citations=["E1"],
    )
    await _completed_run(
        repository,
        "abstain-good",
        "alice",
        answer="I could not find relevant information to answer your question.",
        supported=0,
        unsupported=0,
        citations=[],
    )

    result = await service.evaluate(
        "alice",
        project_id="project",
        dataset_id="grounded-v1",
        threshold=1.0,
        # Deliberately reversed: association must use case_key, not request position.
        items=tuple(reversed(_items("grounded-good", "abstain-good"))),
    )

    assert result.status == "completed" and result.passed is True
    assert [case.case_key for case in result.cases] == [
        "grounded-citation",
        "safe-abstention",
    ]
    assert [case.source_run_id for case in result.cases] == ["grounded-good", "abstain-good"]
    assert all(case.score == 1 for case in result.cases)
    grounded_metrics = result.cases[0].metrics
    assert grounded_metrics["evidence_count"] == 1
    assert grounded_metrics["supported_count"] == 1
    assert grounded_metrics["unsupported_count"] == 0
    assert grounded_metrics["citation_count"] == 1
    assert grounded_metrics["latency_ms"] == 12.5
    assert grounded_metrics["cost_usd"] == 0.02
    assert result.aggregate_metrics["total_tokens"] == 16

    await _completed_run(
        repository,
        "grounded-bad",
        "alice",
        answer="unsupported answer",
        supported=1,
        unsupported=1,
        citations=[],
    )
    bad = await service.evaluate(
        "alice",
        project_id="project",
        dataset_id="grounded-v1",
        threshold=0.8,
        items=_items("grounded-bad", "abstain-good"),
    )
    assert bad.status == "completed" and bad.passed is False
    assert bad.cases[0].passed is False
    assert bad.cases[0].score == 0
    assert bad.cases[0].metrics["support_rate"] == 0.5
    assert bad.cases[0].metrics["unsupported_rate"] == 0.5
    await repository.close()


@pytest.mark.asyncio
async def test_rejects_invalid_mapping_foreign_project_owner_and_nonterminal_runs(
    tmp_path: Path,
) -> None:
    repository, _, service = await _setup(tmp_path)
    await _completed_run(
        repository,
        "foreign-owner",
        "mallory",
        answer="fact [E1]",
        supported=1,
        unsupported=0,
        citations=["E1"],
    )
    await _completed_run(
        repository,
        "foreign-project",
        "alice",
        answer="fact [E1]",
        supported=1,
        unsupported=0,
        citations=["E1"],
        project="other-project",
    )
    await _append(repository, "active", "alice", "evidence_retrieved", {"evidence_count": 0})

    with pytest.raises(EvaluationRequestError, match="every dataset case"):
        await service.evaluate(
            "alice",
            project_id="project",
            dataset_id="grounded-v1",
            threshold=0.5,
            items=(EvaluationItem("active", "safe-abstention"),),
        )
    for run_id in ("foreign-owner", "foreign-project", "missing"):
        with pytest.raises(SourceRunNotFoundError):
            await service.evaluate(
                "alice",
                project_id="project",
                dataset_id="grounded-v1",
                threshold=0.5,
                items=_items(run_id, "active"),
            )
    with pytest.raises(SourceRunNotCompletedError):
        await service.evaluate(
            "alice",
            project_id="project",
            dataset_id="grounded-v1",
            threshold=0.5,
            items=_items("active", "missing"),
        )
    await repository.close()


@pytest.mark.asyncio
async def test_results_survive_restart_compare_without_runtime_dependencies_and_store_no_raw_data(
    tmp_path: Path,
) -> None:
    repository, _, service = await _setup(tmp_path)
    assert tuple(inspect.signature(EvaluationService).parameters) == (
        "runs",
        "evaluations",
        "dataset_paths",
    )
    await _completed_run(
        repository,
        "grounded",
        "alice",
        answer="private grounded answer [E1]",
        supported=1,
        unsupported=0,
        citations=["E1"],
    )
    await _completed_run(
        repository,
        "abstain",
        "alice",
        answer="I could not find relevant information to answer your question.",
        supported=0,
        unsupported=0,
        citations=[],
    )
    first = await service.evaluate(
        "alice",
        project_id="project",
        dataset_id="grounded-v1",
        threshold=1.0,
        items=_items("grounded", "abstain"),
    )
    second = await service.evaluate(
        "alice",
        project_id="project",
        dataset_id="grounded-v1",
        threshold=0.5,
        items=_items("grounded", "abstain"),
    )
    assert {item.id for item in await service.list("alice", project_id="project")} == {
        first.id,
        second.id,
    }
    comparison = await service.compare("alice", first.id, second.id)
    assert comparison is not None
    assert comparison["a_id"] == first.id
    assert comparison["b_id"] == second.id
    assert await service.get("mallory", first.id) is None
    assert await service.compare("mallory", first.id, second.id) is None

    async with repository.session_factory() as session:
        eval_runs = list((await session.scalars(select(EvalRunRow))).all())
        cases = list((await session.scalars(select(EvalCaseResultRow))).all())
    raw_eval_json = json.dumps(
        [row.source_run_ids_json for row in eval_runs]
        + [row.aggregate_metrics_json for row in eval_runs]
        + [row.metrics_json for row in cases]
        + [row.checks_json for row in cases]
    )
    assert "private grounded answer" not in raw_eval_json
    assert "grounded_answer" not in raw_eval_json
    assert "citation_ids" not in raw_eval_json
    await repository.close()

    restarted = ConversationRepository(
        f"sqlite+aiosqlite:///{tmp_path / 'recorded-evals.db'}", PersistenceRedactor()
    )
    await restarted.initialize()
    restarted_service = EvaluationService(
        restarted.runs, EvaluationRepository(restarted.session_factory)
    )
    persisted = await restarted_service.get("alice", first.id)
    assert persisted is not None and len(persisted.cases) == 2
    assert persisted.aggregate_metrics == first.aggregate_metrics
    await restarted.close()


@pytest.mark.asyncio
async def test_persistence_failure_finalizes_evaluation_as_safe_failed_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, evaluations, service = await _setup(tmp_path)
    await _completed_run(
        repository,
        "grounded",
        "alice",
        answer="fact [E1]",
        supported=1,
        unsupported=0,
        citations=["E1"],
    )
    await _completed_run(
        repository,
        "abstain",
        "alice",
        answer="I could not find relevant information to answer your question.",
        supported=0,
        unsupported=0,
        citations=[],
    )

    async def reject_case(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected append failure")

    monkeypatch.setattr(evaluations, "append_case", reject_case)
    with pytest.raises(RuntimeError, match="injected append failure"):
        await service.evaluate(
            "alice",
            project_id="project",
            dataset_id="grounded-v1",
            threshold=1.0,
            items=_items("grounded", "abstain"),
        )
    failed = await evaluations.list("alice")
    assert len(failed) == 1
    stored = await evaluations.get("alice", failed[0].id)
    assert stored is not None
    assert stored.status == "failed" and stored.passed is None
    assert stored.aggregate_metrics == {"case_count": 0}
    assert stored.cases == ()
    await repository.close()
