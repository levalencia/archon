from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[3]))

from sandbox_runner import server as runner_server

from app.config import Settings
from app.main import create_app
from app.tools.sandbox import SandboxResult
from app.tools.sandbox_client import SandboxClientConfig, SandboxRunnerClient


def test_runner_image_installs_seccomp_runtime() -> None:
    dockerfile = (Path(__file__).parents[3] / "sandbox_runner" / "Dockerfile").read_text()
    assert "apt-get install --yes --no-install-recommends libseccomp2" in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def short_socket(name: str) -> Path:
    return Path("/tmp") / f"archon-{name}-{uuid.uuid4().hex[:8]}.sock"


@pytest.mark.asyncio
async def test_runner_allowlist_timeout_output_and_safe_errors(tmp_path: Path) -> None:
    runner_server.WORK_DIR = tmp_path
    runner_server.COMMANDS["python"] = (sys.executable, "-I", "-")
    ok = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "a" * 32,
            "kind": "python",
            "content": "print('ok')",
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
        }
    )
    assert ok["stdout"] == "ok\n" and ok["isolation"] == "runner-container"

    rejected = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "b" * 32,
            "kind": "/bin/bash",
            "content": "SECRET_VALUE",
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
        }
    )
    assert rejected == {
        "version": 1,
        "status": "error",
        "request_id": "b" * 32,
        "error": "invalid_request",
    }
    assert "SECRET_VALUE" not in json.dumps(rejected)

    timed = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "c" * 32,
            "kind": "python",
            "content": "import time; time.sleep(30)",
            "timeout_seconds": 0.1,
            "output_bytes": 1024,
        }
    )
    assert timed["timed_out"] is True and timed["exit_code"] != 0

    blocked_stdin = await asyncio.wait_for(
        runner_server.execute(
            {
                "version": 1,
                "operation": "execute",
                "request_id": "6" * 32,
                "kind": "shell",
                "content": "sleep 30\n#" + "x" * 500_000,
                "timeout_seconds": 0.1,
                "output_bytes": 1024,
            }
        ),
        timeout=1.0,
    )
    assert blocked_stdin["timed_out"] is True

    capped = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "d" * 32,
            "kind": "python",
            "content": "print('x' * 5000)",
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
        }
    )
    assert capped["truncated"] is True
    assert len(capped["stdout"].encode()) + len(capped["stderr"].encode()) <= 1024

    extra = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "e" * 32,
            "kind": "python",
            "content": "print('ignored')",
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
            "unexpected": True,
        }
    )
    assert extra["status"] == "error" and extra["error"] == "invalid_request"


def test_response_frame_is_bounded_after_json_escaping() -> None:
    response = {
        "version": 1,
        "status": "ok",
        "request_id": "a" * 32,
        "stdout": "\x00" * runner_server.MAX_OUTPUT_BYTES,
        "stderr": "",
        "exit_code": 0,
        "timed_out": False,
        "truncated": False,
        "isolation": "runner-container",
    }
    frame = runner_server._encode_response(response)
    decoded = json.loads(frame)
    assert len(frame) <= runner_server.MAX_FRAME_BYTES
    assert decoded["truncated"] is True
    assert decoded["stdout"]


@pytest.mark.asyncio
async def test_successful_command_kills_detached_descendants(tmp_path: Path) -> None:
    runner_server.WORK_DIR = tmp_path
    result = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "3" * 32,
            "kind": "shell",
            "content": "sleep 30 </dev/null >/dev/null 2>&1 & echo $!",
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
        }
    )
    pid = int(result["stdout"].strip())
    for _ in range(20):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        stat = Path(f"/proc/{pid}/stat")
        try:
            if stat.exists() and stat.read_text().split()[2] == "Z":
                break
        except OSError:
            break
        await asyncio.sleep(0.025)
    else:
        pytest.fail("detached sandbox descendant survived successful execution")


