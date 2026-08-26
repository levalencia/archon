"""Tests for strict versioned evaluation fixture loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.eval.fixtures import DatasetFixtureError, fixture_content_hash, load_evaluation_fixture

_FIXTURE = Path("tests/fixtures/evals/grounded-v1.json")


def test_grounded_fixture_has_stable_verified_hash() -> None:
    fixture = load_evaluation_fixture(_FIXTURE)
    assert fixture.schema_version == 1
    assert fixture.version == "1.0.0"
    assert fixture.content_hash == (
        "76291c6eaac73f0333921303ece607ce95c4f26077387e73fcbd693ab1507f15"
    )
    assert fixture_content_hash(fixture) == fixture.content_hash


def test_fixture_loader_rejects_schema_version_cases_and_hash(tmp_path: Path) -> None:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    for name, mutate, message in (
        ("schema", lambda item: item.update({"extra": True}), "top-level schema"),
        ("version", lambda item: item.update({"schema_version": 2}), "schema version"),
        ("cases", lambda item: item.update({"cases": []}), "cases"),
        ("hash", lambda item: item.update({"content_hash": "0" * 64}), "hash does not match"),
    ):
        changed = dict(raw)
        mutate(changed)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(DatasetFixtureError, match=message):
            load_evaluation_fixture(path)
