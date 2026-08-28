"""Static contracts for the sole supported production-like local target."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]


def _compose_config() -> dict:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    env = os.environ | {
        "POSTGRES_PASSWORD": "test-only-random-hex",
        "ARCHON_SECRET_KEY": "test-only-app-key",
        "ARCHON_ENCRYPTION_MASTER_KEY": "MDAxMjM0NTY3ODlhYmNkZWYwMTIzNDU2Nzg5YWJjZGVmMA",
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.local.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_only_loopback_gateway_is_published() -> None:
    services = _compose_config()["services"]
    assert set(services) == {
        "backend",
        "frontend",
        "gateway",
        "postgres",
        "redis",
        "otel-collector",
        "sandbox-runner",
    }
    assert "ports" not in services["postgres"]
    assert "ports" not in services["redis"]
    assert "ports" not in services["backend"]
    assert "ports" not in services["frontend"]
    assert "ports" not in services["sandbox-runner"]
    assert services["gateway"]["ports"][0]["host_ip"] == "127.0.0.1"


def test_compose_requires_secrets_and_uses_safe_local_dependencies() -> None:
    text = (ROOT / "docker-compose.local.yml").read_text()
    assert "${POSTGRES_PASSWORD:?" in text
    assert "${ARCHON_SECRET_KEY:?" in text
    assert "${ARCHON_ENCRYPTION_MASTER_KEY:?" in text
    assert "POSTGRES_PASSWORD: archon" not in text
    assert "dev-secret-change-in-production" not in text
    assert "postgres:16-alpine" in text
    assert "pgvector" not in text.lower()
    assert "ARCHON_RATE_LIMIT_BACKEND: redis" in text
    assert 'ARCHON_EXECUTION_ENABLED: "true"' in text
    assert "ARCHON_EXECUTION_RUNNER_SOCKET" in text
    assert "docker.sock" not in text
    services = _compose_config()["services"]
    assert set(services["sandbox-runner"]["security_opt"]) == {
        "no-new-privileges:true",
        "seccomp=unconfined",
    }
    assert all(
        "seccomp=unconfined" not in service.get("security_opt", [])
        for name, service in services.items()
        if name != "sandbox-runner"
    )
    assert "OTEL_BSP_SCHEDULE_DELAY" in text
    assert "ARCHON_LOCAL_PLATFORM:-linux/amd64" in text
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    assert "docker info --format '{{.Architecture}}'" in smoke
    assert 'aarch64 | arm64) ARCHON_LOCAL_PLATFORM="linux/arm64"' in smoke
    assert 'x86_64 | amd64) ARCHON_LOCAL_PLATFORM="linux/amd64"' in smoke
    assert text.count("@sha256:") >= 4


def test_images_run_nonroot_and_backend_migrates() -> None:
    backend = (ROOT / "Dockerfile").read_text()
    entrypoint = (ROOT / "backend/container-entrypoint.sh").read_text()
    frontend = (ROOT / "frontend/Dockerfile").read_text()
    assert "COPY backend/alembic " in backend
    assert "COPY backend/alembic.ini " in backend
    assert "USER archon" in backend
    assert "uv:latest" not in backend
    assert "--frozen --no-dev" in backend
    assert backend.count("@sha256:") >= 3
    assert "alembic upgrade head" in entrypoint
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    assert '[[ "$migration" == "20260828_14" ]]' in smoke
    assert "USER node" in frontend
    assert frontend.count("@sha256:") == 2
    assert "adapter-node" in (ROOT / "frontend/svelte.config.js").read_text()


def test_real_otel_dependencies_and_span_assertion_are_part_of_the_target() -> None:
    dependencies = (ROOT / "backend/pyproject.toml").read_text()
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    assert "opentelemetry-sdk==" in dependencies
    assert "opentelemetry-exporter-otlp-proto-grpc==" in dependencies
    assert '"agent.run" in text' in smoke
    assert '"archon-local" in text' in smoke


def test_gateway_routes_backend_and_frontend_with_sse_settings() -> None:
    nginx = (ROOT / "deploy/nginx.local.conf").read_text()
    assert "proxy_pass http://backend:8000" in nginx
    assert "proxy_pass http://frontend:3000" in nginx
    for route in ("api", "healthz", "readyz", "metrics"):
        assert route in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_read_timeout 3600s" in nginx
