"""Authenticated serving of generated images from private temporary storage."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from app.security.auth import get_current_user
from app.tools.image_storage import image_path

router = APIRouter(
    prefix="/api/images",
    tags=["images"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/{filename}")
async def serve_image(filename: str) -> FileResponse | JSONResponse:
    """Serve a generated image only when its resolved path is safely contained."""
    try:
        filepath = image_path(filename)
    except ValueError:
        filepath = None
    if filepath is None or not filepath.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)

    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }
    return FileResponse(
        filepath,
        media_type=media_types.get(filepath.suffix.lower(), "application/octet-stream"),
    )
