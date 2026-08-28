"""Integration acceptance test for the production-component portfolio benchmark."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.portfolio_benchmark import BENCHMARK_KIND, SCHEMA_VERSION, run_benchmark


@pytest.mark.integration
@pytest.mark.asyncio
async def test_portfolio_report_schema_determinism_invariants_and_privacy() -> None:
    report = await run_benchmark(2)

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["benchmark_kind"] == BENCHMARK_KIND
    assert report["configuration"] == {
        "iterations": 2,
        "external_network": False,
        "external_model": False,
        "estimated_cost_usd": 0,
    }
    assert report["claim_scope"] == (
        "deterministic mock/control-plane; no production or model-quality claim"
    )
    assert report["workspace"]["workspace_unchanged"] is True
    assert report["workspace"]["clean_before"] is True
    assert report["workspace"]["clean_after"] is True
    assert report["summary"]["passed"] is True
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["failures"] == []
    assert report["summary"]["scenario_iterations"] == 24
    assert report["summary"]["tokens"] > 84

    scenarios: list[dict[str, Any]] = report["scenarios"]
    assert [item["id"] for item in scenarios] == [
        "unsafe_write_approval",
        "provider_resilience",
        "grounded_document_workflow",
        "reflection_disabled_vs_enabled",
        "duplicate_side_effect_replay",
        "budget_reservation_provider_failure",
        "context_provenance_key_rotation_interruption",
        "share_grant_revoke_expiry_redaction",
        "signed_child_envelope_replay",
        "durable_job_restart_lease_loss",
        "sandbox_breakout_probes",
        "drift_candidate_exact_approval",
    ]
    for scenario in scenarios:
        assert scenario["passed"] is True
        assert scenario["pass_rate"] == 1.0
        assert scenario["passed_iterations"] == 2
        assert scenario["failures"] == []
        assert scenario["observations_stable"] is True
        assert all(scenario["invariants"].values())
        assert set(scenario["latency_ms"]) == {"p50", "p95", "max"}
        assert 0 <= scenario["latency_ms"]["p50"] <= scenario["latency_ms"]["p95"]
        assert scenario["latency_ms"]["p95"] <= scenario["latency_ms"]["max"]

    by_id = {item["id"]: item for item in scenarios}
    assert (
        by_id["budget_reservation_provider_failure"]["observation"]["provider_failure_propagated"]
        is True
    )
    assert by_id["share_grant_revoke_expiry_redaction"]["observation"]["disclosure_redactions"] > 0
    assert by_id["drift_candidate_exact_approval"]["observation"]["drift_report_bound"] is True
    assert by_id["drift_candidate_exact_approval"]["observation"]["drift_pass_rate_delta"] == -1.0
    sandbox = by_id["sandbox_breakout_probes"]["observation"]
    assert sandbox["missing_runner_failed_closed"] is True
    if sys.platform == "linux":
        assert sandbox["seccomp_probe_executed"] is True
        assert sandbox["socket_blocked"] is True
        assert sandbox["control_unlink_blocked"] is True
        assert sandbox["volume_write_blocked"] is True
        assert sandbox["control_chmod_blocked"] is True

    encoded = json.dumps(report, sort_keys=True)
    for forbidden in (
        "run the registered benchmark probe",
        "What technology does Alpha use?",
        "Return JSON only",
        "private-provider-detail-must-not-appear",
        "private-breaker-detail-must-not-appear",
        "raw-provider-secret",
        "benchmark-sensitive-token-123456",
        "private input",
        "historical private value",
        "current private value",
    ):
        assert forbidden not in encoded
    assert "git_status_porcelain" not in encoded
    assert report["workspace"]["before"]["sha256"] == report["workspace"]["after"]["sha256"]


@pytest.mark.integration
def test_benchmark_executes_via_documented_script_path(tmp_path: Path) -> None:
    backend = Path(__file__).parents[2]
    output = tmp_path / "cli-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(backend / "scripts/portfolio_benchmark.py"),
            "--output",
            str(output),
            "--iterations",
            "1",
        ],
        cwd=backend,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] is True
    assert report["workspace"]["workspace_unchanged"] is True
