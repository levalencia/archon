"""Unit tests for scripts/learning-media-release.py – comprehensive security tests.

Covers: manifest validation, catalog validation, path traversal, absent artifacts,
content checksums, untrusted HTTPS host, oversized downloads, member counts,
duplicate members, uncompressed size caps, output parent creation, target-inside-repo,
unrelated .old preservation, atomic rollback, and more.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import io
import json
import os
import struct
import sys
import tarfile
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def _import_release_module():
    """Import scripts/learning-media-release.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "learning_media_release",
        SCRIPTS_DIR / "learning-media-release.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["learning_media_release"] = mod
    spec.loader.exec_module(mod)
    return mod


lmr = _import_release_module()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SOURCE_COMMIT = "07b527103e2863e09a71802463f5af91c37eb69e"
MARKER_FILE = ".archon-learning-library"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 16)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _make_minimal_library(root: Path, *, commit: str = SOURCE_COMMIT) -> dict:
    """Create a minimal library directory tree that passes validation."""
    marker = root / MARKER_FILE
    marker.write_text("archon.learning-library/v1\n")

    pub = root / "published" / "demo-pack" / "demo-deck"
    pub.mkdir(parents=True, exist_ok=True)

    deck_content = b'{"title":"Demo"}'
    deck_file = pub / "deck.json"
    deck_file.write_bytes(deck_content)

    svg_content = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    svg_file = pub / "diagram.svg"
    svg_file.write_bytes(svg_content)

    catalog = {
        "schema": "archon.learning-library",
        "version": 1,
        "generated_at": "2026-09-08T11:00:00+00:00",
        "source_commit": commit,
        "packs": [
            {
                "id": "demo-pack",
                "title": "Demo Pack",
                "purpose": "testing",
                "artifacts": [
                    {
                        "id": "demo-deck",
                        "type": "deck",
                        "title": "Demo Deck",
                        "status": "review-ready",
                        "language": "en",
                        "file": "published/demo-pack/demo-deck/deck.json",
                        "media_type": "application/json",
                        "sha256": _sha256(deck_content),
                        "source_commit": commit,
                        "limitations": [],
                    },
                    {
                        "id": "demo-diagram",
                        "type": "diagram",
                        "title": "Demo Diagram",
                        "status": "review-ready",
                        "language": "en",
                        "file": "published/demo-pack/demo-deck/diagram.svg",
                        "media_type": "image/svg+xml",
                        "sha256": _sha256(svg_content),
                        "source_commit": commit,
                        "limitations": [],
                    },
                ],
            }
        ],
    }
    (root / "catalog.json").write_text(json.dumps(catalog, indent=2))
    return catalog


def _make_archive_and_manifest(tmp_path: Path) -> tuple[Path, dict]:
    """Create a valid archive + manifest for install tests."""
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_minimal_library(lib)
    out = tmp_path / "pkg.tar.gz"
    manifest = lmr.create_archive(lib, out, SOURCE_COMMIT)
    return out, manifest


def _make_hostile_archive(tmp_path: Path, members: list) -> Path:
    """Create a tar.gz with given members."""
    out = tmp_path / "hostile.tar.gz"
    with tarfile.open(out, "w:gz") as tf:
        for m in members:
            tf.addfile(m)
    return out


def _manifest_for_raw_archive(archive_path: Path) -> dict:
    """Build a manifest that matches a raw archive for testing."""
    bs = archive_path.stat().st_size
    sha = _sha256_file(archive_path)
    short = SOURCE_COMMIT[:12]
    tag = f"learning-media-{short}"
    asset = f"archon-learning-media-{short}.tar.gz"
    return {
        "schema_version": 1,
        "release_tag": tag,
        "source_commit": SOURCE_COMMIT,
        "asset_name": asset,
        "download_url": f"https://github.com/levalencia/archon/releases/download/{tag}/{asset}",
        "byte_size": bs,
        "archive_sha256": sha,
    }


# ===================================================================
# MANIFEST VALIDATION TESTS
# ===================================================================


