"""Authenticated, rate-limited APIs for evaluations, drift, and reviewed candidates."""
# ruff: noqa: B008 -- FastAPI dependencies are intentionally declared as defaults.

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.eval.candidates import CandidateConflictError, CandidateType, OptimizationCandidateService
from app.eval.drift import DriftService, DriftThresholds
from app.eval.service import (
    EvaluationItem,
    EvaluationRequestError,
    EvaluationService,
    SourceRunNotCompletedError,
    SourceRunNotFoundError,
)
from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit

router = APIRouter(prefix="/api/evals", tags=["evaluations"])


class RecordedRunItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=255)
    case_key: str = Field(min_length=1, max_length=255)


class RecordedEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: Literal["grounded-v1"]
    path: Literal["grounded-v1"] | None = None
    threshold: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)
    project_id: str = Field(min_length=1, max_length=255)
    items: Annotated[list[RecordedRunItem], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def dataset_path_matches(self) -> RecordedEvaluationRequest:
        if self.path is not None and self.path != self.dataset_id:
            raise ValueError("dataset path must match the allowlisted dataset")
        return self


class DriftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=255)
    baseline_eval_id: str = Field(min_length=1, max_length=255)
    candidate_eval_id: str = Field(min_length=1, max_length=255)
    minimum_sample_size: int = Field(default=20, ge=2, le=10_000)


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=255)
    candidate_type: Literal["prompt", "policy", "retrieval", "config"]
    change_summary: str = Field(min_length=1, max_length=1000)
    proposal_metadata: dict[str, Any] = Field(default_factory=dict)
    rollback_plan: str = Field(min_length=1, max_length=2000)
    target_revision: str = Field(min_length=1, max_length=255)
    baseline_eval_id: str = Field(min_length=1, max_length=255)
    candidate_eval_id: str = Field(min_length=1, max_length=255)
    drift_report_id: str | None = Field(default=None, max_length=255)


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=255)
    expected_version: int = Field(ge=1)


class ApproveCandidateRequest(VersionRequest):
    approval_id: str = Field(min_length=1, max_length=255)


class ReasonedVersionRequest(VersionRequest):
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


def _service(request: Request) -> EvaluationService:
    return cast(EvaluationService, request.app.state.evaluation_service)


def _drift(request: Request) -> DriftService:
    return cast(DriftService, request.app.state.drift_service)


def _candidates(request: Request) -> OptimizationCandidateService:
    return cast(OptimizationCandidateService, request.app.state.optimization_candidates)


