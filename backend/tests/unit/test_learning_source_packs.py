"""Security and provenance tests for Hermes learning source packs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-learning-source-packs.py"
SPEC = importlib.util.spec_from_file_location("build_learning_source_packs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_builds_six_english_packs_with_checksums(tmp_path: Path) -> None:
    manifest = builder.build_packs(tmp_path / "packs", require_clean=False)
    assert manifest["schema"] == "cogentrex.learning-source-packs"
    assert manifest["language"] == "en"
    assert len(manifest["packs"]) == 6
    assert all(pack["language"] == "en" for pack in manifest["packs"])
    assert all(
        pack["files"][0]["source"] == "generated truth boundaries" for pack in manifest["packs"]
    )
    assert all(len(item["sha256"]) == 64 for pack in manifest["packs"] for item in pack["files"])


def test_rejects_nonempty_unowned_output(tmp_path: Path) -> None:
    output = tmp_path / "packs"
    output.mkdir()
    (output / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned"):
        builder.build_packs(output, require_clean=False)


def test_rejects_traversal_and_untracked_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        builder._safe_source("../outside.md")

    def reject_untracked(*_args: str) -> str:
        raise builder.subprocess.CalledProcessError(1, "git ls-files")

    monkeypatch.setattr(builder, "_git", reject_untracked)
    with pytest.raises(ValueError, match="untracked"):
        builder._safe_source("README.md")
