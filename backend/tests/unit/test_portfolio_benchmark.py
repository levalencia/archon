"""Unit tests for the reproducible portfolio benchmark CLI and report helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import portfolio_benchmark as benchmark


@pytest.mark.unit
def test_iteration_bounds_and_nearest_rank_latency() -> None:
    assert benchmark._bounded_iterations("1") == 1
    assert benchmark._bounded_iterations("100") == 100
    with pytest.raises(Exception, match="between 1 and 100"):
        benchmark._bounded_iterations("0")
    with pytest.raises(Exception, match="between 1 and 100"):
        benchmark._bounded_iterations("101")
    with pytest.raises(Exception, match="outside the repository"):
        benchmark._external_output_path(str(benchmark._REPO_ROOT / "report.json"))
    assert benchmark._latency_summary([4.0, 1.0, 3.0, 2.0]) == {
        "p50": 2.0,
        "p95": 4.0,
        "max": 4.0,
    }


@pytest.mark.unit
def test_atomic_json_writer_replaces_destination(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    destination.write_text("stale", encoding="utf-8")
    report: dict[str, Any] = {"schema_version": "1.0", "passed": True}

    benchmark._atomic_json_write(destination, report)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.unit
def test_status_summary_does_not_expose_file_names() -> None:
    summary = benchmark._status_summary([" M private-name.txt", "?? secret-path/"])
    assert summary["dirty_entries"] == 2
    assert len(summary["sha256"]) == 64
    assert "private" not in json.dumps(summary)


@pytest.mark.unit
def test_main_returns_nonzero_for_failed_acceptance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def failed(_: int) -> dict[str, Any]:
        return {"summary": {"passed": False}}

    monkeypatch.setattr(benchmark, "run_benchmark", failed)
    output = tmp_path / "failure.json"
    assert benchmark.main(["--output", str(output), "--iterations", "1"]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["passed"] is False
