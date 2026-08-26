"""Regression tests for the acceptance verification harness."""

from pathlib import Path


def test_docker_smoke_uses_ephemeral_validated_memory_key() -> None:
    script = (Path(__file__).parents[3] / "scripts" / "verify.sh").read_text()
    smoke = script.partition("== Backend container smoke test ==")[2]

    assert "secrets.token_urlsafe(32)" in smoke
    assert "decode_memory_master_key(key)" in smoke
    assert 'ARCHON_ENCRYPTION_MASTER_KEY="$memory_master_key" docker run' in smoke
    assert "-e ARCHON_MEMORY_ENCRYPTION_ENABLED=true" in smoke
    assert "-e ARCHON_ENCRYPTION_MASTER_KEY" in smoke
    assert "<replace-with-at-least-32-byte-secret>" not in smoke
    assert "unset memory_master_key" in smoke


def test_docker_smoke_uses_configurable_reproducible_platform() -> None:
    script = (Path(__file__).parents[3] / "scripts" / "verify.sh").read_text()
    smoke = script.partition("== Backend container smoke test ==")[2]

    assert 'PLATFORM="${ARCHON_VERIFY_PLATFORM:-linux/amd64}"' in script
    assert 'docker build --platform "$PLATFORM"' in smoke
    assert "docker run -d \\" in smoke
    assert '  --platform "$PLATFORM" \\' in smoke


def test_sandbox_smoke_runs_exact_built_image_id() -> None:
    root = Path(__file__).parents[3]
    build_script = (root / "scripts" / "build-sandbox.sh").read_text()
    verify_script = (root / "scripts" / "verify.sh").read_text()

    assert "Dockerfile.sandbox" in build_script
    assert "docker image inspect --format '{{.Id}}'" in build_script
    assert "^sha256:[0-9a-f]{64}$" in build_script
    assert 'SANDBOX_IMAGE_ID="$("$ROOT/scripts/build-sandbox.sh")"' in verify_script
    assert 'ARCHON_SANDBOX_IMAGE="$SANDBOX_IMAGE_ID"' in verify_script
