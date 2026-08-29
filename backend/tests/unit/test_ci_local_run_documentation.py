from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
GUIDE = ROOT / "docs" / "CI-PIPELINES-AND-LOCAL-RUN.md"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
COMPOSE = ROOT / "docker-compose.local.yml"


def test_ci_guide_matches_workflow_inventory() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    workflow_files = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])

    assert [path.name for path in workflow_files] == ["ci.yml"]
    workflow = yaml.safe_load(workflow_files[0].read_text(encoding="utf-8"))
    jobs = set(workflow["jobs"])

    assert jobs == {"backend-quality", "frontend-quality", "backend-image"}
    assert "GitHub Actions workflow files | 1" in guide
    assert "Jobs in the CI workflow | 3" in guide
    for job in jobs:
        assert f"`{job}`" in guide


def test_ci_guide_matches_compose_and_run_commands() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    services = set(yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"])

    assert services == {
        "gateway",
        "backend",
        "sandbox-runner",
        "frontend",
        "postgres",
        "redis",
        "otel-collector",
    }
    assert "Verified Compose services | 7" in guide
    for service in services:
        assert f"`{service}`" in guide

    required_container_facts = (
        "internal port `8000`",
        "internal port `5432`",
        "internal port `6379`",
        "`4317` (gRPC)",
        "`4318` (HTTP)",
        "internal port `13133`",
        "no Compose healthcheck",
        "`0.5` CPU",
        "`128m` memory",
        "`64` PIDs",
        "two `16m` tmpfs",
        "`/tmp` is `noexec,nosuid,nodev`",
        "`/work` is executable",
        "`no-new-privileges`",
        "OTEL requires only `service_started`",
    )
    for fact in required_container_facts:
        assert fact in guide

    required_commands = (
        "./scripts/verify.sh",
        "./scripts/local-stack.sh start",
        "./scripts/local-stack.sh start --live-provider",
        "./scripts/local-stack.sh status",
        "./scripts/local-stack.sh url",
        "./scripts/local-stack.sh logs otel-collector",
        "./scripts/local-stack.sh stop",
        "./scripts/local-deploy-smoke.sh",
        "KEEP=1 ./scripts/local-deploy-smoke.sh",
        "./scripts/local-dr-smoke.sh /tmp/archon-dr-report.json",
        "uv run python scripts/portfolio_benchmark.py",
        "uv run uvicorn app.main:app",
        "npm run dev",
    )
    for command in required_commands:
        assert command in guide
