"""Small, fail-closed Unix socket daemon for sandbox execution."""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.util
import errno
import json
import os
import re
import resource
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

SOCKET_PATH = Path(os.environ.get("SANDBOX_SOCKET_PATH", "/run/archon-sandbox/runner.sock"))
WORK_DIR = Path(os.environ.get("SANDBOX_WORK_DIR", "/work"))
MAX_FRAME_BYTES = 1_100_000
MAX_INPUT_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 1_048_576
MAX_TIMEOUT_SECONDS = 120.0
COMMANDS = {"python": ("python", "-I", "-"), "shell": ("sh", "-s")}
SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8"}
EXECUTION_ACTIVE = False
_EXECUTE_KEYS = {
    "version",
    "operation",
    "request_id",
    "kind",
    "content",
    "timeout_seconds",
    "output_bytes",
}
_HEALTH_KEYS = {"version", "operation"}
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_SECCOMP_PATH = ctypes.util.find_library("seccomp") if sys.platform == "linux" else None
_SECCOMP = ctypes.CDLL(_SECCOMP_PATH, use_errno=True) if _SECCOMP_PATH else None
_SECCOMP_DENIED = (
    "socket",
    "socketpair",
    "connect",
    "bind",
    "listen",
    "accept",
    "accept4",
    "ptrace",
    "process_vm_readv",
    "process_vm_writev",
    "kill",
    "tkill",
    "tgkill",
    "pidfd_send_signal",
    "setsid",
    "setpgid",
    "unlink",
    "unlinkat",
    "rename",
    "renameat",
    "renameat2",
    "chmod",
    "fchmod",
    "fchmodat",
    "fchmodat2",
)


def _install_seccomp() -> None:
    if sys.platform != "linux":
        return
    if _SECCOMP is None:
        raise RuntimeError("seccomp_unavailable")
    seccomp = _SECCOMP
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    seccomp.seccomp_rule_add.restype = ctypes.c_int
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_syscall_resolve_name.restype = ctypes.c_int
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_load.restype = ctypes.c_int
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    context = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("seccomp_init_failed")
    try:
        deny = 0x00050000 | errno.EPERM  # SCMP_ACT_ERRNO(EPERM)
        for name in _SECCOMP_DENIED:
            syscall = seccomp.seccomp_syscall_resolve_name(name.encode())
            if syscall >= 0 and seccomp.seccomp_rule_add(context, deny, syscall, 0) != 0:
                raise RuntimeError("seccomp_rule_failed")
        if seccomp.seccomp_load(context) != 0:
            raise RuntimeError("seccomp_load_failed")
    finally:
        seccomp.seccomp_release(context)


