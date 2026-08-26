"""Docker sandbox boundary unit tests use a fake Docker process only."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from app.config import Settings
from app.main import create_app
from app.tools.sandbox import (
    DockerSandboxConfig,
    DockerSandboxExecutor,
    SandboxResult,
    execute_sandboxed,
)


def config(**changes: Any) -> DockerSandboxConfig:
    values = {
        "binary": "/trusted/docker",
        "image": "sandbox@sha256:" + "a" * 64,
        "platform": "linux/amd64",
        "timeout_seconds": 3.0,
        "cpus": 0.5,
        "memory_mb": 128,
        "pids_limit": 32,
        "output_bytes": 4096,
    }
    values.update(changes)
    return DockerSandboxConfig(**cast(Any, values))


def test_fixed_docker_argv_has_all_boundaries_and_no_content() -> None:
    executor = DockerSandboxExecutor(config())
    argv = executor._argv("archon-sandbox-fixed", "python")
    assert argv == (
        "/trusted/docker",
        "run",
        "--rm",
        "--name",
        "archon-sandbox-fixed",
        "--label",
        "com.archon.sandbox=true",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "0.5",
        "--user",
        "65532:65532",
        "--workdir",
        "/work",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--tmpfs",
        "/work:rw,nosuid,nodev,size=16m",
        "--env",
        "HOME=/tmp",
        "--env",
        "PATH=/usr/local/bin:/usr/bin:/bin",
        "-i",
        "sandbox@sha256:" + "a" * 64,
        "python",
        "-I",
        "-",
    )
    assert "untrusted-content" not in argv
    assert not any(argument.startswith("--volume") or argument == "-v" for argument in argv)


class FakeStdin:
    def __init__(self) -> None:
        self.value = b""
        self.closed = False

    def write(self, value: bytes) -> None:
        self.value += value

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdout: bytes = b"ok\n", stderr: bytes = b"") -> None:
        self.stdin = FakeStdin()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr.feed_data(stderr)
        self.stderr.feed_eof()
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = 137

    async def communicate(self) -> tuple[bytes, bytes]:
        self.returncode = 0
        return b"", b""


@pytest.mark.asyncio
async def test_execute_uses_exec_fixed_env_and_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    processes: list[FakeProcess] = []

    async def fake_create(*args: str, **kwargs: Any) -> FakeProcess:
        process = FakeProcess()
        calls.append((args, kwargs))
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    result = await DockerSandboxExecutor(config()).execute("untrusted-content", kind="python")
    assert result.stdout == "ok\n" and result.isolation == "docker"
    run_args, run_kwargs = calls[0]
    assert run_args[1] == "run"
    assert "untrusted-content" not in run_args
    assert run_kwargs["env"] == {"PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"}
    assert processes[0].stdin.value == b"untrusted-content"
    assert processes[0].stdin.closed
    assert calls[-1][0][1:3] == ("rm", "-f")
    assert calls[-1][0][3].startswith("archon-sandbox-")
    assert not hasattr(asyncio, "create_subprocess_shell") or all(
        args[1] != "sh -c" for args, _ in calls
    )


@pytest.mark.asyncio
async def test_legacy_code_adapter_has_no_host_fallback() -> None:
    with pytest.raises(RuntimeError, match="no isolated executor"):
        await execute_sandboxed("print('host')")


def test_settings_require_digest_when_requested() -> None:
    with pytest.raises(ValueError, match="sha256 digest"):
        Settings(
            memory_encryption_enabled=False,
            execution_enabled=True,
            execution_require_image_digest=True,
            execution_docker_image="sandbox:latest",
        )


class FailingExecutor:
    async def preflight(self) -> None:
        raise RuntimeError("docker unavailable")

    async def execute(
        self, content: str, *, kind: str, timeout: float | None = None
    ) -> SandboxResult:
        raise AssertionError("not reached")


@pytest.mark.asyncio
async def test_enabled_startup_fails_closed_on_preflight() -> None:
    settings = Settings(
        memory_encryption_enabled=False,
        execution_enabled=True,
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings, sandbox_executor_factory=lambda _: FailingExecutor())
    with pytest.raises(RuntimeError, match="docker unavailable"):
        async with app.router.lifespan_context(app):
            pass
