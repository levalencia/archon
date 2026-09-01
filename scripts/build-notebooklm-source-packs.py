#!/usr/bin/env python3
"""Build sanitized, provenance-preserving NotebookLM source packs outside the repo."""

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
CONFIG = ROOT / "docs/visual-learning/notebooklm-sources.yaml"
DEFAULT_OUTPUT = ROOT.parent / "archon-notebooklm" / "source-packs"
ALLOWED_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt"}
FORBIDDEN_PARTS = {".env", ".git", "auth.json", "storage_state.json", "secrets"}
OWNER_MARKER = ".archon-notebooklm-packs.json"
OWNER_SCHEMA = "archon.notebooklm-pack-directory/v1"
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:ENCRYPTED |RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
    r"|-----BEGIN PGP PRIVATE KEY BLOCK-----"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"
)
CLOUD_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

TRUTH_BOUNDARIES = """# Archon source priority and truth boundaries

This notebook contains public, repository-grounded Archon learning material.

## Source priority

1. `docs/IMPLEMENTATION-EVIDENCE.md` for current capability claims.
2. `docs/implementation/CAPABILITY-ACCEPTANCE.yaml` for machine-readable acceptance.
3. `docs/REMAINING-DEFERRED-GAPS.md` for incomplete or deferred boundaries.
4. `docs/ARCHITECTURE-DIAGRAMS.md` for system structure.
5. Course modules and concept pages for teaching explanations.

## Never infer

- Local deployment is not public production deployment.
- Process health or dependency readiness is not proof of useful model behavior.
- Deterministic mock output is not live provider inference.
- Provider-live embeddings are not inferred from configuration; cite them only when the evidence source records an executed live acceptance.
- Native provider JSON Schema parity is not claimed; Archon applies strict local validation.
- OTEL debug/stdout export is not a Jaeger or Azure Monitor deployment.
- Approval-gated optimization is not autonomous production mutation.
- Code existence is not automatically runtime or user-facing evidence.

If sources appear to disagree, preserve the more conservative claim and cite the evidence or deferred-gap source.
"""


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def _require_clean_repo() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("NotebookLM packs require a clean repository")


def _scan_source(source: Path, raw: str) -> None:
    text = source.read_text(encoding="utf-8")
    if PRIVATE_KEY_PATTERN.search(text):
        raise ValueError(f"private-key marker in NotebookLM source: {raw}")
    if JWT_PATTERN.search(text) or CLOUD_KEY_PATTERN.search(text):
        raise ValueError(f"credential-like value in NotebookLM source: {raw}")


def _safe_source(raw: str) -> Path:
    relative = Path(raw)
    if relative.is_absolute() or any(
        part in FORBIDDEN_PARTS for part in relative.parts
    ):
        raise ValueError(f"unsafe NotebookLM source path: {raw}")
    candidate = ROOT / relative
    if candidate.is_symlink():
        raise ValueError(f"symlinked NotebookLM source is not allowed: {raw}")
    source = candidate.resolve()
    if ROOT not in source.parents or not source.is_file():
        raise ValueError(f"missing or escaping NotebookLM source: {raw}")
    if source.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported NotebookLM source type: {raw}")
    try:
        _git("ls-files", "--error-unmatch", "--", relative.as_posix())
    except subprocess.CalledProcessError as error:
        raise ValueError(
            f"untracked NotebookLM source is not allowed: {raw}"
        ) from error
    _scan_source(source, raw)
    return source


