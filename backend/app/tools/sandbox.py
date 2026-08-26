"""Docker-backed execution boundary for untrusted code and shell input."""

from __future__ import annotations

import asyncio
import re
import secrets
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

import structlog

logger = structlog.get_logger()
ExecutionKind = Literal["python", "shell"]
_IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
_REGISTRY_DIGEST_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:+-]*@sha256:[0-9a-f]{64}")


def is_immutable_image_reference(image: str) -> bool:
    """Accept only a registry digest or an exact local Docker image ID."""
    return bool(_IMAGE_ID_PATTERN.fullmatch(image) or _REGISTRY_DIGEST_PATTERN.fullmatch(image))


@dataclass(frozen=True, slots=True)
class SandboxResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    truncated: bool
    isolation: str = "docker"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SandboxExecutor(Protocol):
    async def preflight(self) -> None: ...

    async def execute(
        self, content: str, *, kind: ExecutionKind, timeout: float | None = None
    ) -> SandboxResult: ...


@dataclass(frozen=True, slots=True)
class DockerSandboxConfig:
    binary: str
    image: str
    platform: str
    timeout_seconds: float
    cpus: float
    memory_mb: int
    pids_limit: int
    output_bytes: int


class DockerSandboxExecutor:
    """Run input in an ephemeral, networkless, mountless Docker container."""

    _CLIENT_ENV = {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"}
    _CLIENT_TIMEOUT_SECONDS = 10.0
    _CLEANUP_TIMEOUT_SECONDS = 2.0

    def __init__(self, config: DockerSandboxConfig) -> None:
        if not is_immutable_image_reference(config.image):
            raise ValueError("Docker sandbox image must be an immutable sha256 reference")
        self.config = config

    async def _client_call(self, *args: str) -> tuple[int, bytes, bytes]:
        proc: asyncio.subprocess.Process | None = None
        try:
            async with asyncio.timeout(self._CLIENT_TIMEOUT_SECONDS):
                proc = await asyncio.create_subprocess_exec(
                    self.config.binary,
                    *args,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self._CLIENT_ENV,
                )
                stdout, stderr = await proc.communicate()
                return proc.returncode or 0, stdout, stderr
        except (FileNotFoundError, PermissionError) as exc:
            raise RuntimeError("Docker sandbox binary is unavailable") from exc
        finally:
            if proc is not None and proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=0.5)

    async def preflight(self) -> None:
        """Fail closed unless the Docker client, daemon, platform and image are usable."""
        try:
            version_code, _, _ = await self._client_call(
                "version", "--format", "{{.Server.Version}}"
            )
            image_code, image_stdout, _ = await self._client_call(
                "image", "inspect", "--format", "{{.Id}}", self.config.image
            )
        except TimeoutError as exc:
            raise RuntimeError("Docker sandbox preflight timed out") from exc
        if version_code != 0:
            raise RuntimeError("Docker sandbox daemon is unavailable")
        if image_code != 0:
            raise RuntimeError("Docker sandbox image is unavailable")
        resolved_image_id = image_stdout.decode(errors="replace").strip()
        if not _IMAGE_ID_PATTERN.fullmatch(resolved_image_id):
            raise RuntimeError("Docker sandbox image did not resolve to an immutable image ID")
        if (
            _IMAGE_ID_PATTERN.fullmatch(self.config.image)
            and resolved_image_id != self.config.image
        ):
            raise RuntimeError(
                "Docker sandbox resolved image ID does not match configured image ID"
            )

    def _argv(self, name: str, kind: ExecutionKind) -> tuple[str, ...]:
        command = ("python", "-I", "-") if kind == "python" else ("sh", "-s")
        return (
            self.config.binary,
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            "com.archon.sandbox=true",
            "--platform",
            self.config.platform,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.config.pids_limit),
            "--memory",
            f"{self.config.memory_mb}m",
            "--cpus",
            str(self.config.cpus),
            "--user",
            "65532:65532",
            "--workdir",
            "/work",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=16m",  # nosec B108: container tmpfs, not host
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=16m",
            "--env",
            "HOME=/tmp",
            "--env",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "-i",
            self.config.image,
            *command,
        )

    async def _remove(self, name: str) -> None:
        with suppress(Exception):
            await self._client_call("rm", "-f", name)

    async def _cleanup_process(self, proc: asyncio.subprocess.Process | None, name: str) -> None:
        if proc is not None:
            if proc.stdin is not None:
                with suppress(Exception):
                    proc.stdin.close()
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.kill()
                with suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=0.5)
        await self._remove(name)

    async def _cleanup_bounded(self, proc: asyncio.subprocess.Process | None, name: str) -> None:
        async def bounded_cleanup() -> None:
            async with asyncio.timeout(self._CLEANUP_TIMEOUT_SECONDS):
                await self._cleanup_process(proc, name)

        cleanup_task = asyncio.create_task(bounded_cleanup())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            # The caller's cancellation must not interrupt container removal.
            with suppress(TimeoutError):
                await asyncio.shield(cleanup_task)
            raise
        except TimeoutError:
            logger.error("sandbox_cleanup_timed_out", container=name)

    async def execute(
        self, content: str, *, kind: ExecutionKind, timeout: float | None = None
    ) -> SandboxResult:
        if kind not in ("python", "shell"):
            raise ValueError("Unsupported execution kind")
        limit = self.config.output_bytes
        wall_timeout = (
            self.config.timeout_seconds
            if timeout is None
            else min(max(timeout, 0.1), self.config.timeout_seconds)
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wall_timeout
        name = f"archon-sandbox-{secrets.token_hex(12)}"
        proc: asyncio.subprocess.Process | None = None
        stdout = bytearray()
        stderr = bytearray()
        truncated = False
        timed_out = False
        cap_reached = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []

        async def read_bounded(stream: asyncio.StreamReader, destination: bytearray) -> None:
            nonlocal truncated
            while chunk := await stream.read(8192):
                remaining = limit - len(stdout) - len(stderr)
                if remaining <= 0:
                    truncated = True
                    cap_reached.set()
                    return
                destination.extend(chunk[:remaining])
                if len(chunk) > remaining or len(stdout) + len(stderr) >= limit:
                    truncated = True
                    cap_reached.set()
                    return

        try:
            try:
                # One monotonic deadline covers client spawn, stdin delivery and closure,
                # output readers, and waiting for the Docker client to exit.
                async with asyncio.timeout_at(deadline):
                    proc = await asyncio.create_subprocess_exec(
                        *self._argv(name, kind),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=self._CLIENT_ENV,
                    )
                    assert (
                        proc.stdin is not None
                        and proc.stdout is not None
                        and proc.stderr is not None
                    )
                    stdout_task = asyncio.create_task(read_bounded(proc.stdout, stdout))
                    stderr_task = asyncio.create_task(read_bounded(proc.stderr, stderr))
                    wait_task = asyncio.create_task(proc.wait())
                    cap_task = asyncio.create_task(cap_reached.wait())
                    tasks.extend((stdout_task, stderr_task, wait_task, cap_task))

                    proc.stdin.write(content.encode("utf-8"))
                    await proc.stdin.drain()
                    proc.stdin.close()
                    await proc.stdin.wait_closed()

                    done, _ = await asyncio.wait(
                        (wait_task, cap_task), return_when=asyncio.FIRST_COMPLETED
                    )
                    if cap_task not in done:
                        await asyncio.gather(stdout_task, stderr_task)
            except TimeoutError:
                timed_out = True

            exit_code = proc.returncode if proc is not None and proc.returncode is not None else 137
            if timed_out and not stderr:
                stderr.extend(b"Execution timed out")
            result = SandboxResult(
                stdout.decode(errors="replace"),
                stderr.decode(errors="replace"),
                exit_code,
                timed_out,
                truncated,
            )
            logger.info(
                "sandbox_executed",
                kind=kind,
                exit_code=exit_code,
                timed_out=timed_out,
                truncated=truncated,
                output_bytes=len(stdout) + len(stderr),
                isolation="docker",
            )
            return result
        finally:
            # Stop the process first so pipe readers can observe EOF and release their
            # transports before the event loop closes.
            await self._cleanup_bounded(proc, name)
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if proc is not None:
                # asyncio's subprocess transport is finalized only after all pipes are
                # drained; doing that here prevents transport cleanup after loop close.
                with suppress(Exception):
                    await asyncio.wait_for(proc.communicate(), timeout=0.5)


async def execute_sandboxed(
    code: str,
    language: str = "python",
    timeout: float = 10.0,
    max_memory_mb: int = 256,
    *,
    executor: SandboxExecutor | None = None,
) -> dict[str, object]:
    """Legacy adapter; execution is impossible without explicit isolated injection."""
    del max_memory_mb
    if executor is None:
        raise RuntimeError("Sandbox execution is disabled: no isolated executor configured")
    if language != "python":
        return {"error": f"Unsupported language: {language}", "exit_code": 1}
    return (await executor.execute(code, kind="python", timeout=timeout)).to_dict()
