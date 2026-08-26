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
    assert report["summary"]["passed"] is True
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["failures"] == []
    assert report["summary"]["scenario_iterations"] == 6
    assert report["summary"]["tokens"] == 84

    scenarios: list[dict[str, Any]] = report["scenarios"]
    assert [item["id"] for item in scenarios] == [
        "unsafe_write_approval",
        "provider_resilience",
        "grounded_document_workflow",
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

    encoded = json.dumps(report, sort_keys=True)
    for forbidden in (
        "run the registered benchmark probe",
        "What technology does Alpha use?",
        "Return JSON only",
        "private-provider-detail-must-not-appear",
        "private-breaker-detail-must-not-appear",
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
