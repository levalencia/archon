"""Strict path and MIME controls for published learning media."""

from __future__ import annotations

from pathlib import Path

ALLOWED_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".vtt": "text/vtt; charset=utf-8",
    ".srt": "application/x-subrip",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}


def resolve_published_file(root: str | Path, relative_path: str) -> Path:
    """Resolve one catalog path, rejecting traversal, symlinks, and unknown types."""
    library_root = Path(root).expanduser().resolve()
    if not relative_path or "\x00" in relative_path:
        raise ValueError("empty or invalid learning-media path")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("published",):
        raise ValueError("learning-media path must remain below published")
    candidate = library_root / relative
    if candidate.is_symlink() or any(
        part.is_symlink() for part in candidate.parents if part != library_root
    ):
        raise ValueError("symlinked learning media is not allowed")
    resolved = candidate.resolve()
    published_root = (library_root / "published").resolve()
    if published_root not in resolved.parents or not resolved.is_file():
        raise ValueError("learning-media file is missing or escapes the library")
    if resolved.suffix.lower() not in ALLOWED_MEDIA_TYPES:
        raise ValueError("unsupported learning-media file type")
    return resolved


def media_type_for(path: Path) -> str:
    """Return the allowlisted MIME type for a validated path."""
    try:
        return ALLOWED_MEDIA_TYPES[path.suffix.lower()]
    except KeyError as error:
        raise ValueError("unsupported learning-media file type") from error