@pytest.mark.asyncio
async def test_runner_serializes_execution_and_rejects_reentry(tmp_path: Path) -> None:
    runner_server.WORK_DIR = tmp_path
    runner_server.COMMANDS["python"] = (sys.executable, "-I", "-")
    runner_server.EXECUTION_ACTIVE = False
    socket_path = short_socket("actual")

    async def send(payload: dict) -> dict:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(json.dumps(payload).encode() + b"\n")
        await writer.drain()
        response = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        return response

    server = await asyncio.start_unix_server(
        runner_server.handle,
        path=socket_path,
        limit=runner_server.MAX_FRAME_BYTES + 1,
    )
    first_payload = {
        "version": 1,
        "operation": "execute",
        "request_id": "f" * 32,
        "kind": "python",
        "content": "import time;time.sleep(.25);print('done')",
        "timeout_seconds": 1.0,
        "output_bytes": 1024,
    }
    second_payload = {**first_payload, "request_id": "1" * 32, "content": "print('nested')"}
    abandoned_payload = {
        **first_payload,
        "request_id": "4" * 32,
        "content": "import time;time.sleep(5)",
        "timeout_seconds": 5.0,
    }
    async with server:
        first = asyncio.create_task(send(first_payload))
        await asyncio.sleep(0.05)
        second = await send(second_payload)
        completed = await first

        _, abandoned = await asyncio.open_unix_connection(socket_path)
        abandoned.write(json.dumps(abandoned_payload).encode() + b"\n")
        await abandoned.drain()
        for _ in range(40):
            if runner_server.EXECUTION_ACTIVE:
                break
            await asyncio.sleep(0.01)
        assert runner_server.EXECUTION_ACTIVE is True
        abandoned.close()
        await abandoned.wait_closed()
        for _ in range(40):
            if not runner_server.EXECUTION_ACTIVE:
                break
            await asyncio.sleep(0.025)
        assert runner_server.EXECUTION_ACTIVE is False
        recovered = await send(
            {**first_payload, "request_id": "5" * 32, "content": "print('recovered')"}
        )
    socket_path.unlink(missing_ok=True)
    assert second == {
        "version": 1,
        "status": "error",
        "request_id": "1" * 32,
        "error": "runner_busy",
    }
    assert completed["status"] == "ok" and completed["stdout"] == "done\n"
    assert recovered["status"] == "ok" and recovered["stdout"] == "recovered\n"


@pytest.mark.skipif(sys.platform != "linux", reason="seccomp is a Linux boundary")
@pytest.mark.asyncio
async def test_runner_child_seccomp_blocks_socket_and_control_file_mutation(tmp_path: Path) -> None:
    runner_server.WORK_DIR = tmp_path
    runner_server.COMMANDS["python"] = (sys.executable, "-I", "-")
    protected = tmp_path / "protected.sock"
    protected.write_text("control")
    control_dir = tmp_path / "control"
    control_dir.mkdir(mode=0o550)
    result = await runner_server.execute(
        {
            "version": 1,
            "operation": "execute",
            "request_id": "2" * 32,
            "kind": "python",
            "content": (
                "import os,socket\n"
                "try: socket.socket(); raise SystemExit('socket-open')\n"
                "except OSError: print('socket-blocked')\n"
                f"try: os.unlink({str(protected)!r}); raise SystemExit('unlink-worked')\n"
                "except OSError: print('unlink-blocked')\n"
                f"try: open({str(control_dir / 'payload')!r},'wb').write(b'x'); "
                "raise SystemExit('volume-write')\n"
                "except OSError: print('volume-blocked')\n"
                f"try: os.chmod({str(control_dir)!r},0o770); raise SystemExit('chmod-worked')\n"
                "except OSError: print('chmod-blocked')"
            ),
            "timeout_seconds": 1.0,
            "output_bytes": 1024,
        }
    )
    assert result["exit_code"] == 0
    assert result["stdout"] == ("socket-blocked\nunlink-blocked\nvolume-blocked\nchmod-blocked\n")
    assert protected.exists()
    assert not (control_dir / "payload").exists()


@pytest.mark.parametrize(
    "config",
    [
        SandboxClientConfig("relative.sock", 1, 1024),
        SandboxClientConfig("/tmp/runner.sock", float("nan"), 1024),
        SandboxClientConfig("/tmp/runner.sock", True, 1024),
        SandboxClientConfig("/tmp/runner.sock", 1, 100),
    ],
)
def test_runner_client_rejects_invalid_limits(config: SandboxClientConfig) -> None:
    with pytest.raises(ValueError):
        SandboxRunnerClient(config)