def _safe_filename(index: int, raw: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return f"{index:02d}-{stem}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    return _git("rev-parse", "HEAD")


def _validated_output_path(raw: Path) -> Path:
    candidate = raw.expanduser().absolute()
    for part in (candidate, *candidate.parents):
        if part.is_symlink():
            raise ValueError("NotebookLM output path cannot contain symlinks")
    output = candidate.resolve(strict=False)
    home = Path.home().resolve()
    if (
        output == Path(output.anchor)
        or output == home
        or output == ROOT
        or ROOT in output.parents
        or output in ROOT.parents
    ):
        raise ValueError("unsafe NotebookLM output directory")
    if output.exists() and not output.is_dir():
        raise ValueError("NotebookLM output path must be a directory")
    entries = list(output.iterdir()) if output.exists() else []
    if entries:
        marker = output / OWNER_MARKER
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("refusing non-empty unowned NotebookLM output directory")
        try:
            marker_schema = json.loads(marker.read_text(encoding="utf-8")).get("schema")
        except (OSError, ValueError, TypeError):
            marker_schema = None
        if marker_schema != OWNER_SCHEMA:
            raise ValueError("invalid NotebookLM output ownership marker")
    return output


def _publish_tree(staging: Path, output: Path) -> None:
    backup: Path | None = None
    try:
        if output.exists():
            backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
            output.rename(backup)
        staging.rename(output)
        if backup is not None:
            shutil.rmtree(backup)
    except Exception:
        if not output.exists() and backup is not None and backup.exists():
            backup.rename(output)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def build_packs(output_dir: Path, *, require_clean: bool = True) -> dict[str, Any]:
    if require_clean:
        _require_clean_repo()
    output_dir = _validated_output_path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    notebooks = config.get("notebooks", [])
    ids = [item["id"] for item in notebooks]
    if len(ids) != len(set(ids)) or not notebooks:
        raise ValueError("NotebookLM notebook IDs must be unique and non-empty")

    staging_dir = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.staging-", dir=output_dir.parent)
    )
    manifest: dict[str, Any] = {
        "schema": "archon.notebooklm-source-packs",
        "version": 1,
        "source_commit": _git_head(),
        "source_config": str(CONFIG.relative_to(ROOT)),
        "notebooks": [],
    }

    for notebook in notebooks:
        notebook_dir = staging_dir / notebook["id"]
        if notebook_dir.exists():
            shutil.rmtree(notebook_dir)
        notebook_dir.mkdir(parents=True)
        truth_path = notebook_dir / "00-ARCHON-TRUTH-BOUNDARIES.md"
        truth_path.write_text(TRUTH_BOUNDARIES, encoding="utf-8")
        files = [
            {
                "upload_file": truth_path.name,
                "canonical_source": "generated truth boundaries",
                "sha256": _sha256(truth_path),
            }
        ]
        selected_sources = list(
            dict.fromkeys(
                config.get("source_priority", []) + notebook.get("sources", [])
            )
        )
        for index, raw in enumerate(selected_sources, start=1):
            source = _safe_source(raw)
            destination = notebook_dir / _safe_filename(index, raw)
            shutil.copyfile(source, destination)
            files.append(
                {
                    "upload_file": destination.name,
                    "canonical_source": raw,
                    "sha256": _sha256(destination),
                }
            )
        guide = notebook_dir / "UPLOAD-README.md"
        guide.write_text(
            "# Upload this folder to NotebookLM\n\n"
            f"Notebook title: **{notebook['title']}**\n\n"
            f"Purpose: {notebook['purpose']}\n\n"
            "Upload `00-ARCHON-TRUTH-BOUNDARIES.md` first, then every numbered source file. "
            "Do not upload this README as a source. Use the repository promptbook to generate artifacts.\n",
            encoding="utf-8",
        )
        manifest["notebooks"].append(
            {
                "id": notebook["id"],
                "title": notebook["title"],
                "purpose": notebook["purpose"],
                "artifacts": notebook["artifacts"],
                "directory": notebook_dir.name,
                "files": files,
            }
        )

    manifest_path = staging_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (staging_dir / OWNER_MARKER).write_text(
        json.dumps({"schema": OWNER_SCHEMA}, indent=2) + "\n", encoding="utf-8"
    )
    _publish_tree(staging_dir, output_dir)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build_packs(args.output_dir)
    print(
        f"Built {len(manifest['notebooks'])} NotebookLM source packs at "
        f"{args.output_dir.expanduser().resolve()}"
    )


if __name__ == "__main__":
    main()
