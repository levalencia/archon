"""Required real-Docker containment acceptance smoke (not a pytest skip)."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.tools.sandbox import DockerSandboxConfig, DockerSandboxExecutor  # noqa: E402

SANDBOX_LABEL: Final = "com.archon.sandbox=true"
DOCKER: Final = (
    shutil.which("docker", path="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin") or "docker"
)


async def sandbox_container_ids() -> set[str]:
    """Return all running or stopped containers identifiable as Archon sandboxes."""
    identifiers: set[str] = set()
    for filter_value in ("name=archon-sandbox-", f"label={SANDBOX_LABEL}"):
        check = await asyncio.create_subprocess_exec(
            DOCKER,
            "ps",
            "-aq",
            "--filter",
            filter_value,
            stdout=asyncio.subprocess.PIPE,
        )
        output, _ = await check.communicate()
        assert check.returncode == 0, "could not inspect Docker sandbox cleanup"
        identifiers.update(output.decode().split())
    return identifiers


async def assert_sandboxes_removed() -> None:
    """Allow Docker's --rm briefly, then require both name and label cleanup."""
    identifiers: set[str] = set()
    for _ in range(50):
        identifiers = await sandbox_container_ids()
        if not identifiers:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"sandbox containers remained after cleanup: {sorted(identifiers)}")


async def main() -> None:
    assert not await sandbox_container_ids(), "pre-existing Archon sandbox containers found"
    executor = DockerSandboxExecutor(
        DockerSandboxConfig(
            binary=DOCKER,
            image=os.environ.get("ARCHON_SANDBOX_IMAGE", "archon-sandbox:local"),
            platform=os.environ.get("ARCHON_VERIFY_PLATFORM", "linux/amd64"),
            timeout_seconds=2,
            cpus=0.5,
            memory_mb=128,
            pids_limit=32,
            output_bytes=65536,
        )
    )
    await executor.preflight()
    success = await executor.execute("print('sandbox-ok')", kind="python")
    assert success.exit_code == 0 and success.stdout.strip() == "sandbox-ok"
    shell = await executor.execute("printf terminal-ok", kind="shell")
    assert shell.exit_code == 0 and shell.stdout == "terminal-ok"

    with tempfile.NamedTemporaryFile(prefix="archon-host-sentinel-", delete=False) as sentinel:
        sentinel.write(b"host-secret")
        sentinel_path = sentinel.name
    try:
        fs = await executor.execute(
            (
                f"from pathlib import Path\nassert not Path({sentinel_path!r}).exists()\n"
                "print('fs-isolated')"
            ),
            kind="python",
        )
        assert fs.exit_code == 0 and "fs-isolated" in fs.stdout
    finally:
        Path(sentinel_path).unlink(missing_ok=True)

    os.environ["ARCHON_HOST_SENTINEL"] = "must-not-cross"
    env = await executor.execute(
        "import os\nassert 'ARCHON_HOST_SENTINEL' not in os.environ\nprint('env-isolated')",
        kind="python",
    )
    assert env.exit_code == 0 and "env-isolated" in env.stdout

    network = await executor.execute(
        "import socket\ns=socket.socket(); s.settimeout(.5)\n"
        "try: s.connect(('1.1.1.1', 53)); raise SystemExit('network reachable')\n"
        "except OSError: print('network-isolated')",
        kind="python",
    )
    assert network.exit_code == 0 and "network-isolated" in network.stdout

    timeout = await executor.execute("import time; time.sleep(30)", kind="python", timeout=0.3)
    assert timeout.timed_out
    await assert_sandboxes_removed()

    capped = await executor.execute(
        "import sys\nwhile True: sys.stdout.write('x' * 8192); sys.stdout.flush()",
        kind="python",
    )
    assert capped.truncated
    assert len(capped.stdout.encode()) + len(capped.stderr.encode()) <= 65536
    await assert_sandboxes_removed()

    cancelled = asyncio.create_task(executor.execute("import time; time.sleep(30)", kind="python"))
    for _ in range(50):
        if await sandbox_container_ids():
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("cancellation sandbox never started")
    cancelled.cancel()
    try:
        await cancelled
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("sandbox execution did not propagate cancellation")
    await assert_sandboxes_removed()

    print("Docker sandbox containment smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
