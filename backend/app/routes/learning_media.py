"""Authenticated learning catalog and signed media delivery."""

from __future__ import annotations

import json
import time
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_media.paths import media_type_for
from app.learning_media.signatures import sign_media_token, verify_media_token
from app.learning_media.streaming import file_chunks, parse_byte_range
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/learning-media", tags=["learning-media"])


def _catalog(request: Request) -> LearningMediaCatalog:
    return cast(LearningMediaCatalog, request.app.state.learning_media_catalog)


@router.get("/catalog")
async def get_catalog(
    request: Request,
    _user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Return public metadata for accepted learning artifacts."""
    return _catalog(request).public_catalog()


@router.get("/artifacts/{artifact_id}")
async def get_artifact(
    artifact_id: str,
    request: Request,
    _user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Return metadata for one accepted artifact without exposing its path."""
    try:
        artifact = _catalog(request).artifact(artifact_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Learning artifact not found") from error
    metadata = dict(artifact.metadata)
    metadata.pop("file", None)
    metadata.pop("content_file", None)
    content_path = artifact.content_path
    if content_path is None and artifact.path.suffix.lower() in {".json", ".md"}:
        content_path = artifact.path
    if content_path is not None:
        raw = content_path.read_text(encoding="utf-8")
        metadata["content"] = json.loads(raw) if content_path.suffix.lower() == ".json" else raw
    return metadata


@router.get("/artifacts/{artifact_id}/access")
async def create_media_access(
    artifact_id: str,
    request: Request,
    _user: dict[str, Any] = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    """Create a short-lived URL usable by native audio and video elements."""
    try:
        artifact = _catalog(request).artifact(artifact_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Learning artifact not found") from error
    settings = request.app.state.settings
    expires_at = int(time.time()) + settings.learning_media_signed_url_ttl_seconds
    token = sign_media_token(
        settings.secret_key,
        artifact_id=artifact_id,
        checksum=artifact.metadata["sha256"],
        expires_at=expires_at,
    )
    return {
        "url": f"/api/learning-media/media/{token}",
        "expires_at": expires_at,
    }


@router.get("/media/{token}")
async def stream_media(token: str, request: Request) -> Response:
    """Serve one immutable artifact through an expiring capability URL."""
    parsed = verify_media_token(request.app.state.settings.secret_key, token)
    if parsed is None:
        raise HTTPException(status_code=403, detail="Invalid or expired media URL")
    try:
        artifact = _catalog(request).artifact(parsed["artifact_id"])
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Learning artifact not found") from error
    if artifact.metadata["sha256"] != parsed["checksum"]:
        raise HTTPException(status_code=403, detail="Media URL no longer matches the artifact")

    size = artifact.path.stat().st_size
    try:
        start, end, partial = parse_byte_range(request.headers.get("range"), size)
    except ValueError as error:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
            content=str(error),
        )

    length = end - start + 1
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "ETag": f'"{artifact.metadata["sha256"]}"',
        "Cache-Control": "private, max-age=300",
        "Content-Security-Policy": (
            "sandbox allow-scripts; default-src 'none'; "
            "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "img-src data:; media-src 'self'"
        ),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        file_chunks(artifact.path, start, end),
        status_code=206 if partial else 200,
        media_type=media_type_for(artifact.path),
        headers=headers,
    )
