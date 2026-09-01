"""Bounded filesystem adapters for project instruction formats.

This module only scans an already-authorized workspace root.  Establishing that
trust boundary belongs to the caller; every path returned here is canonical and
contained by that root.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

_INCLUDE_RE: Final = re.compile(r"^\s*@include\s+(.+?)\s*$")
_SECURE_TRAVERSAL_AVAILABLE: Final = (
    hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
)
_DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)


class InstructionLoadError(ValueError):
    """A workspace instruction tree is invalid or exceeds a safety bound."""


class InstructionFamily(StrEnum):
    """Explicitly selected on-disk compatibility family."""

    ARCHON = "archon"
    AGENTS = "agents"
    CLAUDE = "claude"


@dataclass(frozen=True, slots=True)
class InstructionLimits:
    """Resource limits applied across one complete scan."""

    max_file_bytes: int = 64_000
    max_total_bytes: int = 256_000
    max_files: int = 32
    max_directory_depth: int = 32
    max_import_depth: int = 8

    def __post_init__(self) -> None:
        for name in (
            "max_file_bytes",
            "max_total_bytes",
            "max_files",
            "max_directory_depth",
            "max_import_depth",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class InstructionSource:
    """Typed, immutable instruction content with safe provenance."""

    content: str
    path: Path
    relative_path: str
    scope_path: str
    family: InstructionFamily
    is_override: bool
    byte_count: int
    content_hash: str
    import_depth: int = 0

    @classmethod
    def from_content(
        cls,
        content: str,
        relative_path: str,
        scope_path: str,
        family: InstructionFamily | str,
        *,
        path: Path | None = None,
        is_override: bool = False,
        import_depth: int = 0,
    ) -> InstructionSource:
        """Build a typed source for snapshots already loaded by a trusted caller."""
        family = InstructionFamily(family)
        raw = content.encode("utf-8")
        relative = _safe_relative(relative_path)
        scope = _safe_scope(scope_path)
        return cls(
            content=content,
            path=(path or Path(relative)).resolve(),
            relative_path=relative,
            scope_path=scope,
            family=family,
            is_override=is_override,
            byte_count=len(raw),
            content_hash=hashlib.sha256(raw).hexdigest(),
            import_depth=import_depth,
        )


@dataclass(slots=True)
class _LoadState:
    root: Path
    family: InstructionFamily
    limits: InstructionLimits
    sources: list[InstructionSource]
    active: set[Path]
    seen: set[Path]
    total_bytes: int = 0


def load_project_instructions(
    workspace_root: Path | str,
    target_path: Path | str = ".",
    *,
    family: InstructionFamily | str = InstructionFamily.ARCHON,
    limits: InstructionLimits | None = None,
) -> tuple[InstructionSource, ...]:
    """Load one configured family from workspace root toward ``target_path``.

    ``@include relative/path.md`` lines recursively add files after their
    including source. Includes are workspace-relative to the including file,
    bounded, cycle checked, and removed from the including content.
    """
    root = Path(workspace_root).resolve(strict=True)
    if not root.is_dir():
        raise InstructionLoadError("workspace root must be a directory")
    selected_family = InstructionFamily(family)
    selected_limits = limits or InstructionLimits()
    target = _contained(root, root / Path(target_path), "target")
    target_dir = target if target.is_dir() or str(target_path) in {"", "."} else target.parent
    try:
        relative_dir = target_dir.relative_to(root)
    except ValueError as exc:
        raise InstructionLoadError("target path escapes workspace") from exc
    parts = relative_dir.parts
    if len(parts) > selected_limits.max_directory_depth:
        raise InstructionLoadError("directory depth limit exceeded")

    state = _LoadState(root, selected_family, selected_limits, [], set(), set())
    directories = [root]
    current = root
    for part in parts:
        current /= part
        directories.append(current)
    for directory in directories:
        candidate, override = _candidate(directory, selected_family)
        if candidate is not None:
            _load_file(state, candidate, directory, override, 0)
    return tuple(state.sources)


def _candidate(directory: Path, family: InstructionFamily) -> tuple[Path | None, bool]:
    if family is InstructionFamily.ARCHON:
        path = directory / ".archon" / "instructions.md"
        return (path, False) if path.exists() or path.is_symlink() else (None, False)
    if family is InstructionFamily.CLAUDE:
        path = directory / "CLAUDE.md"
        return (path, False) if path.exists() or path.is_symlink() else (None, False)
    override = directory / "AGENTS.override.md"
    normal = directory / "AGENTS.md"
    if override.exists() or override.is_symlink():
        return override, True
    return (normal, False) if normal.exists() or normal.is_symlink() else (None, False)


def _read_regular_file(root: Path, path: Path, max_bytes: int) -> bytes:
    """Read a single-link regular file through a no-follow descriptor chain."""
    if not _SECURE_TRAVERSAL_AVAILABLE:
        raise InstructionLoadError("secure workspace traversal is unavailable")
    try:
        components = list(path.relative_to(root).parts)
    except ValueError as exc:
        raise InstructionLoadError("instruction path escapes workspace") from exc
    if not components or any(component in {"", ".", ".."} for component in components):
        raise InstructionLoadError("invalid instruction path")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(root, _DIRECTORY_FLAGS)
        for component in components[:-1]:
            next_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(components[-1], _FILE_FLAGS, dir_fd=directory_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise InstructionLoadError("instruction source is not a regular file")
        if metadata.st_nlink != 1:
            raise InstructionLoadError("instruction hardlinks are not allowed")
        if metadata.st_size > max_bytes:
            raise InstructionLoadError("instruction file bytes limit exceeded")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise InstructionLoadError("instruction file bytes limit exceeded")
        return raw
    except InstructionLoadError:
        raise
    except (OSError, ValueError):
        raise InstructionLoadError("unable to read instruction safely") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _load_file(
    state: _LoadState,
    requested: Path,
    scope_directory: Path,
    is_override: bool,
    depth: int,
) -> None:
    if depth > state.limits.max_import_depth:
        raise InstructionLoadError("import depth limit exceeded")
    if requested.is_symlink():
        raise InstructionLoadError("instruction symlink is not allowed")
    path = _contained(state.root, requested, "instruction")
    if path in state.active:
        raise InstructionLoadError("instruction import cycle detected")
    if path in state.seen:
        return
    if len(state.seen) >= state.limits.max_files:
        raise InstructionLoadError("instruction file count limit exceeded")
    raw = _read_regular_file(state.root, path, state.limits.max_file_bytes)
    size = len(raw)
    if state.total_bytes + size > state.limits.max_total_bytes:
        raise InstructionLoadError("instruction total bytes limit exceeded")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstructionLoadError("instruction must be UTF-8") from exc

    state.total_bytes += size
    state.seen.add(path)
    state.active.add(path)
    body: list[str] = []
    imports: list[str] = []
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if match:
            imports.append(match.group(1).strip())
        else:
            body.append(line)
    content = "\n".join(body).strip()
    relative = path.relative_to(state.root).as_posix()
    scope = scope_directory.relative_to(state.root).as_posix() or "."
    state.sources.append(
        InstructionSource.from_content(
            content,
            relative,
            scope,
            state.family,
            path=path,
            is_override=is_override,
            import_depth=depth,
        )
    )
    try:
        for imported in imports:
            import_path = _import_path(path.parent, imported)
            _load_file(state, import_path, scope_directory, False, depth + 1)
    finally:
        state.active.remove(path)


def _contained(root: Path, candidate: Path, label: str) -> Path:
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise InstructionLoadError(f"{label} path escapes workspace") from exc
    return resolved


def _import_path(parent: Path, value: str) -> Path:
    if not value or "\x00" in value:
        raise InstructionLoadError("invalid instruction import path")
    path = Path(value)
    if path.is_absolute():
        raise InstructionLoadError("instruction path escapes workspace")
    return parent / path


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise ValueError("relative_path must be a canonical relative path")
    return path.as_posix()


def _safe_scope(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("scope_path must be workspace-relative")
    return path.as_posix() or "."