def _limits() -> None:
    """Defense in depth beneath container CPU/memory/PID limits."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (121, 121))
    _install_seccomp()


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    request_id = request.get("request_id")
    if (
        set(request) != _EXECUTE_KEYS
        or type(request_id) is not str
        or not _REQUEST_ID.fullmatch(request_id)
    ):
        return _error("invalid_request", "")
    kind = request.get("kind")
    content = request.get("content")
    timeout = request.get("timeout_seconds")
    output_limit = request.get("output_bytes")
    timeout_value = float(cast(int | float, timeout)) if type(timeout) in (int, float) else -1.0
    if (
        type(kind) is not str
        or kind not in COMMANDS
        or type(content) is not str
        or len(content.encode("utf-8")) > MAX_INPUT_BYTES
        or not 0.1 <= timeout_value <= MAX_TIMEOUT_SECONDS
        or type(output_limit) is not int
        or not 1024 <= output_limit <= MAX_OUTPUT_BYTES
    ):
        return _error("invalid_request", request_id)

    proc = await asyncio.create_subprocess_exec(
        *COMMANDS[kind],
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORK_DIR,
        env=SAFE_ENV,
        start_new_session=True,
        preexec_fn=_limits,
    )
    assert proc.stdin and proc.stdout and proc.stderr
    stdout = bytearray()
    stderr = bytearray()
    cap = asyncio.Event()
    truncated = False

    async def read(stream: asyncio.StreamReader, destination: bytearray) -> None:
        nonlocal truncated
        while chunk := await stream.read(8192):
            remaining = output_limit - len(stdout) - len(stderr)
            if remaining <= 0:
                truncated = True
                cap.set()
                return
            destination.extend(chunk[:remaining])
            if len(chunk) > remaining or len(stdout) + len(stderr) >= output_limit:
                truncated = True
                cap.set()
                return

    readers = [
        asyncio.create_task(read(proc.stdout, stdout)),
        asyncio.create_task(read(proc.stderr, stderr)),
    ]
    wait = asyncio.create_task(proc.wait())
    cap_wait = asyncio.create_task(cap.wait())
    timed_out = False
    try:
        async with asyncio.timeout(timeout_value):
            proc.stdin.write(content.encode())
            await proc.stdin.drain()
            proc.stdin.close()
            done, _ = await asyncio.wait((wait, cap_wait), return_when=asyncio.FIRST_COMPLETED)
            if cap_wait in done and not wait.done():
                _kill_group(proc)
            await wait
            await asyncio.gather(*readers)
    except TimeoutError:
        timed_out = True
        _kill_group(proc)
        with suppress(Exception):
            await asyncio.wait_for(wait, 1.0)
    except asyncio.CancelledError:
        _kill_group(proc)
        with suppress(Exception):
            await asyncio.wait_for(wait, 1.0)
        raise
    finally:
        _kill_group(proc)
        for task in (*readers, wait, cap_wait):
            if not task.done():
                task.cancel()
        await asyncio.gather(*readers, wait, cap_wait, return_exceptions=True)

    return {
        "version": 1,
        "status": "ok",
        "request_id": request_id,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "exit_code": proc.returncode if proc.returncode is not None else 137,
        "timed_out": timed_out,
        "truncated": truncated,
        "isolation": "runner-container",
    }


def _kill_group(proc: asyncio.subprocess.Process) -> None:
    # The leader may already have exited while background descendants still own the group.
    with suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _error(code: str, request_id: str) -> dict[str, Any]:
    return {"version": 1, "status": "error", "request_id": request_id, "error": code}


def _json_frame(response: dict[str, Any]) -> bytes:
    return json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"


def _encode_response(response: dict[str, Any]) -> bytes:
    frame = _json_frame(response)
    if len(frame) <= MAX_FRAME_BYTES:
        return frame
    if response.get("status") != "ok":
        return _json_frame(_error("response_too_large", ""))

    stdout = response.get("stdout")
    stderr = response.get("stderr")
    if type(stdout) is not str or type(stderr) is not str:
        return _json_frame(_error("response_too_large", ""))
    low, high = 0, len(stdout) + len(stderr)
    best_frame = _json_frame({**response, "stdout": "", "stderr": "", "truncated": True})
    while low <= high:
        keep = (low + high) // 2
        stdout_keep = min(len(stdout), keep)
        stderr_keep = max(0, keep - stdout_keep)
        candidate = {
            **response,
            "stdout": stdout[:stdout_keep],
            "stderr": stderr[:stderr_keep],
            "truncated": True,
        }
        candidate_frame = _json_frame(candidate)
        if len(candidate_frame) <= MAX_FRAME_BYTES:
            best_frame = candidate_frame
            low = keep + 1
        else:
            high = keep - 1
    return best_frame


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global EXECUTION_ACTIVE
    response: dict[str, Any]
    try:
        async with asyncio.timeout(2.0):
            line = await reader.readline()
        if not line or len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
            response = _error("invalid_frame", "")
        else:
            request = json.loads(line)
            if type(request) is not dict or request.get("version") != 1:
                response = _error("invalid_request", "")
            elif request.get("operation") == "health":
                response = (
                    {"version": 1, "status": "ok"}
                    if set(request) == _HEALTH_KEYS
                    else _error("invalid_request", "")
                )
            elif request.get("operation") == "execute":
                request_id = request.get("request_id")
                safe_id = (
                    request_id
                    if type(request_id) is str and _REQUEST_ID.fullmatch(request_id)
                    else ""
                )
                if EXECUTION_ACTIVE:
                    response = _error("runner_busy", safe_id)
                else:
                    EXECUTION_ACTIVE = True
                    execution = asyncio.create_task(execute(request))
                    peer = asyncio.create_task(reader.read(1))
                    try:
                        done, _ = await asyncio.wait(
                            (execution, peer), return_when=asyncio.FIRST_COMPLETED
                        )
                        if execution in done:
                            response = execution.result()
                        else:
                            execution.cancel()
                            await asyncio.gather(execution, return_exceptions=True)
                            response = _error("client_disconnected", safe_id)
                    finally:
                        if not execution.done():
                            execution.cancel()
                        if not peer.done():
                            peer.cancel()
                        await asyncio.gather(execution, peer, return_exceptions=True)
                        EXECUTION_ACTIVE = False
            else:
                response = _error("unsupported_operation", "")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TimeoutError):
        response = _error("invalid_frame", "")
    except Exception:
        # Never include exception, command content, environment, or process output in metadata.
        response = _error("execution_failed", "")
    with suppress(ConnectionError, BrokenPipeError):
        writer.write(_encode_response(response))
        await writer.drain()
    writer.close()
    with suppress(ConnectionError):
        await writer.wait_closed()


async def main() -> None:
    SOCKET_PATH.parent.mkdir(mode=0o770, parents=True, exist_ok=True)
    os.chmod(SOCKET_PATH.parent, 0o770)
    SOCKET_PATH.unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle, path=SOCKET_PATH, limit=MAX_FRAME_BYTES + 1)
    os.chmod(SOCKET_PATH, 0o660)
    os.chmod(SOCKET_PATH.parent, 0o550)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
