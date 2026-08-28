#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.local.yml")

cleanup() {
  if [[ "${KEEP:-0}" != "1" ]]; then
    "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

"${COMPOSE[@]}" up -d --build sandbox-runner backend
CID="$("${COMPOSE[@]}" ps -q sandbox-runner)"
test -n "$CID"

inspect="$(docker inspect "$CID")"
python3 - "$inspect" <<'PY'
import json, sys
c = json.loads(sys.argv[1])[0]
h = c["HostConfig"]
assert h["NetworkMode"] == "none"
assert h["ReadonlyRootfs"] is True
assert h["Init"] is True
assert h["CapDrop"] == ["ALL"]
assert h["PidsLimit"] == 64
assert h["Memory"] == 128 * 1024 * 1024
assert any(value.startswith("no-new-privileges") for value in h["SecurityOpt"])
assert all("docker.sock" not in m["Source"] for m in c.get("Mounts", []))
PY

"${COMPOSE[@]}" exec -T backend python - <<'PY'
import asyncio
from app.tools.sandbox_client import SandboxClientConfig, SandboxRunnerClient

async def main():
    client = SandboxRunnerClient(SandboxClientConfig('/run/archon-sandbox/runner.sock', 2, 65536))
    await client.preflight()
    ok = await client.execute("print('sandbox-runner-ok')", kind='python')
    assert ok.stdout.strip() == 'sandbox-runner-ok'
    network = await client.execute(
        "import socket\n"
        "try:\n s=socket.socket();s.settimeout(.3);s.connect(('1.1.1.1',53));"
        "raise SystemExit('network reachable')\n"
        "except OSError:print('network-isolated')", kind='python')
    assert network.stdout.strip() == 'network-isolated'
    reentry = await client.execute(
        "import socket\n"
        "try:s=socket.socket(socket.AF_UNIX);s.connect('/run/archon-sandbox/runner.sock');"
        "raise SystemExit('control socket reachable')\n"
        "except OSError:print('control-socket-blocked')", kind='python')
    assert reentry.stdout.strip() == 'control-socket-blocked'
    detached = await client.execute(
        "sleep 30 </dev/null >/dev/null 2>&1 & echo $!", kind='shell')
    child_pid = int(detached.stdout.strip())
    orphan = await client.execute(
        f"import os,time\n"
        f"p='/proc/{child_pid}'\n"
        "for _ in range(25):\n"
        " if not os.path.exists(p):break\n"
        " time.sleep(.02)\n"
        "print(os.path.exists(p))", kind='python')
    assert orphan.stdout.strip() == 'False'
    timeout = await client.execute("import time;time.sleep(30)", kind='python', timeout=.2)
    assert timeout.timed_out
    capped = await client.execute("print('x'*100000)", kind='python')
    assert capped.truncated and len(capped.stdout.encode()) + len(capped.stderr.encode()) <= 65536
    large = SandboxRunnerClient(
        SandboxClientConfig('/run/archon-sandbox/runner.sock', 2, 1048576))
    escaped = await large.execute(
        "import sys;sys.stdout.buffer.write(b'\\0'*1048576)", kind='python')
    assert escaped.truncated
    assert len(escaped.stdout.encode()) + len(escaped.stderr.encode()) <= 1048576

asyncio.run(main())
PY
printf 'Sandbox runner Compose smoke passed\n'
