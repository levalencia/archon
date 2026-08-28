"""Regression tests for the acceptance verification harness."""

from pathlib import Path

ROOT = Path(__file__).parents[3]


def _verify_script() -> str:
    return (ROOT / "scripts" / "verify.sh").read_text()


def test_docker_smoke_uses_ephemeral_validated_memory_key() -> None:
    script = _verify_script()
    smoke = script.partition("== Backend container smoke test ==")[2]

    assert "secrets.token_urlsafe(32)" in smoke
    assert "decode_memory_master_key(key)" in smoke
    assert 'ARCHON_ENCRYPTION_MASTER_KEY="$memory_master_key" docker run' in smoke
    assert "-e ARCHON_MEMORY_ENCRYPTION_ENABLED=true" in smoke
    assert "-e ARCHON_ENCRYPTION_MASTER_KEY" in smoke
    assert "<replace-with-at-least-32-byte-secret>" not in smoke
    assert "unset memory_master_key" in smoke


def test_ci_backend_smoke_supplies_ephemeral_memory_key_without_literal_value() -> None:
    workflow = (Path(__file__).parents[3] / ".github" / "workflows" / "ci.yml").read_text()
    smoke = workflow.partition("- name: Smoke test backend image")[2]

    assert "secrets.token_urlsafe(32)" in smoke
    assert "memory_env_name='ARCHON_ENCRYPTION_MASTER_'\"KEY\"" in smoke
    assert 'export "${memory_env_name}=${memory_material}"' in smoke
    assert "-e ARCHON_MEMORY_ENCRYPTION_ENABLED=true" in smoke
    assert '-e "$memory_env_name"' in smoke
    assert 'unset "$memory_env_name" memory_material' in smoke
    assert "<replace-with-at-least-32-byte-secret>" not in smoke


def test_docker_smoke_uses_configurable_reproducible_platform() -> None:
    script = _verify_script()
    smoke = script.partition("== Backend container smoke test ==")[2]

    assert 'PLATFORM="${ARCHON_VERIFY_PLATFORM:-linux/amd64}"' in script
    assert 'docker build --platform "$PLATFORM"' in smoke
    assert "docker run -d \\" in smoke
    assert '  --platform "$PLATFORM" \\' in smoke


def test_sandbox_smoke_runs_exact_built_image_id() -> None:
    root = ROOT
    build_script = (root / "scripts" / "build-sandbox.sh").read_text()
    verify_script = (root / "scripts" / "verify.sh").read_text()

    assert "Dockerfile.sandbox" in build_script
    assert "docker image inspect --format '{{.Id}}'" in build_script
    assert "^sha256:[0-9a-f]{64}$" in build_script
    assert 'SANDBOX_IMAGE_ID="$("$ROOT/scripts/build-sandbox.sh")"' in verify_script
    assert 'ARCHON_SANDBOX_IMAGE="$SANDBOX_IMAGE_ID"' in verify_script


def test_integrated_gate_orders_offline_acceptance_before_existing_and_benchmark_gates() -> None:
    script = _verify_script()
    headings = [
        "== Clean workspace preflight ==",
        "== Shell script syntax ==",
        "== Acceptance script lint ==",
        "== Acceptance script tests ==",
        "== Capability acceptance manifest ==",
        "== Backend lint ==",
        "== Backend tests ==",
        "== Frontend dependencies ==",
        "== Frontend static checks ==",
        "== Frontend tests ==",
        "== Frontend production build ==",
        "== Frontend browser tests ==",
        "== Docker sandbox containment smoke ==",
        "== Backend container smoke test ==",
        "== Final portfolio benchmark preflight ==",
        "== Clean workspace verification ==",
    ]

    positions = [script.index(heading) for heading in headings]
    assert positions == sorted(positions)
    assert "npm ci" in script
    assert script.index("npm ci") < script.index("npm run check")
    assert "scripts/acceptance_support.py" in script
    assert "scripts/embedding_smoke.py" in script
    assert "scripts/multimodal_smoke.py" in script
    assert "scripts/portfolio_benchmark.py" in script
    assert "scripts/provider_acceptance.py" in script
    assert "../scripts/sandbox_smoke.py" in script
    assert 'bash -n "${SHELL_SCRIPTS[@]}"' in script
    assert "tests/unit/test_provider_acceptance_scripts.py" in script
    assert 'scripts/portfolio_benchmark.py --output "$BENCHMARK_REPORT" --iterations 1' in script
    assert "--execute-live" not in script


def test_integrated_gate_cleans_artifacts_and_has_no_or_true_bypass() -> None:
    script = _verify_script()

    assert 'VERIFY_TMPDIR="$(mktemp -d' in script
    assert 'rm -rf "$VERIFY_TMPDIR"' in script
    assert "local status=$?" in script
    assert "local cleanup_failed=0" in script
    assert 'docker rm -f "$CONTAINER_ID"' in script
    assert 'CONTAINER_ID="$(ARCHON_ENCRYPTION_MASTER_KEY=' in script
    assert "Refusing to remove pre-existing container" in script
    assert 'CONTAINER="${ARCHON_VERIFY_CONTAINER:-archon-backend-verify-$$}"' in script
    assert "status=1" in script
    assert 'exit "$status"' in script
    assert script.count("assert_clean_tree") >= 3  # definition plus preflight and final check
    assert 'git -C "$ROOT" status --porcelain=v1 --untracked-files=all' in script
    assert "|| true" not in script
