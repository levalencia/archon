"""Authenticated, non-public run share grant endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.security.auth import get_current_user
from app.security.dependencies import enforce_rate_limit
from app.services.run_exports import ExportIntegrityError, RunExportService

router = APIRouter(prefix="/api/shares", tags=["run-shares"])


class RedeemRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    purpose: str = Field(min_length=1, max_length=120)


def _service(request: Request) -> RunExportService:
    return request.app.state.run_exports


@router.post("/redeem")
async def redeem_share(
    body: RedeemRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    await enforce_rate_limit(request, user, "share_redeem")
    try:
        bundle = await _service(request).redeem(user["user_id"], body.token, body.purpose)
    except ExportIntegrityError as exc:
        raise HTTPException(status_code=409, detail="Export integrity verification failed") from exc
    if bundle is None:
        # Do not distinguish bad, expired, revoked, wrong-purpose, or wrong-recipient grants.
        raise HTTPException(status_code=404, detail="Share grant not found")
    return bundle


@router.delete("/{grant_id}", status_code=204)
async def revoke_share(
    grant_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> None:
    await enforce_rate_limit(request, user, "share_revoke")
    if not await _service(request).revoke(user["user_id"], grant_id):
        raise HTTPException(status_code=404, detail="Share grant not found")
