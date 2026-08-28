"""Pinned deterministic evidence for measured reflection benefit."""

from pathlib import Path

import pytest

from app.reflection.measurement import (
    ReflectionFixtureError,
    load_reflection_benchmark_fixture,
    measure_reflection_benefit,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "evals" / "reflection-benefit-v1.json"


@pytest.mark.integration
class TestReflectionBenefit:
    def test_reports_only_observed_baseline_vs_reflected_delta(self) -> None:
        fixture = load_reflection_benchmark_fixture(FIXTURE)

        report = measure_reflection_benefit(fixture)

        assert report.dataset_id == "archon-reflection-benefit"
        assert report.version == "1.0.0"
        assert report.cases == 3
        assert report.baseline_correct == 1
        assert report.reflected_correct == 3
        assert report.baseline_score == pytest.approx(1 / 3)
        assert report.reflected_score == 1.0
        assert report.measured_delta == pytest.approx(2 / 3)
        assert report.measured_benefit is True

    def test_fixture_hash_prevents_unversioned_result_drift(self, tmp_path: Path) -> None:
        changed = FIXTURE.read_text(encoding="utf-8").replace("The sum is 41.", "The sum is 42.")
        path = tmp_path / "changed.json"
        path.write_text(changed, encoding="utf-8")

        with pytest.raises(ReflectionFixtureError, match="content hash"):
            load_reflection_benchmark_fixture(path)
