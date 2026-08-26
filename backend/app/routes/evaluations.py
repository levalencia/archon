"""Authenticated APIs for deterministic evaluations of recorded runs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def _service(request: Request) -> EvaluationService:
    return cast(EvaluationService, request.app.state.evaluation_service)


async def _rate_limit(request: Request, user: dict[str, Any]) -> None:
    await enforce_rate_limit(request, user, "eval_read")


@router.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_recorded_evaluation(
    body: RecordedEvaluationRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
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
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    results = await _service(request).list(
        user["user_id"], project_id=project_id, limit=limit, offset=offset
    )
    return {"items": [asdict(item) for item in results], "limit": limit, "offset": offset}


@router.get("/compare")
async def compare_recorded_evaluations(
    request: Request,
    a: str = Query(min_length=1, max_length=255),
    b: str = Query(min_length=1, max_length=255),
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    service = _service(request)
    left = await service.get(user["user_id"], a)
    right = await service.get(user["user_id"], b)
    comparison = await service.compare(user["user_id"], a, b)
    if left is None or right is None or comparison is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return {
        "a": asdict(left),
        "b": asdict(right),
        "metric_delta_b_minus_a": comparison["metric_delta_b_minus_a"],
    }


@router.get("/{evaluation_id}")
async def get_recorded_evaluation(
    evaluation_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await _rate_limit(request, user)
    result = await _service(request).get(user["user_id"], evaluation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return asdict(result)
