"""Deterministic, version-pinned baseline-versus-reflection measurement."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = 1
_TOP_KEYS = frozenset(
    {
        "schema_version",
        "dataset_id",
        "version",
        "content_hash",
        "evidence_kind",
        "generation_provenance",
        "cases",
    }
)
_CASE_KEYS = frozenset({"key", "prompt", "expected_answer", "baseline_answer", "reflected_answer"})
_MAX_CASES = 100
_MAX_TEXT = 10_000


class ReflectionFixtureError(ValueError):
    """The measured-benefit fixture is malformed, unsupported, or has drifted."""


@dataclass(frozen=True, slots=True)
class ReflectionBenchmarkCase:
    key: str
    prompt: str
    expected_answer: str
    baseline_answer: str
    reflected_answer: str


@dataclass(frozen=True, slots=True)
class ReflectionBenchmarkFixture:
    schema_version: int
    dataset_id: str
    version: str
    content_hash: str
    evidence_kind: str
    generation_provenance: str
    cases: tuple[ReflectionBenchmarkCase, ...]


@dataclass(frozen=True, slots=True)
class ReflectionBenefitReport:
    dataset_id: str
    version: str
    content_hash: str
    evidence_kind: str
    generation_provenance: str
    runtime_executed: bool
    generalizes: bool
    cases: int
    baseline_correct: int
    reflected_correct: int
    baseline_score: float
    reflected_score: float
    measured_delta: float

    @property
    def measured_benefit(self) -> bool:
        return self.measured_delta > 0.0


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ReflectionFixtureError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _text(value: object, field: str, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ReflectionFixtureError(f"{field} must be a non-empty bounded string")
    return value


def _canonical(fixture: ReflectionBenchmarkFixture) -> bytes:
    value = {
        "cases": [
            {
                "baseline_answer": case.baseline_answer,
                "expected_answer": case.expected_answer,
                "key": case.key,
                "prompt": case.prompt,
                "reflected_answer": case.reflected_answer,
            }
            for case in fixture.cases
        ],
        "dataset_id": fixture.dataset_id,
        "evidence_kind": fixture.evidence_kind,
        "generation_provenance": fixture.generation_provenance,
        "schema_version": fixture.schema_version,
        "version": fixture.version,
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def reflection_fixture_content_hash(fixture: ReflectionBenchmarkFixture) -> str:
    return hashlib.sha256(_canonical(fixture)).hexdigest()


def load_reflection_benchmark_fixture(path: Path) -> ReflectionBenchmarkFixture:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except ReflectionFixtureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReflectionFixtureError("fixture is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _TOP_KEYS:
        raise ReflectionFixtureError("fixture has an invalid top-level schema")
    if raw["schema_version"] != _SCHEMA_VERSION:
        raise ReflectionFixtureError("unsupported fixture schema version")
    cases_raw = raw["cases"]
    if not isinstance(cases_raw, list) or not 1 <= len(cases_raw) <= _MAX_CASES:
        raise ReflectionFixtureError("cases must be a non-empty bounded list")
    cases: list[ReflectionBenchmarkCase] = []
    for item in cases_raw:
        if not isinstance(item, dict) or set(item) != _CASE_KEYS:
            raise ReflectionFixtureError("case has an invalid schema")
        cases.append(
            ReflectionBenchmarkCase(
                _text(item["key"], "key", 128),
                _text(item["prompt"], "prompt"),
                _text(item["expected_answer"], "expected_answer"),
                _text(item["baseline_answer"], "baseline_answer"),
                _text(item["reflected_answer"], "reflected_answer"),
            )
        )
    if len({case.key for case in cases}) != len(cases):
        raise ReflectionFixtureError("case keys must be unique")
    content_hash = raw["content_hash"]
    if (
        not isinstance(content_hash, str)
        or len(content_hash) != 64
        or any(character not in "0123456789abcdef" for character in content_hash)
    ):
        raise ReflectionFixtureError("content_hash must be a lowercase SHA-256 digest")
    evidence_kind = _text(raw["evidence_kind"], "evidence_kind", 64)
    if evidence_kind != "recorded_synthetic_fixture":
        raise ReflectionFixtureError("unsupported reflection evidence kind")
    fixture = ReflectionBenchmarkFixture(
        _SCHEMA_VERSION,
        _text(raw["dataset_id"], "dataset_id", 128),
        _text(raw["version"], "version", 64),
        content_hash,
        evidence_kind,
        _text(raw["generation_provenance"], "generation_provenance", 512),
        tuple(cases),
    )
    if reflection_fixture_content_hash(fixture) != fixture.content_hash:
        raise ReflectionFixtureError("fixture content hash does not match")
    return fixture


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def measure_reflection_benefit(fixture: ReflectionBenchmarkFixture) -> ReflectionBenefitReport:
    """Report only the observed exact-match delta on the supplied pinned fixture."""
    if reflection_fixture_content_hash(fixture) != fixture.content_hash:
        raise ReflectionFixtureError("fixture content hash does not match")
    baseline = sum(
        _normalized(case.baseline_answer) == _normalized(case.expected_answer)
        for case in fixture.cases
    )
    reflected = sum(
        _normalized(case.reflected_answer) == _normalized(case.expected_answer)
        for case in fixture.cases
    )
    count = len(fixture.cases)
    baseline_score = baseline / count
    reflected_score = reflected / count
    return ReflectionBenefitReport(
        fixture.dataset_id,
        fixture.version,
        fixture.content_hash,
        fixture.evidence_kind,
        fixture.generation_provenance,
        False,
        False,
        count,
        baseline,
        reflected,
        baseline_score,
        reflected_score,
        reflected_score - baseline_score,
    )
