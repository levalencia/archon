"""HTTP byte-range parsing and streaming for learning media."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def parse_byte_range(value: str | None, size: int) -> tuple[int, int, bool]:
    """Parse one RFC 7233 byte range and return start, end, is_partial."""
    if size <= 0:
        raise ValueError("cannot range an empty file")
    if value is None:
        return 0, size - 1, False
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("only one bytes range is supported")
    raw = value.removeprefix("bytes=")
    if "-" not in raw:
        raise ValueError("malformed byte range")
    start_text, end_text = raw.split("-", 1)
    try:
        if not start_text:
            suffix = int(end_text)
            if suffix <= 0:
                raise ValueError("invalid suffix range")
            start = max(size - suffix, 0)
            end = size - 1
        else:
            start = int(start_text)
            end = size - 1 if not end_text else int(end_text)
    except ValueError as error:
        raise ValueError("malformed byte range") from error
    if start < 0 or end < start or start >= size:
        raise ValueError("unsatisfiable byte range")
    return start, min(end, size - 1), True


def file_chunks(
    path: Path, start: int, end: int, *, chunk_size: int = 64 * 1024
) -> Iterator[bytes]:
    """Yield exactly the requested inclusive byte range."""
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
