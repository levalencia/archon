"""Safety and provenance contracts for NotebookLM source packs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts/build-notebooklm-source-packs.py"
SPEC = importlib.util.spec_from_file_location("build_notebooklm_packs", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_notebooklm_packs_are_external_sanitized_and_traceable(tmp_path: Path) -> None:
    output = tmp_path / "packs"
    manifest = builder.build_packs(output, require_clean=False)
    assert (output / builder.OWNER_MARKER).is_file()
    (output / "stale-notebook").mkdir()
    manifest = builder.build_packs(output, require_clean=False)

    assert not (output / "stale-notebook").exists()
    assert manifest["schema"] == "archon.notebooklm-source-packs"
    assert len(manifest["source_commit"]) == 40
    assert len(manifest["notebooks"]) == 5
    for notebook in manifest["notebooks"]:
        directory = output / notebook["directory"]
        assert directory.is_dir()
        assert (directory / "00-ARCHON-TRUTH-BOUNDARIES.md").is_file()
        assert (directory / "UPLOAD-README.md").is_file()
        assert len(notebook["files"]) >= 9
        for item in notebook["files"]:
            path = directory / item["upload_file"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
            assert not any(
                forbidden in item["upload_file"].lower()
                for forbidden in (".env", "auth.json", "storage_state", "secret")
            )
    assert json.loads((output / "manifest.json").read_text()) == manifest


def test_notebooklm_builder_requires_clean_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder, "_git", lambda *args: " M docs/example.md")
    with pytest.raises(ValueError, match="clean repository"):
        builder.build_packs(tmp_path / "packs")


def test_notebooklm_builder_refuses_unowned_and_dangerous_outputs(tmp_path: Path) -> None:
    unowned = tmp_path / "unowned"
    unowned.mkdir()
    sentinel = unowned / "keep-me.txt"
    sentinel.write_text("preserve")
    with pytest.raises(ValueError, match="unowned"):
        builder.build_packs(unowned, require_clean=False)
    assert sentinel.read_text() == "preserve"

    with pytest.raises(ValueError, match="unsafe"):
        builder.build_packs(Path.home(), require_clean=False)

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-output"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        builder.build_packs(link, require_clean=False)
    assert list(target.iterdir()) == []

    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        builder.build_packs(dangling / "packs", require_clean=False)

    marker_target = tmp_path / "valid-marker.json"
    marker_target.write_text(json.dumps({"schema": builder.OWNER_SCHEMA}))
    marker_link_output = tmp_path / "marker-link-output"
    marker_link_output.mkdir()
    marker_sentinel = marker_link_output / "keep-me-too.txt"
    marker_sentinel.write_text("preserve")
    (marker_link_output / builder.OWNER_MARKER).symlink_to(marker_target)
    with pytest.raises(ValueError, match="unowned"):
        builder.build_packs(marker_link_output, require_clean=False)
    assert marker_sentinel.read_text() == "preserve"


def test_private_key_markers_are_rejected(tmp_path: Path) -> None:
    for marker in (
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN ENCRYPTED PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN DSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "-----BEGIN PGP PRIVATE KEY BLOCK-----",
    ):
        source = tmp_path / "candidate.md"
        source.write_text(marker)
        with pytest.raises(ValueError, match="private-key marker"):
            builder._scan_source(source, "candidate.md")


def test_notebooklm_builder_refuses_repository_output() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        builder.build_packs(ROOT / "generated-notebooklm", require_clean=False)