async def _read_limit(request: Request, user: dict[str, Any]) -> None:
    await enforce_rate_limit(request, user, "eval_read")


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_recorded_evaluation(
    body: RecordedEvaluationRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await enforce_rate_limit(request, user, "eval_write")
    try:
        result = await _service(request).evaluate(
            user["user_id"],
            project_id=body.project_id,
            dataset_id=body.dataset_id,
            threshold=body.threshold,
            items=tuple(EvaluationItem(item.run_id, item.case_key) for item in body.items),
        )
    except SourceRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Source run not found") from exc
    except SourceRunNotCompletedError as exc:
        raise HTTPException(status_code=409, detail="Source run must be completed") from exc
    except EvaluationRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(result)


@router.get("")
async def list_recorded_evaluations(
    request: Request,
    project_id: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    results = await _service(request).list(
        user["user_id"], project_id=project_id, limit=limit, offset=offset
    )
    return {"items": [asdict(item) for item in results], "limit": limit, "offset": offset}


@router.get("/compare")
async def compare_recorded_evaluations(
    request: Request,
    a: str = Query(min_length=1, max_length=255),
    b: str = Query(min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    left, right = (
        await _service(request).get(user["user_id"], a),
        await _service(request).get(user["user_id"], b),
    )
    comparison = await _service(request).compare(user["user_id"], a, b)
    if left is None or right is None or comparison is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return {
        "a": asdict(left),
        "b": asdict(right),
        "metric_delta_b_minus_a": comparison["metric_delta_b_minus_a"],
    }


@router.post("/drift", status_code=status.HTTP_201_CREATED)
async def create_drift_report(
    body: DriftRequest, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:  # noqa: B008
    await enforce_rate_limit(request, user, "eval_write")
    try:
        report = await _drift(request).compare(
            user["user_id"],
            project_id=body.project_id,
            baseline_eval_id=body.baseline_eval_id,
            candidate_eval_id=body.candidate_eval_id,
            thresholds=DriftThresholds(minimum_sample_size=body.minimum_sample_size),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Evaluation cohort not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return asdict(report)


@router.get("/drift/{report_id}")
async def get_drift_report(
    report_id: str,
    request: Request,
    project_id: str = Query(min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    report = await _drift(request).get(user["user_id"], report_id, project_id=project_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Drift report not found")
    return asdict(report)


@router.post("/candidates", status_code=status.HTTP_201_CREATED)
async def create_candidate(
    body: CandidateRequest, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:  # noqa: B008
    await enforce_rate_limit(request, user, "eval_write")
    try:
        item = await _candidates(request).create(
            user["user_id"],
            project_id=body.project_id,
            candidate_type=CandidateType(body.candidate_type),
            change_summary=body.change_summary,
            proposal_metadata=body.proposal_metadata,
            rollback_plan=body.rollback_plan,
            target_revision=body.target_revision,
            baseline_eval_id=body.baseline_eval_id,
            candidate_eval_id=body.candidate_eval_id,
            drift_report_id=body.drift_report_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Evaluation evidence not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(item)


@router.get("/candidates")
async def list_candidates(
    request: Request,
    project_id: str = Query(min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    items = await _candidates(request).list(user["user_id"], project_id=project_id, limit=limit)
    return {"items": [asdict(item) for item in items]}


@router.post("/candidates/{candidate_id}/approval", status_code=status.HTTP_201_CREATED)
async def request_candidate_approval(
    candidate_id: str,
    body: VersionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await enforce_rate_limit(request, user, "approval")
    try:
        approval_id, tool_call_id = await _candidates(request).request_approval(
            user["user_id"],
            candidate_id,
            project_id=body.project_id,
            expected_version=body.expected_version,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc
    except CandidateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "approval_id": approval_id,
        "tool_call_id": tool_call_id,
        "run_id": candidate_id,
        "purpose": "optimization_candidate_promotion",
    }


async def _candidate_transition(
    operation: str, candidate_id: str, body: VersionRequest, request: Request, user: dict[str, Any]
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "eval_write")
    service = _candidates(request)
    try:
        if operation == "approve":
            assert isinstance(body, ApproveCandidateRequest)
            item = await service.approve(
                user["user_id"],
                candidate_id,
                project_id=body.project_id,
                expected_version=body.expected_version,
                approval_id=body.approval_id,
            )
        elif operation == "promote":
            item = await service.promote(
                user["user_id"],
                candidate_id,
                project_id=body.project_id,
                expected_version=body.expected_version,
            )
        elif operation == "reject":
            assert isinstance(body, ReasonedVersionRequest)
            item = await service.reject(
                user["user_id"],
                candidate_id,
                project_id=body.project_id,
                expected_version=body.expected_version,
                reason_code=body.reason_code,
            )
        else:
            assert isinstance(body, ReasonedVersionRequest)
            item = await service.rollback(
                user["user_id"],
                candidate_id,
                project_id=body.project_id,
                expected_version=body.expected_version,
                reason_code=body.reason_code,
            )
    except CandidateConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return asdict(item)


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(
    candidate_id: str,
    body: ApproveCandidateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    return await _candidate_transition("approve", candidate_id, body, request, user)


@router.post("/candidates/{candidate_id}/promote")
async def promote_candidate(
    candidate_id: str,
    body: VersionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    return await _candidate_transition("promote", candidate_id, body, request, user)


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    body: ReasonedVersionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    return await _candidate_transition("reject", candidate_id, body, request, user)


@router.post("/candidates/{candidate_id}/rollback")
async def rollback_candidate(
    candidate_id: str,
    body: ReasonedVersionRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    return await _candidate_transition("rollback", candidate_id, body, request, user)


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    request: Request,
    project_id: str = Query(min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    item = await _candidates(request).get(user["user_id"], candidate_id, project_id=project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return asdict(item)


@router.get("/{evaluation_id}")
async def get_recorded_evaluation(
    evaluation_id: str, request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:  # noqa: B008
    await _read_limit(request, user)
    result = await _service(request).get(user["user_id"], evaluation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return asdict(result)