class TestManifestValidation:
    """Manifest must be validated before any network/file work."""

    def _base_manifest(self) -> dict:
        short = SOURCE_COMMIT[:12]
        tag = f"learning-media-{short}"
        asset = f"archon-learning-media-{short}.tar.gz"
        return {
            "schema_version": 1,
            "release_tag": tag,
            "source_commit": SOURCE_COMMIT,
            "asset_name": asset,
            "download_url": f"https://github.com/levalencia/archon/releases/download/{tag}/{asset}",
            "byte_size": 12345,
            "archive_sha256": "a" * 64,
        }

    def test_valid_manifest_passes(self):
        lmr.validate_manifest(self._base_manifest())

    def test_missing_schema_version(self):
        m = self._base_manifest()
        del m["schema_version"]
        with pytest.raises(lmr.InstallError, match="schema_version"):
            lmr.validate_manifest(m)

    def test_wrong_schema_version(self):
        m = self._base_manifest()
        m["schema_version"] = 99
        with pytest.raises(lmr.InstallError, match="schema_version"):
            lmr.validate_manifest(m)

    def test_missing_byte_size(self):
        m = self._base_manifest()
        del m["byte_size"]
        with pytest.raises(lmr.InstallError, match="byte_size"):
            lmr.validate_manifest(m)

    def test_null_byte_size(self):
        m = self._base_manifest()
        m["byte_size"] = None
        with pytest.raises(lmr.InstallError, match="byte_size"):
            lmr.validate_manifest(m)

    def test_byte_size_above_archive_limit(self):
        m = self._base_manifest()
        m["byte_size"] = lmr.MAX_ARCHIVE_SIZE + 1
        with pytest.raises(lmr.InstallError, match="byte_size"):
            lmr.validate_manifest(m)

    def test_zero_byte_size(self):
        m = self._base_manifest()
        m["byte_size"] = 0
        with pytest.raises(lmr.InstallError, match="byte_size"):
            lmr.validate_manifest(m)

    def test_negative_byte_size(self):
        m = self._base_manifest()
        m["byte_size"] = -1
        with pytest.raises(lmr.InstallError, match="byte_size"):
            lmr.validate_manifest(m)

    def test_missing_archive_sha256(self):
        m = self._base_manifest()
        del m["archive_sha256"]
        with pytest.raises(lmr.InstallError, match="archive_sha256"):
            lmr.validate_manifest(m)

    def test_null_archive_sha256(self):
        m = self._base_manifest()
        m["archive_sha256"] = None
        with pytest.raises(lmr.InstallError, match="archive_sha256"):
            lmr.validate_manifest(m)

    def test_short_archive_sha256(self):
        m = self._base_manifest()
        m["archive_sha256"] = "abcd"
        with pytest.raises(lmr.InstallError, match="archive_sha256"):
            lmr.validate_manifest(m)

    def test_uppercase_archive_sha256(self):
        m = self._base_manifest()
        m["archive_sha256"] = "A" * 64
        with pytest.raises(lmr.InstallError, match="archive_sha256"):
            lmr.validate_manifest(m)

    def test_short_source_commit(self):
        m = self._base_manifest()
        m["source_commit"] = "deadbeef"
        with pytest.raises(lmr.InstallError, match="source_commit"):
            lmr.validate_manifest(m)

    def test_null_source_commit(self):
        m = self._base_manifest()
        m["source_commit"] = None
        with pytest.raises(lmr.InstallError, match="source_commit"):
            lmr.validate_manifest(m)

    def test_wrong_tag_format(self):
        m = self._base_manifest()
        m["release_tag"] = "wrong-tag"
        with pytest.raises(lmr.InstallError, match="release_tag"):
            lmr.validate_manifest(m)

    def test_wrong_asset_name(self):
        m = self._base_manifest()
        m["asset_name"] = "wrong.tar.gz"
        with pytest.raises(lmr.InstallError, match="asset_name"):
            lmr.validate_manifest(m)

    def test_wrong_download_url(self):
        m = self._base_manifest()
        m["download_url"] = "https://evil.com/file.tar.gz"
        with pytest.raises(lmr.InstallError, match="download_url"):
            lmr.validate_manifest(m)

    def test_http_download_url(self):
        m = self._base_manifest()
        short = SOURCE_COMMIT[:12]
        tag = f"learning-media-{short}"
        asset = f"archon-learning-media-{short}.tar.gz"
        m["download_url"] = f"http://github.com/levalencia/archon/releases/download/{tag}/{asset}"
        with pytest.raises(lmr.InstallError, match="download_url"):
            lmr.validate_manifest(m)


# ===================================================================
# CATALOG VALIDATION TESTS
# ===================================================================


