"""Safe, metadata-only adapters for optional external skill catalogs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit

_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_KEYS = {
    "external_id",
    "name",
    "description",
    "source_url",
    "repository",
    "path",
    "revision",
}


def _open_regular_beneath(root: Path, source: Path) -> tuple[int, os.stat_result]:
    """Open a resolved file through a no-follow descriptor chain rooted at ``root``."""
    relative = source.relative_to(root)
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_DIRECTORY", 0)
    )
    descriptor = os.open(root, directory_flags)
    try:
        for component in relative.parts[:-1]:
            child = os.open(component, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        opened = os.open(relative.parts[-1], file_flags, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    source_stat = os.fstat(opened)
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
        os.close(opened)
        raise ValueError("catalog source must be a singly-linked regular file")
    return opened, source_stat


@dataclass(frozen=True, slots=True)
class ExternalSkillMetadata:
    """Untrusted discovery metadata. It deliberately cannot contain executable bodies."""

    external_id: str
    name: str
    description: str
    source_url: str
    repository: str
    path: str
    revision: str | None = None


class SkillCatalogProvider(Protocol):
    """Read-only metadata discovery boundary for optional external catalogs."""

    @property
    def health_code(self) -> str: ...

    async def search(self, query: str, *, limit: int) -> tuple[ExternalSkillMetadata, ...]: ...


class UnavailableSkillCatalogProvider:
    """No-op provider used for disabled or invalid optional configuration."""

    def __init__(self, health_code: str = "disabled") -> None:
        self._health_code = health_code

    @property
    def health_code(self) -> str:
        return self._health_code

    async def search(self, query: str, *, limit: int) -> tuple[ExternalSkillMetadata, ...]:
        del query, limit
        return ()


class AgentGodModeCatalogProvider:
    """Bounded adapter for a fixed command or JSON index under an allowlisted root."""

    def __init__(
        self,
        *,
        allowlisted_root: str,
        executable: str = "",
        json_index: str = "",
        timeout_seconds: float = 2.0,
        max_stdout_bytes: int = 65_536,
        max_results: int = 50,
    ) -> None:
        if bool(executable) == bool(json_index):
            raise ValueError("exactly one catalog source must be configured")
        if not 0.05 <= timeout_seconds <= 30:
            raise ValueError("invalid catalog timeout")
        if not 1_024 <= max_stdout_bytes <= 1_048_576:
            raise ValueError("invalid catalog output limit")
        if not 1 <= max_results <= 100:
            raise ValueError("invalid catalog result limit")
        root = Path(allowlisted_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("catalog root is not a directory")
        source = Path(executable or json_index).expanduser().resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("catalog source is outside the allowlisted root")
        descriptor, source_stat = _open_regular_beneath(root, source)
        try:
            if executable and not source_stat.st_mode & 0o111:
                raise ValueError("catalog executable is not executable")
        except BaseException:
            os.close(descriptor)
            raise
        self._source_path = source
        self._source_fd = descriptor
        self._source_identity = (source_stat.st_dev, source_stat.st_ino)
        self._executable = source if executable else None
        self._json_index = source if json_index else None
        self._execution_dir: str | None = None
        self._safe_executable: Path | None = None
        self._execution_identity: tuple[int, int] | None = None
        if executable:
            execution_dir = tempfile.mkdtemp(prefix="archon-skill-catalog-")
            safe_executable = Path(execution_dir) / "catalog"
            copy_fd = os.open(safe_executable, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
            with os.fdopen(copy_fd, "wb") as stream:
                offset = 0
                while chunk := os.pread(descriptor, 65_536, offset):
                    stream.write(chunk)
                    offset += len(chunk)
            execution_stat = os.lstat(safe_executable)
            self._execution_dir = execution_dir
            self._safe_executable = safe_executable
            self._execution_identity = (execution_stat.st_dev, execution_stat.st_ino)
        self._timeout = timeout_seconds
        self._max_bytes = max_stdout_bytes
        self._max_results = max_results
        self._health_code = "available"

    def __del__(self) -> None:
        descriptor = getattr(self, "_source_fd", -1)
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
            self._source_fd = -1
        safe_executable = getattr(self, "_safe_executable", None)
        execution_dir = getattr(self, "_execution_dir", None)
        if safe_executable is not None:
            with contextlib.suppress(OSError):
                safe_executable.unlink()
        if execution_dir is not None:
            with contextlib.suppress(OSError):
                os.rmdir(execution_dir)

    @property
    def health_code(self) -> str:
        return self._health_code

    async def search(self, query: str, *, limit: int) -> tuple[ExternalSkillMetadata, ...]:
        bounded_limit = min(max(limit, 0), self._max_results)
        if not query.strip() or bounded_limit == 0:
            return ()
        try:
            raw = (
                await self._run_command(query)
                if self._executable is not None
                else await self._read_index()
            )
            parsed = _parse_catalog(raw, self._max_results)
        except TimeoutError:
            self._health_code = "timeout"
            return ()
        except _OutputTooLargeError:
            self._health_code = "output_too_large"
            return ()
        except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            self._health_code = "malformed_output"
            return ()
        self._health_code = "available"
        if self._json_index is not None:
            terms = query.casefold().split()
            parsed = tuple(
                item
                for item in parsed
                if all(
                    term
                    in " ".join(
                        (item.external_id, item.name, item.description, item.repository, item.path)
                    ).casefold()
                    for term in terms
                )
            )
        return parsed[:bounded_limit]

    async def _run_command(self, query: str) -> bytes:
        assert self._executable is not None
        current = os.fstat(self._source_fd)
        pathname = os.lstat(self._source_path)
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or not stat.S_ISREG(pathname.st_mode)
            or pathname.st_nlink != 1
            or (current.st_dev, current.st_ino) != self._source_identity
            or (pathname.st_dev, pathname.st_ino) != self._source_identity
        ):
            raise OSError("catalog executable identity changed")
        assert self._safe_executable is not None
        safe = os.lstat(self._safe_executable)
        if (
            not stat.S_ISREG(safe.st_mode)
            or safe.st_nlink != 1
            or (safe.st_dev, safe.st_ino) != self._execution_identity
        ):
            raise OSError("private catalog executable identity changed")
        process = await asyncio.create_subprocess_exec(
            str(self._safe_executable),
            query,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            start_new_session=True,
        )
        assert process.stdout is not None
        try:
            raw = await asyncio.wait_for(process.stdout.read(self._max_bytes + 1), self._timeout)
            if len(raw) > self._max_bytes:
                raise _OutputTooLargeError
            return_code = await asyncio.wait_for(process.wait(), self._timeout)
            if return_code != 0:
                raise ValueError("catalog command failed")
            return raw
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

    async def _read_index(self) -> bytes:
        assert self._json_index is not None

        def read() -> bytes:
            current = os.fstat(self._source_fd)
            if (
                not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
                or (current.st_dev, current.st_ino) != self._source_identity
            ):
                raise OSError("catalog index identity changed")
            data = os.pread(self._source_fd, self._max_bytes + 1, 0)
            if len(data) > self._max_bytes:
                raise _OutputTooLargeError
            return data

        return await asyncio.wait_for(asyncio.to_thread(read), self._timeout)


class _OutputTooLargeError(ValueError):
    pass


def _text(row: dict[str, Any], key: str, *, maximum: int, allow_empty: bool = False) -> str:
    value = row.get(key)
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or (not allow_empty and not value.strip())
    ):
        raise ValueError(f"invalid {key}")
    if any(ord(character) < 32 and character not in "\t\n" for character in value):
        raise ValueError(f"invalid {key}")
    return value.strip()


def _parse_catalog(raw: bytes, max_results: int) -> tuple[ExternalSkillMetadata, ...]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, list) or len(value) > max_results:
        raise ValueError("catalog must be a bounded JSON array")
    result: list[ExternalSkillMetadata] = []
    for unknown in value:
        if not isinstance(unknown, dict) or set(unknown) - _ALLOWED_KEYS:
            raise ValueError("invalid catalog item")
        row: dict[str, Any] = unknown
        external_id = _text(row, "external_id", maximum=128)
        if not _EXTERNAL_ID.fullmatch(external_id):
            raise ValueError("invalid external_id")
        repository = _text(row, "repository", maximum=255)
        if not _REPOSITORY.fullmatch(repository):
            raise ValueError("invalid repository")
        source_url = _text(row, "source_url", maximum=2048)
        url = urlsplit(source_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("invalid source_url")
        path_value = _text(row, "path", maximum=500)
        path = PurePosixPath(path_value)
        if (
            path.is_absolute()
            or "\\" in path_value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("invalid path")
        revision_value = row.get("revision")
        if revision_value is not None and (
            not isinstance(revision_value, str) or not _REVISION.fullmatch(revision_value)
        ):
            raise ValueError("invalid revision")
        result.append(
            ExternalSkillMetadata(
                external_id=external_id,
                name=_text(row, "name", maximum=100),
                description=_text(row, "description", maximum=2000),
                source_url=source_url,
                repository=repository,
                path=path.as_posix(),
                revision=revision_value,
            )
        )
    return tuple(result)


def create_skill_catalog_provider(
    *,
    enabled: bool,
    allowlisted_root: str,
    executable: str,
    json_index: str,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_results: int,
) -> SkillCatalogProvider:
    """Create the optional provider without making application startup depend on it."""
    if not enabled:
        return UnavailableSkillCatalogProvider()
    try:
        return AgentGodModeCatalogProvider(
            allowlisted_root=allowlisted_root,
            executable=executable,
            json_index=json_index,
            timeout_seconds=timeout_seconds,
            max_stdout_bytes=max_stdout_bytes,
            max_results=max_results,
        )
    except (OSError, ValueError):
        return UnavailableSkillCatalogProvider("misconfigured")
