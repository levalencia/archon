"""Image serving + generation API routes.

GET /api/images/{filename} — Serve generated images
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(prefix="/api/images", tags=["images"])

IMAGES_DIR = Path("/tmp/archon_generated_images")


@router.get("/{filename}")
async def serve_image(filename: str) -> FileResponse:
    """Serve a generated image file."""
    filepath = IMAGES_DIR / filename
    if not filepath.exists():
        from fastapi.responses import JSONResponse

        return JSONResponse(
            {"error": "Image not found"},
            status_code=404,
        )

    # Determine media type
    suffix = filepath.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }

    return FileResponse(
        filepath,
        media_type=media_types.get(suffix, "application/octet-stream"),
    )
