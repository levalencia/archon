"""Private process-local storage for generated images."""

from __future__ import annotations

import tempfile
from pathlib import Path

IMAGES_DIR = Path(tempfile.mkdtemp(prefix="archon_generated_images_"))


def image_path(filename: str) -> Path:
    """Return a contained image path, rejecting traversal and nested paths."""
    if not filename or Path(filename).name != filename:
        raise ValueError("Invalid image filename")
    path = (IMAGES_DIR / filename).resolve()
    if path.parent != IMAGES_DIR.resolve():
        raise ValueError("Invalid image filename")
    return path
