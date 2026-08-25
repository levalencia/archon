"""Compliance policy endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.security.compliance import default_checker

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/compliance/policies")
async def get_compliance_policies() -> dict:
    """Return active compliance policies."""
    return {"policies": default_checker.get_policies()}
