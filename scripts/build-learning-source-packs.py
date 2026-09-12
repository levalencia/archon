#!/usr/bin/env python3
"""Build sanitized, provenance-preserving source packs for Hermes learning jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/visual-learning/learning-artifacts.yaml"
DEFAULT_OUTPUT = ROOT.parent / "cogentrex-learning-media" / "source-packs"
OWNER_MARKER = ".cogentrex-learning-source-packs.json"
OWNER_SCHEMA = "cogentrex.learning-pack-directory/v1"
ALLOWED_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt"}
FORBIDDEN_PARTS = {".env", ".git", "auth.json", "storage_state.json", "secrets"}
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:ENCRYPTED |RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|-----BEGIN PGP PRIVATE KEY BLOCK-----"
)
JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b")
CLOUD_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

TRUTH_BOUNDARIES = """# Cogentrex source priority and truth boundaries

This pack contains public, repository-grounded Cogentrex learning material for Hermes.
All generated learner-facing content must be English.

1. IMPLEMENTATION-EVIDENCE is the current capability record.
2. CAPABILITY-ACCEPTANCE is the machine-readable acceptance record.
3. REMAINING-DEFERRED-GAPS records incomplete boundaries.
4. ARCHITECTURE-DIAGRAMS describes system structure.
5. Course pages provide teaching explanations.

Never infer public deployment from local deployment, live-provider behavior from mocks,
readiness from process health, or implementation from a generated learning artifact.
"""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def _safe_source(raw: str) -> Path:
    relative = Path(raw)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(part in FORBIDDEN_PARTS for part in relative.parts)
    ):
        raise ValueError(f"unsafe learning source path: {raw}")
    candidate = ROOT / relative
    if candidate.is_symlink():
        raise ValueError(f"symlinked learning source is not allowed: {raw}")
    source = candidate.resolve()
    if ROOT not in source.parents or not source.is_file():
        raise ValueError(f"missing or escaping learning source: {raw}")
    if source.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported learning source type: {raw}")
    try:
        _git("ls-files", "--error-unmatch", "--", relative.as_posix())
    except subprocess.CalledProcessError as error:
        raise ValueError(f"untracked learning source is not allowed: {raw}") from error
    text = source.read_text(encoding="utf-8")
    if (
        PRIVATE_KEY_PATTERN.search(text)
        or JWT_PATTERN.search(text)
        or CLOUD_KEY_PATTERN.search(text)
    ):
        raise ValueError(f"credential-like value in learning source: {raw}")
    return source


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output(raw: Path) -> Path:
    candidate = raw.expanduser().absolute()
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError("learning-pack output path cannot contain symlinks")
    output = candidate.resolve(strict=False)
    home = Path.home().resolve()
    if (
        output in {Path(output.anchor), home, ROOT}
        or ROOT in output.parents
        or output in ROOT.parents
    ):
        raise ValueError("unsafe learning-pack output directory")
    if output.exists() and not output.is_dir():
        raise ValueError("learning-pack output path must be a directory")
    if output.exists() and any(output.iterdir()):
        marker = output / OWNER_MARKER
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("refusing non-empty unowned learning-pack directory")
        try:
            schema = json.loads(marker.read_text(encoding="utf-8")).get("schema")
        except (OSError, ValueError, TypeError):
            schema = None
        if schema != OWNER_SCHEMA:
            raise ValueError("invalid learning-pack ownership marker")
    return output


def build_packs(output_dir: Path, *, require_clean: bool = True) -> dict[str, Any]:
    if require_clean and _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("learning packs require a clean repository")
    output_dir = _output(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    packs = config.get("packs", [])
    ids = [item["id"] for item in packs]
    if not packs or len(ids) != len(set(ids)):
        raise ValueError("learning-pack IDs must be unique and non-empty")
    if config.get("language") != "en" or any(pack.get("language") != "en" for pack in packs):
        raise ValueError("all learning packs must use English")

    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent))
    manifest: dict[str, Any] = {
        "schema": "cogentrex.learning-source-packs",
        "version": 1,
        "language": "en",
        "source_commit": _git("rev-parse", "HEAD"),
        "source_config": str(CONFIG.relative_to(ROOT)),
        "packs": [],
    }
    try:
        for pack in packs:
            pack_dir = staging / pack["id"]
            pack_dir.mkdir(parents=True)
            truth = pack_dir / "00-COGENTREX-TRUTH-BOUNDARIES.md"
            truth.write_text(TRUTH_BOUNDARIES, encoding="utf-8")
            files = [
                {
                    "file": truth.name,
                    "source": "generated truth boundaries",
                    "sha256": _sha256(truth),
                }
            ]
            sources = list(
                dict.fromkeys(config.get("source_priority", []) + pack.get("sources", []))
            )
            for index, raw in enumerate(sources, 1):
                source = _safe_source(raw)
                name = f"{index:02d}-" + re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
                target = pack_dir / name
                shutil.copyfile(source, target)
                files.append({"file": name, "source": raw, "sha256": _sha256(target)})
            manifest["packs"].append(
                {
                    "id": pack["id"],
                    "title": pack["title"],
                    "purpose": pack["purpose"],
                    "language": "en",
                    "artifacts": pack["artifacts"],
                    "files": files,
                }
            )
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (staging / OWNER_MARKER).write_text(
            json.dumps({"schema": OWNER_SCHEMA}) + "\n", encoding="utf-8"
        )
        backup = None
        if output_dir.exists():
            backup = output_dir.parent / f".{output_dir.name}.backup-{uuid.uuid4().hex}"
            output_dir.rename(backup)
        staging.rename(output_dir)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    manifest = build_packs(args.output_dir, require_clean=not args.allow_dirty)
    print(f"Built {len(manifest['packs'])} English learning packs at {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
