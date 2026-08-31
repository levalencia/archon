"""Executable contract for the capability acceptance baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.capabilities.acceptance import (
    REQUIRED_CAPABILITY_IDS,
    load_capability_acceptance,
)

ROOT = Path(__file__).parents[3]
MANIFEST = ROOT / "docs" / "implementation" / "CAPABILITY-ACCEPTANCE.yaml"


def _entry(identifier: str = "capability-a") -> dict[str, Any]:
    return {
        "id": identifier,
        "owner_module": "backend/app/runtime/engine.py",
        "status": "implemented",
        "dimensions": {
            "exists": "yes",
            "wired": "yes",
            "tested": "yes",
            "observed": "yes",
            "ui": "na",
            "live_provider": "na",
            "deployed": "no",
        },
        "sources": ["backend/app/runtime/engine.py"],
        "tests": ["backend/tests/unit/test_runtime_v2.py"],
        "evidence": ["docs/IMPLEMENTATION-EVIDENCE.md"],
        "limitation": "Local evidence only.",
    }


def _write(tmp_path: Path, entries: list[dict[str, Any]]) -> Path:
    path = tmp_path / "acceptance.yaml"
    path.write_text(json.dumps({"schema_version": 1, "capabilities": entries}), encoding="utf-8")
    return path


@pytest.mark.unit
def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="duplicate capability id"):
        load_capability_acceptance(_write(tmp_path, [_entry(), _entry()]))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [("dimensions.exists", "maybe"), ("status", "done")],
)
def test_rejects_invalid_dimension_and_status(tmp_path: Path, field: str, value: str) -> None:
    entry = _entry()
    if field.startswith("dimensions."):
        entry["dimensions"][field.split(".", 1)[1]] = value
    else:
        entry[field] = value

    with pytest.raises(ValidationError):
        load_capability_acceptance(_write(tmp_path, [entry]))


@pytest.mark.unit
def test_rejects_blank_owner_module(tmp_path: Path) -> None:
    entry = _entry()
    entry["owner_module"] = "  "

    with pytest.raises(ValidationError, match="owner_module"):
        load_capability_acceptance(_write(tmp_path, [entry]))


@pytest.mark.unit
def test_rejects_missing_or_blank_limitation(tmp_path: Path) -> None:
    entry = _entry()
    entry["limitation"] = "  "

    with pytest.raises(ValidationError, match="limitation"):
        load_capability_acceptance(_write(tmp_path, [entry]))


@pytest.mark.unit
@pytest.mark.parametrize("field", ["sources", "tests", "evidence"])
def test_implemented_requires_source_tests_and_evidence(tmp_path: Path, field: str) -> None:
    entry = _entry()
    entry[field] = []

    with pytest.raises(ValidationError, match="implemented capabilities require"):
        load_capability_acceptance(_write(tmp_path, [entry]))


@pytest.mark.unit
def test_real_manifest_is_complete_and_valid() -> None:
    manifest = load_capability_acceptance(MANIFEST, require_baseline=True)

    assert {item.id for item in manifest.capabilities} == REQUIRED_CAPABILITY_IDS
    assert all(
        set(item.dimensions.model_dump())
        == {"exists", "wired", "tested", "observed", "ui", "live_provider", "deployed"}
        for item in manifest.capabilities
    )
    assert [item.id for item in manifest.capabilities if item.status == "partial"] == []
    assert [
        (item.id, key)
        for item in manifest.capabilities
        for key, value in item.dimensions.model_dump().items()
        if value == "partial"
    ] == []
