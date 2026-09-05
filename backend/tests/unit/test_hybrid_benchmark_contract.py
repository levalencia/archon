"""Contracts for the versioned live Single-vs-Team benchmark."""

from __future__ import annotations

import argparse
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
DATASET = ROOT / "benchmarks/hybrid-orchestration/v1/cases.json"
RUBRIC = ROOT / "benchmarks/hybrid-orchestration/v1/rubric.json"
SCRIPT = ROOT / "scripts/run-hybrid-benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_hybrid_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_dataset_has_exact_stratified_shape_and_unique_ids() -> None:
    payload = harness.load_dataset(DATASET)
    cases = payload["cases"]

    assert len(cases) == 100
    assert len({item["id"] for item in cases}) == 100
    assert sum(item["calibration"] for item in cases) == 20
    assert {item["difficulty"] for item in cases} == {"easy", "medium", "hard"}
    assert {item["tools_profile"] for item in cases} == {"none", "search_only"}

    categories = {item["category"] for item in cases}
    assert len(categories) == 10
    for category in categories:
        selected = [item for item in cases if item["category"] == category]
        assert len(selected) == 10
        assert [
            sum(item["difficulty"] == value for item in selected)
            for value in ("easy", "medium", "hard")
        ] == [4, 3, 3]
        assert sum(item["calibration"] for item in selected) == 2


def test_dataset_prompts_are_bounded_and_tool_profiles_match_contract() -> None:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))["cases"]

    for item in cases:
        assert 1 <= len(item["prompt"]) <= 10_000
        assert 3 <= len(item["expected_traits"]) <= 10
        assert item["trait_scoring"] == "normalized_equal_weight"
        if item["tools_profile"] == "none":
            assert item["tools_allowed"] == []
            assert "Do not use tools" in item["prompt"]
        else:
            assert item["tools_allowed"] == ["web_search"]
            assert "Use web_search only" in item["prompt"]


def test_rubric_has_cost_stop_routing_and_specialist_gates() -> None:
    payload = json.loads(RUBRIC.read_text(encoding="utf-8"))

    assert payload["primary_quality_rubric"]["maximum"] == 10
    assert len(payload["primary_quality_rubric"]["dimensions"]) == 5
    assert payload["global_stop_conditions"]["authorized_cost_cap_usd"] == 60
    assert payload["calibration_gate"]["cases"] == 20
    assert (
        payload["routing_decision_rules"]["team_positive_category"][
            "minimum_win_rate_excluding_ties"
        ]
        == 0.6
    )
    assert payload["specialist_decision_rules"]["prototype_only_after_cluster_review"] is True


def test_raw_output_must_be_external_and_checkpoint_cost_is_additive(tmp_path: Path) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        harness.external_output(str(ROOT / "raw-results.json"))

    output = harness.external_output(str(tmp_path / "raw-results.json"))
    assert output == (tmp_path / "raw-results.json").resolve()
    assert harness.cumulative_cost(
        {"results": [{"cost_usd": "0.25"}, {"cost_usd": "0.75"}]}
    ) == Decimal("1.00")


def test_phase_selection_is_disjoint_and_complete() -> None:
    payload = harness.load_dataset(DATASET)
    calibration = harness.selected_cases(payload, "calibration")
    remainder = harness.selected_cases(payload, "remainder")

    assert len(calibration) == 20
    assert len(remainder) == 80
    assert {item["id"] for item in calibration}.isdisjoint({item["id"] for item in remainder})
    assert len(harness.selected_cases(payload, "all")) == 100


def test_resume_never_retries_recorded_failed_attempts() -> None:
    payload = {
        "results": [
            {"case_id": "fact-001", "mode": "single", "http_status": 0},
            {"case_id": "fact-001", "mode": "team", "http_status": 200},
        ]
    }

    assert harness.completed_keys(payload) == {
        ("fact-001", "single"),
        ("fact-001", "team"),
    }


def test_functional_gate_rejects_tools_outside_case_contract() -> None:
    item = {
        "http_status": 200,
        "resolved_mode": "single",
        "mode": "single",
        "degraded": False,
        "allowed_tools": [],
        "actual_tool_calls": [{"name": "web_search"}],
    }

    assert harness.functional_failure(item) == "tool_contract_violation"
