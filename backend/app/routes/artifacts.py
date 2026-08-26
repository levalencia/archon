"""Authenticated, owner-scoped artifact API routes."""

from __future__ import annotations

import html
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.security.auth import get_current_user
from app.services.artifacts import Artifact, ArtifactStore

router = APIRouter(
    prefix="/api/artifacts", tags=["artifacts"], dependencies=[Depends(get_current_user)]
)
_RENDER_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def get_artifact_store(request: Request) -> ArtifactStore:
    """Resolve the application-scoped store."""
    return cast(ArtifactStore, request.app.state.artifacts)


class ArtifactUpdate(BaseModel):
    content: str = Field(..., min_length=1)
    title: str | None = None


async def _owned_artifact(store: ArtifactStore, artifact_id: str, user_id: str) -> Artifact:
    artifact = await store.get(artifact_id)
    if not artifact or artifact.user_id != user_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


def _safe_response(body: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        body,
        status_code=status_code,
        headers={
            "Content-Security-Policy": _RENDER_CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _render_text(content: str, *, title: str = "Artifact") -> str:
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>body{margin:16px;background:#0d1117;color:#e6edf3;font-family:monospace;"
        "white-space:pre-wrap}pre{white-space:pre-wrap}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><pre>{html.escape(content)}</pre></body></html>"
    )


@router.get("")
async def list_artifacts(
    request: Request,
    conversation_id: str = "",
    user: dict = Depends(get_current_user),  # noqa: B008
) -> list[dict]:
    artifacts = await get_artifact_store(request).list_by_user(user["user_id"], conversation_id)
    return [artifact.to_summary() for artifact in artifacts]


@router.get("/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    artifact = await get_artifact_store(request).get(artifact_id)
    if not artifact or artifact.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact.to_dict()


@router.get("/{artifact_id}/render")
async def render_artifact(
    artifact_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> HTMLResponse:
    """Render inert escaped content in a CSP sandbox; never execute artifact markup."""
    artifact = await _owned_artifact(get_artifact_store(request), artifact_id, user["user_id"])
    return _safe_response(_render_text(artifact.content, title=artifact.title))


@router.put("/{artifact_id}")
async def update_artifact(
    artifact_id: str,
    body: ArtifactUpdate,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    store = get_artifact_store(request)
    current = await store.get(artifact_id)
    if not current or current.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = await store.update_content(artifact_id, body.content, body.title)
    assert artifact is not None
    return artifact.to_dict()


@router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(
    artifact_id: str,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> None:
    store = get_artifact_store(request)
    await _owned_artifact(store, artifact_id, user["user_id"])
    await store.delete(artifact_id)
