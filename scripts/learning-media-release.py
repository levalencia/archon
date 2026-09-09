#!/usr/bin/env python3
"""learning-media-release.py – Package and install Archon rich Visual Learning media.

A standard-library-only CLI for creating deterministic, checksummed tar.gz
archives of the rich media library and securely installing them from GitHub
Release assets or local files.

Subcommands:
    package   Create a deterministic archive from the external library.
    install   Install an archive to the local media directory.

Usage:
    python3 scripts/learning-media-release.py package \\
        --library /path/to/archon-learning-media \\
        --output archon-learning-media-v<tag>.tar.gz

    python3 scripts/learning-media-release.py install \\
        --target /path/to/archon-learning-media \\
        --manifest release-manifest.json \\
        [--archive local.tar.gz]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_NAME = "archon.learning-library"
MANIFEST_SCHEMA_VERSION = 1
MARKER_FILE = ".archon-learning-library"
MARKER_CONTENT = "archon.learning-library/v1\n"
ALLOWED_TOP_LEVEL = {MARKER_FILE, "catalog.json", "published"}
REPO_SLUG = "levalencia/archon"

# Size bounds
MIN_ARCHIVE_SIZE = 100  # bytes – smallest plausible archive
MAX_ARCHIVE_SIZE = 2 * 1024**3  # 2 GiB
MAX_ARCHIVE_MEMBERS = 50_000
MAX_MEMBER_UNCOMPRESSED = 500 * 1024**2  # 500 MiB per member
MAX_TOTAL_UNCOMPRESSED = 4 * 1024**3  # 4 GiB cumulative
MAX_DOWNLOAD_BYTES = MAX_ARCHIVE_SIZE  # hard running cap for HTTPS
MAX_INPUT_SCAN_BYTES = 4 * 1024**3  # cumulative input size during packaging

HASH_CHUNK = 1 << 16  # 64 KiB streaming hash chunk

# Deterministic tar settings
TAR_MTIME = 0
TAR_UID = 0
TAR_GID = 0
TAR_UNAME = "root"
TAR_GNAME = "root"
DIR_MODE = 0o755
FILE_MODE = 0o644

_ALLOWED_HOST_PREFIX = "https://github.com/levalencia/archon/releases/download/"
_ALLOWED_REDIRECT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class PackageError(Exception):
    """Raised when packaging validation fails."""


class InstallError(Exception):
    """Raised when installation validation fails."""


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------
def validate_manifest(manifest: dict[str, Any]) -> None:
    """Validate release manifest schema before any network/file work.

    Checks: schema_version, positive byte_size, 64-hex archive_sha256,
    40-hex source_commit, tag/asset naming, and download URL format.
    """
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InstallError(
            f"Manifest schema_version must be {MANIFEST_SCHEMA_VERSION}, "
            f"got {manifest.get('schema_version')!r}"
        )

    # byte_size – positive integer
    bs = manifest.get("byte_size")
    if not isinstance(bs, int) or bs <= 0:
        raise InstallError(f"Manifest byte_size must be a positive integer, got {bs!r}")
    if not MIN_ARCHIVE_SIZE <= bs <= MAX_ARCHIVE_SIZE:
        raise InstallError(
            f"Manifest byte_size must be between {MIN_ARCHIVE_SIZE} and "
            f"{MAX_ARCHIVE_SIZE}, got {bs}"
        )

    # archive_sha256 – exactly 64 hex chars
    sha = manifest.get("archive_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise InstallError("Manifest archive_sha256 must be 64 lowercase hex chars")

    # source_commit – full 40-hex
    commit = manifest.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise InstallError("Manifest source_commit must be a full 40-hex SHA")

    # tag / asset relationship
    tag = manifest.get("release_tag")
    asset = manifest.get("asset_name")
    if not isinstance(tag, str) or not tag:
        raise InstallError("Manifest release_tag is required")
    if not isinstance(asset, str) or not asset:
        raise InstallError("Manifest asset_name is required")

    short = commit[:12]
    expected_tag = f"learning-media-{short}"
    expected_asset = f"archon-learning-media-{short}.tar.gz"
    if tag != expected_tag:
        raise InstallError(f"Manifest release_tag must be {expected_tag!r}, got {tag!r}")
    if asset != expected_asset:
        raise InstallError(f"Manifest asset_name must be {expected_asset!r}, got {asset!r}")

    # download_url – exactly right pattern
    url = manifest.get("download_url")
    expected_url = f"https://github.com/{REPO_SLUG}/releases/download/{tag}/{asset}"
    if url != expected_url:
        raise InstallError(f"Manifest download_url must be {expected_url!r}, got {url!r}")


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------
def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file by streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_relative_published(file_path: str, label: str = "file") -> None:
    """Validate that *file_path* is a relative ``published/...`` path with no
    traversal or absolute components."""
    if not file_path:
        raise PackageError(f"{label}: empty path")
    p = Path(file_path)
    if p.is_absolute():
        raise PackageError(f"{label}: absolute path not allowed: {file_path}")
    parts = p.parts
    if ".." in parts:
        raise PackageError(f"{label}: path traversal not allowed: {file_path}")
    if parts[0] != "published":
        raise PackageError(f"{label}: artifact must be under published/, got {file_path}")


# ---------------------------------------------------------------------------
# Catalog validation
# ---------------------------------------------------------------------------
def validate_catalog(
    catalog: dict[str, Any],
    library_root: Path,
    *,
    expected_source_commit: str | None = None,
) -> None:
    """Validate catalog schema, source commit, and artifact checksums."""
    if catalog.get("schema") != SCHEMA_NAME:
        raise PackageError(
            f"Invalid catalog schema: expected {SCHEMA_NAME!r}, got {catalog.get('schema')!r}"
        )

    version = catalog.get("version")
    if version != 1:
        raise PackageError(f"Catalog version must be 1, got {version!r}")

    commit = catalog.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PackageError(f"Catalog source_commit must be 40-hex, got {commit!r}")
    if expected_source_commit is not None and commit != expected_source_commit:
        raise PackageError(
            f"Catalog source_commit mismatch: expected {expected_source_commit}, got {commit!r}"
        )

    packs = catalog.get("packs")
    if not isinstance(packs, list) or len(packs) == 0:
        raise PackageError("Catalog must have a non-empty 'packs' list")

    for pack in packs:
        artifacts = pack.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) == 0:
            raise PackageError(f"Pack {pack.get('id', '?')!r} must have non-empty artifacts")
        for art in artifacts:
            file_path = art.get("file", "")
            _safe_relative_published(file_path, label=f"artifact {art.get('id', '?')}")

            fpath = library_root / file_path
            resolved = fpath.resolve()
            root_resolved = library_root.resolve()
            # Containment
            if not resolved.is_relative_to(root_resolved):
                raise PackageError(f"Artifact escapes library root: {file_path}")
            # Must exist, be regular, not symlink
            if not fpath.exists():
                raise PackageError(f"Artifact file not found: {file_path}")
            if fpath.is_symlink():
                raise PackageError(f"Artifact is a symlink: {file_path}")
            if not fpath.is_file():
                raise PackageError(f"Artifact is not a regular file: {file_path}")

            # SHA-256 via streaming
            expected_sha = art.get("sha256")
            if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
                raise PackageError(f"Artifact {art.get('id', '?')}: sha256 must be 64 hex chars")
            actual = _sha256_file(fpath)
            if actual != expected_sha:
                raise PackageError(
                    f"Artifact sha256 mismatch for {file_path}: "
                    f"expected {expected_sha}, got {actual}"
                )

            # content_file if present
            cf = art.get("content_file")
            if cf is not None:
                _safe_relative_published(cf, label=f"content_file of {art.get('id', '?')}")
                cfp = library_root / cf
                if not cfp.resolve().is_relative_to(root_resolved):
                    raise PackageError(f"content_file escapes library root: {cf}")
                if not cfp.exists() or cfp.is_symlink() or not cfp.is_file():
                    raise PackageError(f"content_file missing or invalid: {cf}")
                cf_sha = art.get("content_sha256")
                if not isinstance(cf_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", cf_sha):
                    raise PackageError(f"content_file {cf}: content_sha256 must be 64 hex chars")
                if _sha256_file(cfp) != cf_sha:
                    raise PackageError(f"content_file checksum mismatch: {cf}")


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------
def scan_for_irregular_files(library_root: Path) -> None:
    """Reject irregular files in the release payload only."""
    required_files = (library_root / MARKER_FILE, library_root / "catalog.json")
    for path in required_files:
        if not path.exists() or path.is_symlink() or not path.is_file():
            raise PackageError(f"Required release file is missing or irregular: {path}")
    if (library_root / MARKER_FILE).read_text(encoding="utf-8") != MARKER_CONTENT:
        raise PackageError("learning-media ownership marker is invalid")
    published = library_root / "published"
    if not published.exists() or published.is_symlink() or not published.is_dir():
        raise PackageError("published/ is missing or irregular")

    for dirpath, dirnames, filenames in os.walk(published):
        dp = Path(dirpath)
        for name in filenames:
            fp = dp / name
            if fp.is_symlink():
                raise PackageError(f"Symlink found (non-regular file): {fp}")
            st = fp.lstat()
            if not stat.S_ISREG(st.st_mode):
                raise PackageError(f"non-regular file found: {fp}")
        for name in dirnames:
            dp2 = dp / name
            if dp2.is_symlink():
                raise PackageError(f"Symlink found (non-regular file): {dp2}")


# ---------------------------------------------------------------------------
# Deterministic archive creation
# ---------------------------------------------------------------------------
def _collect_entries(library_root: Path) -> list[tuple[str, Path | None]]:
    """Collect archive entries: only marker, catalog.json, published/**."""
    entries: list[tuple[str, Path | None]] = []

    # Marker file
    entries.append((MARKER_FILE, library_root / MARKER_FILE))
    # catalog.json
    entries.append(("catalog.json", library_root / "catalog.json"))

    # published/ tree – sorted walk
    pub = library_root / "published"
    if pub.is_dir():
        for dirpath, dirnames, filenames in os.walk(pub):
            dirnames.sort()
            rel = Path(dirpath).relative_to(library_root)
            entries.append((str(rel), None))  # directory
            for fn in sorted(filenames):
                fp = Path(dirpath) / fn
                entries.append((str(rel / fn), fp))

    return entries


def create_archive(
    library_root: Path,
    output_path: Path,
    source_commit: str,
) -> dict[str, Any]:
    """Create a deterministic tar.gz archive and return the release manifest."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise PackageError("source_commit must be a full 40-hex SHA")
    library_root = library_root.resolve()
    output_path = output_path.resolve()
    if output_path.is_relative_to(library_root):
        raise PackageError("archive output must be outside the media library")

    # Validate first
    catalog_path = library_root / "catalog.json"
    if not catalog_path.exists():
        raise PackageError("catalog.json not found in library root")
    catalog = json.loads(catalog_path.read_text())
    validate_catalog(
        catalog,
        library_root,
        expected_source_commit=source_commit,
    )

    marker_path = library_root / MARKER_FILE
    if not marker_path.exists():
        raise PackageError(f"{MARKER_FILE} not found in library root")

    scan_for_irregular_files(library_root)

    # Collect entries in stable order
    entries = _collect_entries(library_root)

    # mkdir output parent
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Stream files into tar directly (no full BytesIO accumulation)
    # We write tar -> gzip -> file in streaming fashion.
    cumulative_input = 0

    fd, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with (
            open(temporary_path, "wb") as out_f,
            gzip.GzipFile(filename="", fileobj=out_f, mode="wb", mtime=0) as gf,
            tarfile.open(fileobj=gf, mode="w") as tf,
        ):
            for arcname, real_path in entries:
                if real_path is None:
                    # Directory entry
                    info = tarfile.TarInfo(name=arcname)
                    info.type = tarfile.DIRTYPE
                    info.mode = DIR_MODE
                    info.size = 0
                else:
                    fsize = real_path.stat().st_size
                    cumulative_input += fsize
                    if cumulative_input > MAX_INPUT_SCAN_BYTES:
                        raise PackageError(
                            f"Cumulative input size exceeds {MAX_INPUT_SCAN_BYTES} bytes"
                        )
                    info = tarfile.TarInfo(name=arcname)
                    info.size = fsize
                    info.mode = FILE_MODE

                info.mtime = TAR_MTIME
                info.uid = TAR_UID
                info.gid = TAR_GID
                info.uname = TAR_UNAME
                info.gname = TAR_GNAME

                if real_path is not None:
                    with open(real_path, "rb") as rf:
                        tf.addfile(info, rf)
                else:
                    tf.addfile(info)
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    archive_sha = _sha256_file(output_path)
    byte_size = output_path.stat().st_size
    if not MIN_ARCHIVE_SIZE <= byte_size <= MAX_ARCHIVE_SIZE:
        output_path.unlink(missing_ok=True)
        raise PackageError(
            f"Archive size must be between {MIN_ARCHIVE_SIZE} and {MAX_ARCHIVE_SIZE} bytes"
        )

    short = source_commit[:12]
    tag = f"learning-media-{short}"
    asset_name = f"archon-learning-media-{short}.tar.gz"

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "release_tag": tag,
        "source_commit": source_commit,
        "asset_name": asset_name,
        "download_url": f"https://github.com/{REPO_SLUG}/releases/download/{tag}/{asset_name}",
        "byte_size": byte_size,
        "archive_sha256": archive_sha,
    }
    return manifest


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------
def _verify_archive(archive_path: Path, manifest: dict[str, Any]) -> None:
    """Verify size and SHA-256 of archive before extraction."""
    actual_size = archive_path.stat().st_size

    # Size bounds first, before hashing
    if actual_size > MAX_ARCHIVE_SIZE:
        raise InstallError(f"Archive exceeds maximum size ({MAX_ARCHIVE_SIZE})")
    if actual_size < MIN_ARCHIVE_SIZE:
        raise InstallError(f"Archive smaller than minimum size ({MIN_ARCHIVE_SIZE})")

    expected_size = manifest["byte_size"]
    if actual_size != expected_size:
        raise InstallError(f"Archive size mismatch: expected {expected_size}, got {actual_size}")

    # Hash streaming
    actual_sha = _sha256_file(archive_path)
    expected_sha = manifest["archive_sha256"]
    if actual_sha != expected_sha:
        raise InstallError(
            f"Archive SHA-256 checksum mismatch: expected {expected_sha}, got {actual_sha}"
        )


def _validate_tar_members_streaming(tf: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Stream/iterate tar members one-by-one without getmembers().

    Enforces per-member size, cumulative uncompressed size, member count,
    duplicate names, path security, and type restrictions.
    Returns the validated member list.
    """
    members: list[tarfile.TarInfo] = []
    seen_names: set[str] = set()
    cumulative_uncompressed = 0
    for count, member in enumerate(tf, start=1):
        if count > MAX_ARCHIVE_MEMBERS:
            raise InstallError(f"Archive has excessive members (>{MAX_ARCHIVE_MEMBERS})")

        name = member.name
        # Reject absolute paths
        if name.startswith("/"):
            raise InstallError(f"Absolute path in archive: {name}")
        # Reject traversal
        if ".." in name.split("/"):
            raise InstallError(f"Path traversal in archive: {name}")

        # Reject links and devices
        if member.issym() or member.islnk():
            raise InstallError(f"Link entry in archive: {name} (type forbidden)")
        if member.ischr() or member.isblk() or member.isfifo():
            raise InstallError(f"Device/FIFO entry in archive: {name} (type forbidden)")

        # Only files and dirs
        if not member.isreg() and not member.isdir():
            raise InstallError(f"Unexpected member type in archive: {name}")

        # Check top-level path is allowed
        top = name.split("/")[0]
        if top not in ALLOWED_TOP_LEVEL:
            raise InstallError(
                f"Unexpected top-level path in archive: {top!r} (allowed: {ALLOWED_TOP_LEVEL})"
            )

        # Duplicate names
        if name in seen_names:
            raise InstallError(f"Duplicate member name in archive: {name}")
        seen_names.add(name)

        # Per-member size
        if member.isreg() and member.size > MAX_MEMBER_UNCOMPRESSED:
            raise InstallError(
                f"Member {name} exceeds per-member size cap "
                f"({member.size} > {MAX_MEMBER_UNCOMPRESSED})"
            )

        # Cumulative uncompressed size
        if member.isreg():
            cumulative_uncompressed += member.size
            if cumulative_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                raise InstallError(
                    f"Cumulative uncompressed size exceeds cap ({MAX_TOTAL_UNCOMPRESSED})"
                )

        members.append(member)

    return members


def _ensure_outside_repo_root(target: Path) -> None:
    """Refuse to install inside the repository root (script's own repo)."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent  # scripts/ -> repo root
    target_resolved = target.resolve()
    repo_resolved = repo_root.resolve()
    if target_resolved == repo_resolved or str(target_resolved).startswith(
        str(repo_resolved) + os.sep
    ):
        raise InstallError(
            f"Install target must be outside the repository root "
            f"({repo_resolved}), got {target_resolved}"
        )


def install_archive(
    archive_path: Path,
    target: Path,
    manifest: dict[str, Any],
) -> None:
    """Securely install a media archive to *target*.

    - Validates manifest schema before any work.
    - Verifies size and SHA-256 before extraction.
    - Rejects hostile tar entries (absolute, traversal, links, devices).
    - Enforces per-member and cumulative uncompressed size caps.
    - Extracts to a temp sibling, then atomically replaces *target*.
    - Refuses to overwrite non-empty target without ownership marker.
    - Enforces target is outside repository root.
    """
    validate_manifest(manifest)
    _ensure_outside_repo_root(target)
    _verify_archive(archive_path, manifest)

    # Check target
    if target.is_symlink():
        raise InstallError(f"Install target must not be a symlink: {target}")
    if target.exists() and not target.is_dir():
        raise InstallError(f"Install target must be a directory: {target}")
    if target.exists() and not (target / MARKER_FILE).exists() and any(target.iterdir()):
        raise InstallError(
            f"Non-empty unowned target directory: {target}. Missing {MARKER_FILE} marker."
        )

    # Extract to temp sibling
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=parent, prefix=".media-install-"))

    try:
        with tarfile.open(archive_path, "r:gz") as tf:
            members = _validate_tar_members_streaming(tf)

            # Safe extract after validation
            for member in members:
                if member.isdir():
                    (staging / member.name).mkdir(parents=True, exist_ok=True)
                elif member.isreg():
                    dest = staging / member.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    source = tf.extractfile(member)
                    if source is None:
                        raise InstallError(f"Unable to read archive member: {member.name}")
                    with source, open(dest, "wb") as output:
                        shutil.copyfileobj(source, output, length=HASH_CHUNK)

        # Validate extracted content
        if not (staging / MARKER_FILE).exists():
            raise InstallError("Extracted archive missing marker file")
        if (staging / MARKER_FILE).read_text(encoding="utf-8") != MARKER_CONTENT:
            raise InstallError("Extracted archive has an invalid ownership marker")
        if not (staging / "catalog.json").exists():
            raise InstallError("Extracted archive missing catalog.json")

        # Validate catalog via the same validator, translate PackageError
        catalog = json.loads((staging / "catalog.json").read_text())
        try:
            validate_catalog(
                catalog,
                staging,
                expected_source_commit=manifest["source_commit"],
            )
        except PackageError as exc:
            raise InstallError(f"Post-extraction catalog validation failed: {exc}") from exc

        # Atomic replace with unique sibling backup
        if target.exists():
            backup_name = f"{target.name}.old-{uuid.uuid4().hex[:8]}"
            backup = target.with_name(backup_name)
            target.rename(backup)
            try:
                staging.rename(target)
                shutil.rmtree(backup)
            except Exception:
                # Restore from backup
                if not target.exists() and backup.exists():
                    backup.rename(target)
                raise
        else:
            staging.rename(target)

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _download_with_checks(
    url: str,
    dest_path: Path,
    manifest: dict[str, Any],
) -> None:
    """Stream HTTPS download with Content-Length check and running byte cap.

    Rejects redirects/final URLs outside github.com/levalencia/archon/releases/download/.
    """
    if not url.startswith(_ALLOWED_HOST_PREFIX):
        raise InstallError(f"Download URL not in allowed prefix: {url!r}")

    req = urllib.request.Request(url)
    response = urllib.request.urlopen(req)  # noqa: S310
    try:
        final_url = response.url
        parsed = urllib.parse.urlparse(final_url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_REDIRECT_HOSTS:
            raise InstallError(f"Download redirected to untrusted host: {final_url!r}")

        content_length_header = response.headers.get("Content-Length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
            except ValueError as exc:
                raise InstallError("Download returned an invalid Content-Length") from exc
            if content_length != manifest["byte_size"]:
                raise InstallError(
                    f"Content-Length {content_length} does not match "
                    f"manifest byte_size {manifest['byte_size']}"
                )

        running = 0
        max_bytes = min(MAX_DOWNLOAD_BYTES, manifest["byte_size"])
        with open(dest_path, "wb") as output:
            while chunk := response.read(HASH_CHUNK):
                running += len(chunk)
                if running > max_bytes:
                    raise InstallError(f"Download exceeded byte cap ({max_bytes})")
                output.write(chunk)
        if running != manifest["byte_size"]:
            raise InstallError(
                f"Downloaded size {running} does not match manifest byte_size "
                f"{manifest['byte_size']}"
            )
    finally:
        response.close()


def install_from_manifest(
    manifest: dict[str, Any],
    target: Path,
    archive_path: Path | None = None,
) -> None:
    """Install from a release manifest, downloading if needed.

    Always requires a trusted manifest; local --archive never self-computes
    trust data.
    """
    validate_manifest(manifest)
    _ensure_outside_repo_root(target)

    if archive_path is not None:
        install_archive(archive_path, target, manifest)
        return

    url = manifest["download_url"]
    # Download to temp file
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tar.gz")
    try:
        os.close(fd)
        _download_with_checks(url, Path(tmp), manifest)
        install_archive(Path(tmp), target, manifest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="learning-media-release",
        description="Package and install Archon rich Visual Learning media.",
    )
    sub = parser.add_subparsers(dest="command")

    # package
    pkg = sub.add_parser("package", help="Create a deterministic archive.")
    pkg.add_argument(
        "--library",
        required=True,
        help="Path to the external media library root.",
    )
    pkg.add_argument(
        "--output",
        required=True,
        help="Output path for the .tar.gz archive.",
    )
    pkg.add_argument(
        "--manifest-output",
        help="Path to write the release manifest JSON.",
    )

    # install
    inst = sub.add_parser("install", help="Install media archive.")
    inst.add_argument(
        "--target",
        required=True,
        help="Target directory for installation.",
    )
    inst.add_argument(
        "--archive",
        help="Path to a local .tar.gz archive (offline mode).",
    )
    inst.add_argument(
        "--manifest",
        required=True,
        help="Path to a release manifest JSON file (always required).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "package":
        library = Path(args.library).resolve()
        output = Path(args.output).resolve()
        catalog = json.loads((library / "catalog.json").read_text(encoding="utf-8"))
        manifest = create_archive(
            library,
            output,
            str(catalog.get("source_commit", "")),
        )
        print(f"Archive: {output} ({manifest['byte_size']} bytes)")
        print(f"SHA-256: {manifest['archive_sha256']}")
        print(f"Tag:     {manifest['release_tag']}")
        if args.manifest_output:
            mpath = Path(args.manifest_output)
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(json.dumps(manifest, indent=2) + "\n")
            print(f"Manifest: {mpath}")
        else:
            print(json.dumps(manifest, indent=2))
        return 0

    elif args.command == "install":
        target = Path(args.target).resolve()
        manifest = json.loads(Path(args.manifest).read_text())
        if args.archive:
            archive = Path(args.archive).resolve()
            install_from_manifest(manifest, target, archive_path=archive)
        else:
            install_from_manifest(manifest, target)

        print(f"Installed to: {target}")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
