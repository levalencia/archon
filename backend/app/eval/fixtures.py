"""Strict loader for immutable, versioned evaluation fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FIXTURE_SCHEMA_VERSION = 1
_TOP_LEVEL_KEYS = frozenset({"schema_version", "dataset_id", "version", "content_hash", "cases"})
_CASE_KEYS = frozenset({"key", "grounded", "expected_contains", "expected_not_contains"})


class DatasetFixtureError(ValueError):
    """A fixture is malformed, unsupported, or does not match its declared hash."""


@dataclass(frozen=True, slots=True)
class EvaluationFixtureCase:
    key: str
    grounded: bool
    expected_contains: tuple[str, ...]
    expected_not_contains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationFixture:
    schema_version: int
    dataset_id: str
    version: str
    content_hash: str
    cases: tuple[EvaluationFixtureCase, ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatasetFixtureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 100:
        raise DatasetFixtureError(f"{field} must be a list of at most 100 strings")
    if any(not isinstance(item, str) or not item or len(item) > 500 for item in value):
        raise DatasetFixtureError(f"{field} entries must be non-empty bounded strings")
    strings = tuple(value)
    if len(set(strings)) != len(strings):
        raise DatasetFixtureError(f"{field} entries must be unique")
    return strings


def _canonical(fixture: EvaluationFixture) -> bytes:
    body = {
        "cases": [
            {
                "expected_contains": list(case.expected_contains),
                "expected_not_contains": list(case.expected_not_contains),
                "grounded": case.grounded,
                "key": case.key,
            }
            for case in fixture.cases
        ],
        "dataset_id": fixture.dataset_id,
        "schema_version": fixture.schema_version,
        "version": fixture.version,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fixture_content_hash(fixture: EvaluationFixture) -> str:
    """Compute the canonical SHA-256 identity, excluding the declared hash field."""
    return hashlib.sha256(_canonical(fixture)).hexdigest()


def load_evaluation_fixture(path: Path) -> EvaluationFixture:
    """Load an exact-schema fixture and reject version, case, or hash drift."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except DatasetFixtureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatasetFixtureError("fixture is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _TOP_LEVEL_KEYS:
        raise DatasetFixtureError("fixture has an invalid top-level schema")
    if raw["schema_version"] != _FIXTURE_SCHEMA_VERSION:
        raise DatasetFixtureError("unsupported fixture schema version")
    dataset_id = raw["dataset_id"]
    version = raw["version"]
    content_hash = raw["content_hash"]
    raw_cases = raw["cases"]
    if not isinstance(dataset_id, str) or not dataset_id or len(dataset_id) > 255:
        raise DatasetFixtureError("dataset_id is invalid")
    if not isinstance(version, str) or not version or len(version) > 100:
        raise DatasetFixtureError("dataset version is invalid")
    if (
        not isinstance(content_hash, str)
        or len(content_hash) != 64
        or any(char not in "0123456789abcdef" for char in content_hash)
    ):
        raise DatasetFixtureError("content_hash must be a lowercase SHA-256 digest")
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 100:
        raise DatasetFixtureError("cases must contain between 1 and 100 items")
    cases: list[EvaluationFixtureCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or set(raw_case) != _CASE_KEYS:
            raise DatasetFixtureError("case has an invalid schema")
        key = raw_case["key"]
        grounded = raw_case["grounded"]
        if not isinstance(key, str) or not key or len(key) > 255:
            raise DatasetFixtureError("case key is invalid")
        if not isinstance(grounded, bool):
            raise DatasetFixtureError("case grounded must be boolean")
        cases.append(
            EvaluationFixtureCase(
                key=key,
                grounded=grounded,
                expected_contains=_strings(raw_case["expected_contains"], "expected_contains"),
                expected_not_contains=_strings(
                    raw_case["expected_not_contains"], "expected_not_contains"
                ),
            )
        )
    if len({case.key for case in cases}) != len(cases):
        raise DatasetFixtureError("case keys must be unique")
    fixture = EvaluationFixture(
        schema_version=_FIXTURE_SCHEMA_VERSION,
        dataset_id=dataset_id,
        version=version,
        content_hash=content_hash,
        cases=tuple(cases),
    )
    if fixture_content_hash(fixture) != content_hash:
        raise DatasetFixtureError("fixture content hash does not match")
    return fixture