@pytest.mark.asyncio
async def test_unix_client_contract_has_no_host_fallback(tmp_path: Path) -> None:
    socket_path = short_socket("client")

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = json.loads(await reader.readline())
        response = (
            {"version": 1, "status": "ok"}
            if request["operation"] == "health"
            else {
                "version": 1,
                "status": "ok",
                "request_id": request["request_id"],
                "stdout": ("seccomp-ok\n" if "seccomp-ok" in request["content"] else "remote\n"),
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "truncated": False,
                "isolation": "runner-container",
            }
        )
        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(handler, path=socket_path)
    client = SandboxRunnerClient(SandboxClientConfig(str(socket_path), 1, 1024))
    async with server:
        await client.preflight()
        result = await client.execute("print('not local')", kind="python")
    socket_path.unlink(missing_ok=True)
    assert result.stdout == "remote\n" and result.isolation == "runner-container"

    missing_path = short_socket("missing")
    missing = SandboxRunnerClient(SandboxClientConfig(str(missing_path), 1, 1024))
    with pytest.raises(RuntimeError, match="unavailable"):
        await missing.execute("print('must not run')", kind="python")


@pytest.mark.asyncio
async def test_preflight_rejects_health_only_runner_without_seccomp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SandboxRunnerClient(SandboxClientConfig("/tmp/unused.sock", 1, 1024))

    async def fake_request(payload: dict, *, timeout: float) -> dict:
        if payload["operation"] == "health":
            return {"version": 1, "status": "ok"}
        return {
            "version": 1,
            "status": "ok",
            "request_id": payload["request_id"],
            "stdout": "socket-open\n",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "truncated": False,
            "isolation": "runner-container",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(RuntimeError, match="execution boundary"):
        await client.preflight()


class HealthyRunner:
    def __init__(self) -> None:
        self.preflights = 0

    async def preflight(self) -> None:
        self.preflights += 1

    async def execute(
        self, content: str, *, kind: str, timeout: float | None = None
    ) -> SandboxResult:
        return SandboxResult("", "", 0, False, False, "runner-container")


def test_authenticated_sandbox_status_is_live_and_metadata_only(tmp_path: Path) -> None:
    runner = HealthyRunner()
    settings = Settings(
        debug=True,
        memory_encryption_enabled=False,
        execution_enabled=True,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'status.db'}",
    )
    app = create_app(settings, sandbox_executor_factory=lambda _config: runner)
    with TestClient(app) as api:
        assert api.get("/api/sandbox/status").status_code == 401
        token = api.post(
            "/api/auth/register", json={"username": "sandbox-user", "password": "secret1"}
        ).json()["access_token"]
        response = api.get("/api/sandbox/status", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "available": True,
        "isolation": "runner-container",
        "kinds": ["python", "shell"],
        "network_access": False,
        "timeout_seconds": settings.execution_timeout_seconds,
        "output_bytes": settings.execution_output_bytes,
        "memory_mb": settings.execution_memory_mb,
        "pids_limit": settings.execution_pids_limit,
        "cpus": settings.execution_cpus,
        "limits_source": "backend-config",
    }
    assert runner.preflights >= 2
    assert "socket" not in response.text and "docker" not in response.text


def test_compose_runner_boundary() -> None:
    compose = yaml.safe_load((Path(__file__).parents[3] / "docker-compose.local.yml").read_text())
    runner = compose["services"]["sandbox-runner"]
    backend = compose["services"]["backend"]
    assert runner["network_mode"] == "none"
    assert runner["read_only"] is True and runner["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in runner["security_opt"]
    assert runner["user"] == "10001:10001"
    assert runner["pids_limit"] == 64 and runner["mem_limit"] == "128m"
    assert not any("docker.sock" in mount or ".:/" in mount for mount in runner["volumes"])
    assert backend["environment"]["ARCHON_EXECUTION_ENABLED"] == "true"
    assert not any("docker.sock" in mount for mount in backend["volumes"])
    main_source = (Path(__file__).parents[2] / "app" / "main.py").read_text()
    assert "DockerSandboxExecutor" not in main_source
    assert "SandboxRunnerClient" in main_source
