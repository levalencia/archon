"""Static contracts for the sole supported production-like local target."""

from __future__ import annotations

import hashlib
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
        "ARCHON_EFFECT_IDENTITY_SECRET": "test-only-effect-identity-secret-that-is-long-enough",
        "ARCHON_DELEGATION_SIGNING_KEY": "test-only-delegation-signing-key-that-is-long-enough",
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
    assert "ARCHON_LLM_PROVIDER: ${ARCHON_LLM_PROVIDER:-mock}" in text
    assert "ARCHON_LLM_MODEL: ${ARCHON_LLM_MODEL:-mock-model}" in text
    assert "ARCHON_LLM_API_KEY: ${ARCHON_LLM_API_KEY:-}" in text
    assert "ARCHON_LLM_BASE_URL: ${ARCHON_LLM_BASE_URL:-}" in text
    assert 'ARCHON_DURABLE_MONETARY_BUDGET_ENABLED: "true"' in text
    assert 'ARCHON_DURABLE_EFFECT_LEDGER_ENABLED: "true"' in text
    assert "${ARCHON_EFFECT_IDENTITY_SECRET:?" in text
    assert "${ARCHON_DELEGATION_SIGNING_KEY:?" in text
    assert "ARCHON_VERIFIER_ENABLED: ${ARCHON_VERIFIER_ENABLED:-false}" in text
    assert "ARCHON_AGENT_DEADLINE_SECONDS: ${ARCHON_AGENT_DEADLINE_SECONDS:-90}" in text
    assert "ARCHON_EMBEDDING_PROVIDER: ${ARCHON_EMBEDDING_PROVIDER:-mock}" in text
    assert "ARCHON_EMBEDDING_MODEL: ${ARCHON_EMBEDDING_MODEL:-mock-embedding}" in text
    assert "ARCHON_EMBEDDING_API_KEY: ${ARCHON_EMBEDDING_API_KEY:-}" in text
    assert 'ARCHON_EXECUTION_ENABLED: "true"' in text
    assert "ARCHON_EXECUTION_RUNNER_SOCKET" in text
    assert "docker.sock" not in text
    services = _compose_config()["services"]
    security_options = set(services["sandbox-runner"]["security_opt"])
    assert "no-new-privileges:true" in security_options
    seccomp_options = [option for option in security_options if option.startswith("seccomp=")]
    assert len(seccomp_options) == 1
    assert seccomp_options[0].endswith("/sandbox_runner/seccomp-bootstrap.json")
    assert all(
        "seccomp=unconfined" not in service.get("security_opt", [])
        for name, service in services.items()
        if name != "sandbox-runner"
    )
    profile_path = ROOT / "sandbox_runner" / "seccomp-bootstrap.json"
    profile_bytes = profile_path.read_bytes()
    assert hashlib.sha256(profile_bytes).hexdigest() == (
        "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74"
    )
    profile = json.loads(profile_bytes)
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    unconditional = {
        syscall
        for rule in profile["syscalls"]
        if rule["action"] == "SCMP_ACT_ALLOW"
        and not rule.get("includes")
        and not rule.get("excludes")
        for syscall in rule["names"]
    }
    assert "seccomp" in unconditional
    assert not {"clone3", "unshare", "bpf", "keyctl", "perf_event_open"} & unconditional
    assert "OTEL_BSP_SCHEDULE_DELAY" in text
    assert "ARCHON_LOCAL_PLATFORM:-linux/amd64" in text
    assert "ARCHON_SANDBOX_PLATFORM:-linux/amd64" in text
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    assert "docker info --format '{{.Architecture}}'" in smoke
    assert 'aarch64 | arm64) ARCHON_SANDBOX_PLATFORM="linux/arm64"' in smoke
    assert 'x86_64 | amd64) ARCHON_SANDBOX_PLATFORM="linux/amd64"' in smoke
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
    assert "app.acceptance.control_plane" in smoke
    assert 'durable_monetary_budget"] == "enabled"' in smoke
    assert 'durable_effect_ledger"] == "enabled"' in smoke
    assert "USER node" in frontend
    assert frontend.count("@sha256:") == 2
    assert "adapter-node" in (ROOT / "frontend/svelte.config.js").read_text()


def test_real_otel_dependencies_and_span_assertion_are_part_of_the_target() -> None:
    dependencies = (ROOT / "backend/pyproject.toml").read_text()
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    assert "opentelemetry-sdk==" in dependencies
    assert "opentelemetry-exporter-otlp-proto-grpc==" in dependencies
    assert "otel_before=" in smoke
    assert "otel_after=" in smoke
    assert '"\\tTraces\\t" in line and "resource spans" in line' in smoke
    assert "otel_after > otel_before" in smoke
    assert "newly exported OTEL trace batch" in smoke