class TestCatalogValidation:
    """Catalog schema validation."""

    def test_valid_catalog_passes(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        lmr.validate_catalog(cat, tmp_path)

    def test_missing_schema_key_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        del cat["schema"]
        with pytest.raises(lmr.PackageError, match="schema"):
            lmr.validate_catalog(cat, tmp_path)

    def test_wrong_schema_value_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["schema"] = "wrong"
        with pytest.raises(lmr.PackageError, match="schema"):
            lmr.validate_catalog(cat, tmp_path)

    def test_version_must_be_1(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["version"] = 2
        with pytest.raises(lmr.PackageError, match="version"):
            lmr.validate_catalog(cat, tmp_path)

    def test_missing_source_commit_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        del cat["source_commit"]
        with pytest.raises(lmr.PackageError, match="source_commit"):
            lmr.validate_catalog(cat, tmp_path)

    def test_wrong_commit_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["source_commit"] = "deadbeef"
        with pytest.raises(lmr.PackageError, match="source_commit"):
            lmr.validate_catalog(cat, tmp_path)

    def test_empty_packs_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["packs"] = []
        with pytest.raises(lmr.PackageError, match="packs"):
            lmr.validate_catalog(cat, tmp_path)

    def test_empty_artifacts_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["packs"][0]["artifacts"] = []
        with pytest.raises(lmr.PackageError, match="artifacts"):
            lmr.validate_catalog(cat, tmp_path)

    def test_artifact_bad_sha256_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["packs"][0]["artifacts"][0]["sha256"] = "0" * 64
        with pytest.raises(lmr.PackageError, match="sha256"):
            lmr.validate_catalog(cat, tmp_path)

    def test_artifact_missing_file_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        (tmp_path / cat["packs"][0]["artifacts"][0]["file"]).unlink()
        with pytest.raises(lmr.PackageError, match="not found"):
            lmr.validate_catalog(cat, tmp_path)

    def test_artifact_path_traversal_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["packs"][0]["artifacts"][0]["file"] = "published/../../etc/passwd"
        with pytest.raises(lmr.PackageError, match="traversal"):
            lmr.validate_catalog(cat, tmp_path)

    def test_artifact_absolute_path_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        cat["packs"][0]["artifacts"][0]["file"] = "/etc/passwd"
        with pytest.raises(lmr.PackageError, match="absolute|published"):
            lmr.validate_catalog(cat, tmp_path)

    def test_artifact_outside_published_raises(self, tmp_path: Path):
        cat = _make_minimal_library(tmp_path)
        # Create a file outside published/
        (tmp_path / "outside.txt").write_text("bad")
        cat["packs"][0]["artifacts"][0]["file"] = "outside.txt"
        with pytest.raises(lmr.PackageError, match="published"):
            lmr.validate_catalog(cat, tmp_path)

    def test_content_file_checksum_validated(self, tmp_path: Path):
        """content_file with wrong content_sha256 must fail."""
        cat = _make_minimal_library(tmp_path)
        # Add a content_file reference to first artifact
        cf_path = tmp_path / "published" / "demo-pack" / "demo-deck" / "extra.txt"
        cf_path.write_bytes(b"extra content")
        cat["packs"][0]["artifacts"][0]["content_file"] = "published/demo-pack/demo-deck/extra.txt"
        cat["packs"][0]["artifacts"][0]["content_sha256"] = "0" * 64
        with pytest.raises(lmr.PackageError, match="content_file.*checksum"):
            lmr.validate_catalog(cat, tmp_path)


class TestSymlinkRejection:
    """Symlinks and non-regular files must be rejected."""

    def test_symlink_in_published_rejected(self, tmp_path: Path):
        _make_minimal_library(tmp_path)
        link = tmp_path / "published" / "bad-link"
        link.symlink_to("/etc/passwd")
        with pytest.raises(lmr.PackageError, match="[Ss]ymlink|non-regular"):
            lmr.scan_for_irregular_files(tmp_path)

    def test_fifo_rejected(self, tmp_path: Path):
        _make_minimal_library(tmp_path)
        fifo = tmp_path / "published" / "bad-fifo"
        os.mkfifo(fifo)
        with pytest.raises(lmr.PackageError, match="non-regular"):
            lmr.scan_for_irregular_files(tmp_path)

    def test_invalid_ownership_marker_rejected(self, tmp_path: Path):
        _make_minimal_library(tmp_path)
        (tmp_path / MARKER_FILE).write_text("not-archon\n")
        with pytest.raises(lmr.PackageError, match="ownership marker"):
            lmr.scan_for_irregular_files(tmp_path)


# ===================================================================
# PACKAGING TESTS
# ===================================================================


class TestDeterministicPackaging:
    """Archive must be byte-for-byte reproducible."""

    def test_two_runs_produce_identical_bytes(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out1 = tmp_path / "a.tar.gz"
        out2 = tmp_path / "b.tar.gz"
        lmr.create_archive(lib, out1, SOURCE_COMMIT)
        lmr.create_archive(lib, out2, SOURCE_COMMIT)
        assert out1.read_bytes() == out2.read_bytes()

    def test_archive_sha256_matches_manifest(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out = tmp_path / "pkg.tar.gz"
        manifest = lmr.create_archive(lib, out, SOURCE_COMMIT)
        actual_sha = _sha256_file(out)
        assert manifest["archive_sha256"] == actual_sha

    def test_archive_contains_expected_entries(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out = tmp_path / "pkg.tar.gz"
        lmr.create_archive(lib, out, SOURCE_COMMIT)
        with tarfile.open(out, "r:gz") as tf:
            names = sorted(tf.getnames())
        assert ".archon-learning-library" in names
        assert "catalog.json" in names
        assert any("published/" in n for n in names)

    def test_gzip_mtime_is_zero(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out = tmp_path / "pkg.tar.gz"
        lmr.create_archive(lib, out, SOURCE_COMMIT)
        raw = out.read_bytes()
        mtime = struct.unpack("<I", raw[4:8])[0]
        assert mtime == 0

    def test_normalized_uid_gid(self, tmp_path: Path):
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out = tmp_path / "pkg.tar.gz"
        lmr.create_archive(lib, out, SOURCE_COMMIT)
        with tarfile.open(out, "r:gz") as tf:
            for m in tf.getmembers():
                assert m.uid == 0
                assert m.gid == 0
                assert m.uname == "root"
                assert m.gname == "root"

    def test_output_parent_mkdir(self, tmp_path: Path):
        """Output parent directories are created automatically."""
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        out = tmp_path / "nested" / "deep" / "pkg.tar.gz"
        manifest = lmr.create_archive(lib, out, SOURCE_COMMIT)
        assert out.exists()
        assert manifest["byte_size"] > 0

    def test_only_marker_catalog_published_included(self, tmp_path: Path):
        """Extra files at library root must NOT be included in archive."""
        lib = tmp_path / "lib"
        lib.mkdir()
        _make_minimal_library(lib)
        (lib / "extra-file.txt").write_text("should not be included")
        (lib / "other-dir").mkdir()
        (lib / "other-dir" / "child.txt").write_text("also excluded")
        out = tmp_path / "pkg.tar.gz"
        lmr.create_archive(lib, out, SOURCE_COMMIT)
        with tarfile.open(out, "r:gz") as tf:
            names = tf.getnames()
        for n in names:
            top = n.split("/")[0]
            assert top in {".archon-learning-library", "catalog.json", "published"}, (
                f"Unexpected entry {n!r} in archive"
            )


# ===================================================================
# MANIFEST OUTPUT TESTS
# ===================================================================


class TestManifestOutput:
    """Manifest produced by create_archive must be valid."""

    def test_manifest_has_schema_version(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        assert manifest["schema_version"] == 1

    def test_manifest_has_required_keys(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        required = {
            "schema_version",
            "release_tag",
            "source_commit",
            "asset_name",
            "download_url",
            "byte_size",
            "archive_sha256",
        }
        assert required.issubset(set(manifest.keys()))

    def test_manifest_passes_own_validation(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        lmr.validate_manifest(manifest)  # should not raise

    def test_asset_naming_no_duplication(self, tmp_path: Path):
        """Tag is learning-media-<short>, asset is archon-learning-media-<short>.tar.gz."""
        archive, manifest = _make_archive_and_manifest(tmp_path)
        short = SOURCE_COMMIT[:12]
        assert manifest["release_tag"] == f"learning-media-{short}"
        assert manifest["asset_name"] == f"archon-learning-media-{short}.tar.gz"
        # Specifically: no doubled "learning-media-learning-media-" in asset name
        assert "learning-media-learning-media-" not in manifest["asset_name"]


# ===================================================================
# INSTALLATION TESTS
# ===================================================================


class TestInstallValidation:
    """Install-time security checks."""

    def test_install_from_local_archive(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        target = tmp_path / "install-target"
        lmr.install_archive(archive, target, manifest)
        assert (target / MARKER_FILE).exists()
        assert (target / "catalog.json").exists()
        assert any((target / "published").rglob("*"))

    def test_install_rejects_nonempty_unowned_target(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        target = tmp_path / "install-target"
        target.mkdir()
        (target / "foreign-file.txt").write_text("intruder")
        with pytest.raises(lmr.InstallError, match="[Nn]on-empty|unowned"):
            lmr.install_archive(archive, target, manifest)

    def test_install_replaces_owned_target(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        target = tmp_path / "install-target"
        lmr.install_archive(archive, target, manifest)
        assert (target / MARKER_FILE).exists()
        lmr.install_archive(archive, target, manifest)
        assert (target / MARKER_FILE).exists()

    def test_install_rejects_bad_sha256(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        manifest["archive_sha256"] = "0" * 64
        target = tmp_path / "install-target"
        with pytest.raises(lmr.InstallError, match="[Ss]HA|checksum"):
            lmr.install_archive(archive, target, manifest)

    def test_install_rejects_bad_size(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        manifest["byte_size"] = 1
        target = tmp_path / "install-target"
        with pytest.raises(lmr.InstallError, match="[Ss]ize"):
            lmr.install_archive(archive, target, manifest)

    def test_install_rejects_manifest_without_integrity_fields(self, tmp_path: Path):
        """Missing integrity fields must fail at manifest validation."""
        archive, manifest = _make_archive_and_manifest(tmp_path)
        for field in ("archive_sha256", "byte_size", "schema_version"):
            bad = dict(manifest)
            del bad[field]
            target = tmp_path / f"t-{field}"
            with pytest.raises(lmr.InstallError):
                lmr.install_archive(archive, target, bad)


class TestTargetInsideRepo:
    """Install target inside the repository root must be rejected."""

    def test_target_inside_repo_rejected(self, tmp_path: Path):
        archive, manifest = _make_archive_and_manifest(tmp_path)
        # Point target inside the repo (where the script lives)
        repo_root = Path(lmr.__file__).resolve().parent.parent
        target = repo_root / "media-install-test"
        with pytest.raises(lmr.InstallError, match="outside.*repository"):
            lmr.install_archive(archive, target, manifest)


class TestAtomicRollback:
    """Atomic replacement must use unique backup and preserve unrelated .old."""

    def test_unrelated_old_preserved(self, tmp_path: Path):
        """A pre-existing <target>.old directory must not be deleted."""
        archive, manifest = _make_archive_and_manifest(tmp_path)
        target = tmp_path / "install-target"
        # First install
        lmr.install_archive(archive, target, manifest)

        # Create an unrelated .old directory
        unrelated_old = target.with_name(target.name + ".old")
        unrelated_old.mkdir()
        (unrelated_old / "precious.txt").write_text("do not delete")

        # Second install should NOT touch unrelated .old
        lmr.install_archive(archive, target, manifest)
        assert (target / MARKER_FILE).exists()
        assert unrelated_old.exists(), "Unrelated .old was deleted!"
        assert (unrelated_old / "precious.txt").read_text() == "do not delete"

    def test_rollback_on_failure(self, tmp_path: Path):
        """If staging rename fails, the original target is restored."""
        archive, manifest = _make_archive_and_manifest(tmp_path)
        target = tmp_path / "install-target"
        lmr.install_archive(archive, target, manifest)
        assert (target / MARKER_FILE).exists()

        # Patch staging.rename to fail after backup
        original_rename = Path.rename

        def failing_rename(self_path, dest):
            # Let backup rename succeed, fail on staging->target
            if ".media-install-" in str(self_path):
                raise OSError("simulated rename failure")
            return original_rename(self_path, dest)

        with (
            mock.patch.object(Path, "rename", failing_rename),
            pytest.raises(OSError, match="simulated"),
        ):
            lmr.install_archive(archive, target, manifest)

        # Original target should be restored
        assert target.exists()
        assert (target / MARKER_FILE).exists()


# ===================================================================
# TAR SECURITY TESTS
# ===================================================================


class TestTarSecurity:
    """Archive extraction must reject hostile tar entries."""

    def test_reject_absolute_path(self, tmp_path: Path):
        m = tarfile.TarInfo(name="/etc/passwd")
        m.size = 0
        out = _make_hostile_archive(tmp_path, [m])
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Aa]bsolute|traversal|[Pp]ath"):
            lmr.install_archive(out, target, manifest)

    def test_reject_traversal_path(self, tmp_path: Path):
        m = tarfile.TarInfo(name="../../../etc/passwd")
        m.size = 0
        out = _make_hostile_archive(tmp_path, [m])
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Aa]bsolute|traversal|[Pp]ath"):
            lmr.install_archive(out, target, manifest)

    def test_reject_symlink_member(self, tmp_path: Path):
        m = tarfile.TarInfo(name="evil-link")
        m.type = tarfile.SYMTYPE
        m.linkname = "/etc/shadow"
        out = _make_hostile_archive(tmp_path, [m])
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Ll]ink|device|[Tt]ype"):
            lmr.install_archive(out, target, manifest)

    def test_reject_device_member(self, tmp_path: Path):
        m = tarfile.TarInfo(name="evil-dev")
        m.type = tarfile.CHRTYPE
        out = _make_hostile_archive(tmp_path, [m])
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Ll]ink|device|[Tt]ype"):
            lmr.install_archive(out, target, manifest)

    def test_reject_unexpected_top_level(self, tmp_path: Path):
        info = tarfile.TarInfo(name="rogue-file.txt")
        info.size = 5
        out = tmp_path / "rogue.tar.gz"
        cat_bytes = (
            b'{"schema":"archon.learning-library","version":1,'
            b'"source_commit":"07b527103e2863e09a71802463f5af91c37eb69e",'
            b'"generated_at":"2026-09-08T11:00:00+00:00","packs":[]}'
        )
        with tarfile.open(out, "w:gz") as tf:
            marker = tarfile.TarInfo(name=".archon-learning-library")
            marker.size = 0
            tf.addfile(marker)
            cat = tarfile.TarInfo(name="catalog.json")
            cat.size = len(cat_bytes)
            tf.addfile(cat, io.BytesIO(cat_bytes))
            tf.addfile(info, io.BytesIO(b"rogue"))
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Uu]nexpected|top.level"):
            lmr.install_archive(out, target, manifest)

    def test_reject_duplicate_member_names(self, tmp_path: Path):
        """Duplicate names in archive must be rejected."""
        out = tmp_path / "dup.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            m1 = tarfile.TarInfo(name=".archon-learning-library")
            m1.size = 0
            tf.addfile(m1)
            m2 = tarfile.TarInfo(name=".archon-learning-library")
            m2.size = 0
            tf.addfile(m2)
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="[Dd]uplicate"):
            lmr.install_archive(out, target, manifest)

    def test_reject_excessive_members_with_low_limit(self, tmp_path: Path):
        """Monkeypatch MAX_ARCHIVE_MEMBERS to a low number and verify rejection."""
        out = tmp_path / "many.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            for i in range(10):
                m = tarfile.TarInfo(name=f"published/file{i}.txt")
                m.size = 1
                tf.addfile(m, io.BytesIO(b"x"))
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with (
            mock.patch.object(lmr, "MAX_ARCHIVE_MEMBERS", 5),
            pytest.raises(lmr.InstallError, match="excessive members"),
        ):
            lmr.install_archive(out, target, manifest)

    def test_reject_oversized_member(self, tmp_path: Path):
        """Member claiming huge size must be rejected by per-member cap."""
        out = tmp_path / "big.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            m = tarfile.TarInfo(name=".archon-learning-library")
            m.size = 0
            tf.addfile(m)
            big = tarfile.TarInfo(name="published/huge.bin")
            big.size = 100  # actual data is small, but we'll patch the cap
            tf.addfile(big, io.BytesIO(b"x" * 100))
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        with (
            mock.patch.object(lmr, "MAX_MEMBER_UNCOMPRESSED", 50),
            pytest.raises(lmr.InstallError, match="per-member size"),
        ):
            lmr.install_archive(out, target, manifest)

    def test_reject_cumulative_uncompressed_cap(self, tmp_path: Path):
        """Cumulative uncompressed size exceeding cap must be rejected."""
        out = tmp_path / "cumul.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            for i in range(5):
                m = tarfile.TarInfo(name=f"published/f{i}.txt")
                m.size = 30
                tf.addfile(m, io.BytesIO(b"x" * 30))
        manifest = _manifest_for_raw_archive(out)
        target = tmp_path / "t"
        # 5 * 30 = 150 bytes cumulative; set cap to 100
        with (
            mock.patch.object(lmr, "MAX_TOTAL_UNCOMPRESSED", 100),
            pytest.raises(lmr.InstallError, match="[Cc]umulative"),
        ):
            lmr.install_archive(out, target, manifest)


# ===================================================================
# DOWNLOAD TESTS
# ===================================================================


class TestDownloadSecurity:
    """HTTPS download must enforce host, Content-Length, and byte cap."""

    def test_download_rejects_non_https(self, tmp_path: Path):
        m = {
            "schema_version": 1,
            "release_tag": f"learning-media-{SOURCE_COMMIT[:12]}",
            "source_commit": SOURCE_COMMIT,
            "asset_name": f"archon-learning-media-{SOURCE_COMMIT[:12]}.tar.gz",
            "download_url": "http://evil.com/pkg.tar.gz",
            "archive_sha256": "a" * 64,
            "byte_size": 100,
        }
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="download_url"):
            lmr.install_from_manifest(m, target)

    def test_download_rejects_untrusted_host(self, tmp_path: Path):
        """URL pointing to a non-github host must be rejected."""
        m = {
            "schema_version": 1,
            "release_tag": f"learning-media-{SOURCE_COMMIT[:12]}",
            "source_commit": SOURCE_COMMIT,
            "asset_name": f"archon-learning-media-{SOURCE_COMMIT[:12]}.tar.gz",
            "download_url": "https://evil.com/levalencia/archon/releases/download/x/y",
            "archive_sha256": "a" * 64,
            "byte_size": 100,
        }
        target = tmp_path / "t"
        with pytest.raises(lmr.InstallError, match="download_url"):
            lmr.install_from_manifest(m, target)

    def test_download_byte_cap_enforced(self, tmp_path: Path):
        """Oversized streamed download must be cut off."""
        archive, manifest = _make_archive_and_manifest(tmp_path)

        # Mock urlopen to return more data than manifest says
        class FakeResp:
            url = manifest["download_url"]
            headers = {"Content-Length": str(manifest["byte_size"] * 10)}

            def read(self, n):
                return b"x" * n

            def close(self):
                pass

        dest = tmp_path / "dl.tar.gz"
        with (
            mock.patch("urllib.request.urlopen", return_value=FakeResp()),
            pytest.raises(lmr.InstallError, match="[Bb]yte cap|Content-Length"),
        ):
            lmr._download_with_checks(manifest["download_url"], dest, manifest)

    def test_download_redirect_to_evil_host_rejected(self, tmp_path: Path):
        """Redirect to an untrusted host must be rejected."""
        archive, manifest = _make_archive_and_manifest(tmp_path)

        class FakeResp:
            url = "https://evil.com/bad"
            headers = {}

            def read(self, n):
                return b""

            def close(self):
                pass

        dest = tmp_path / "dl.tar.gz"
        with (
            mock.patch("urllib.request.urlopen", return_value=FakeResp()),
            pytest.raises(lmr.InstallError, match="untrusted|redirect"),
        ):
            lmr._download_with_checks(manifest["download_url"], dest, manifest)


# ===================================================================
# LOCAL --archive MUST REQUIRE MANIFEST
# ===================================================================


class TestLocalArchiveRequiresManifest:
    """Local --archive install must always require a trusted manifest."""

    def test_cli_requires_manifest_flag(self):
        """The --manifest flag is required for install subcommand."""
        parser = lmr.build_parser()
        # install without --manifest should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["install", "--target", "/tmp/t", "--archive", "/tmp/a.tar.gz"])


# ===================================================================
# CLI TESTS
# ===================================================================


class TestCLI:
    """CLI entry-point smoke tests."""

    def test_package_subcommand_exists(self):
        parser = lmr.build_parser()
        args = parser.parse_args(
            ["package", "--library", "/tmp/lib", "--output", "/tmp/out.tar.gz"]
        )
        assert args.command == "package"

    def test_install_subcommand_exists(self):
        parser = lmr.build_parser()
        args = parser.parse_args(
            ["install", "--target", "/tmp/target", "--manifest", "/tmp/m.json"]
        )
        assert args.command == "install"

    def test_install_with_archive_flag(self):
        parser = lmr.build_parser()
        args = parser.parse_args(
            [
                "install",
                "--target",
                "/tmp/t",
                "--archive",
                "/tmp/a.tar.gz",
                "--manifest",
                "/tmp/m.json",
            ]
        )
        assert args.archive == "/tmp/a.tar.gz"