def test_local_stack_wrapper_preserves_exact_generated_runtime_context() -> None:
    smoke = (ROOT / "scripts/local-deploy-smoke.sh").read_text()
    wrapper = (ROOT / "scripts/local-stack.sh").read_text()
    generator = (ROOT / "scripts/generate-local-env.py").read_text()

    assert "STATE_FILE=${ARCHON_RUNTIME_STATE_FILE:-}" in smoke
    assert "ARCHON_COMPOSE_PROJECT" in smoke
    assert "ARCHON_COMPOSE_ENV_FILE" in smoke
    assert "ARCHON_BASE_URL" in smoke
    assert "ARCHON_RUNTIME_MODE" in smoke
    assert "generate-local-env.py" in smoke
    assert "ARCHON_PROVIDER_ENV_FILE" in smoke
    assert '"ARCHON_LLM_PROVIDER"' in generator
    assert '"ARCHON_LLM_MODEL"' in generator
    assert '"ARCHON_LLM_API_KEY"' in generator
    assert '"ARCHON_LLM_BASE_URL"' in generator
    assert "provider env must not be group/world accessible" in generator
    assert "managed live mode currently requires ARCHON_LLM_PROVIDER=foundry" in generator
    assert "managed Foundry endpoint must be an absolute HTTPS URL" in generator
    assert 'state_tmp=$(mktemp "${STATE_FILE}.XXXXXX")' in smoke
    assert 'mv -f "$state_tmp" "$STATE_FILE"' in smoke
    assert '"${KEEP:-0}" == "1" && "$status" == "0"' in smoke
    assert "KEEP_FAILED=1" in smoke

    for command in ("start)", "status)", "url)", "logs)", "stop)"):
        assert command in wrapper
    assert "local-deploy-smoke.sh" in wrapper
    assert "start [--live-provider]" in wrapper
    assert "requested_mode=live-foundry" in wrapper
    assert "provider_env=${ARCHON_PROVIDER_ENV_FILE:-$ROOT/backend/.env}" in wrapper
    assert "Stop explicitly before changing provider mode" in wrapper
    assert 'ARCHON_PROVIDER_ENV_FILE="$provider_env"' in wrapper
    assert "RUNTIME_MODE=%s" in wrapper
    assert '--env-file "$ARCHON_COMPOSE_ENV_FILE"' in wrapper
    assert '-p "$ARCHON_COMPOSE_PROJECT"' in wrapper
    assert 'chmod 600 "$STATE_FILE"' in wrapper
    assert 'chmod 600 "$ARCHON_COMPOSE_ENV_FILE"' in wrapper
    assert 'LOCK_FILE="$STATE_DIR/start.lock"' in wrapper
    assert "ARCHON_START_LOCK_HELD:-0" in wrapper
    assert 'exec lockf -t 0 "$LOCK_FILE"' in wrapper
    assert 'exec flock -n "$LOCK_FILE"' in wrapper
    assert "Legacy lock directory detected" in wrapper
    assert "No supported advisory lock primitive found" in wrapper
    assert "LOCK_DIR" not in wrapper
    assert "release_start_lock" not in wrapper
    assert "kill -0" not in wrapper
    assert "preserving env and state for retry" in wrapper
    assert "Managed runtime state exists but cannot be used" in wrapper
    assert '"$ARCHON_BASE_URL/healthz"' in wrapper
    assert '"$ARCHON_BASE_URL/readyz"' in wrapper
    assert "already running, healthy, and ready" in wrapper
    assert "Managed Archon stack exists but health or readiness is failing" in wrapper
    assert "Preserving containers, volumes, env, and state" in wrapper
    assert "stop explicitly before a new start" in wrapper
    assert "label=com.docker.compose.project=$ARCHON_COMPOSE_PROJECT" in wrapper
    assert "reading logs through exact Compose project labels" in wrapper
    assert "removing only resources labeled for project" in wrapper
    assert "Removing stale managed stack before restart" not in wrapper
    assert "stop_loaded_stack || true" not in wrapper
    assert "backend/.env" in wrapper
    assert "dummy secret" in wrapper
    assert "ARCHON_SECRET_KEY=x" not in wrapper
    assert "ARCHON_ENCRYPTION_MASTER_KEY=x" not in wrapper
    assert "POSTGRES_PASSWORD=x" not in wrapper


def test_gateway_routes_backend_and_frontend_with_sse_settings() -> None:
    nginx = (ROOT / "deploy/nginx.local.conf").read_text()
    assert "proxy_pass http://backend:8000" in nginx
    assert "proxy_pass http://frontend:3000" in nginx
    for route in ("api", "healthz", "readyz", "metrics"):
        assert route in nginx
    assert "proxy_buffering off" in nginx
    assert "proxy_read_timeout 3600s" in nginx
