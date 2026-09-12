"""Build the curated learning corpus from canonical repo sources and media transcripts."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.learning_media.catalog import LearningMediaCatalog
from app.learning_tutor.sources import (
    LearningSourceInput,
    collect_markdown,
    collect_python,
    collect_text_code,
    collect_video_transcripts,
)

_ALLOWED_PREFIXES = (
    "docs/course/",
    "docs/architecture/",
    "docs/evidence/",
    "docs/operations/",
    "backend/alembic/",
    "backend/app/",
    "backend/tests/",
    "deploy/",
    "frontend/src/",
    "sandbox_runner/",
    "scripts/",
    ".github/workflows/",
)
_ALLOWED_EXACT = {
    "docs/ARCHITECTURE-DIAGRAMS.md",
    "docs/IMPLEMENTATION-EVIDENCE.md",
    "docs/REMAINING-DEFERRED-GAPS.md",
    "docker-compose.local.yml",
}


def collect_learning_corpus(
    *,
    repository_root: str | Path,
    studio_path: str | Path,
    revision: str,
    media_catalog: LearningMediaCatalog | None = None,
    video_artifact_ids: set[str] | None = None,
    include_review_ready: bool = False,
) -> list[LearningSourceInput]:
    """Collect only canonical, explicitly referenced learning material."""
    root = Path(repository_root).resolve()
    studio = json.loads(Path(studio_path).resolve().read_text(encoding="utf-8"))
    if studio.get("schema") != "cogentrex.visual-learning-studio":
        raise ValueError("Visual Learning manifest has an unsupported schema")
    collected: dict[str, LearningSourceInput] = {}

    def add(source: LearningSourceInput, *context_keys: str) -> None:
        contexts = tuple(dict.fromkeys((*source.context_keys, *context_keys)))
        candidate = replace(source, context_keys=contexts)
        current = collected.get(candidate.id)
        if current is not None:
            candidate = replace(
                current,
                context_keys=tuple(dict.fromkeys((*current.context_keys, *contexts))),
            )
        collected[candidate.id] = candidate

    for concept in studio.get("concepts", []):
        if not isinstance(concept, dict) or not concept.get("id"):
            continue
        concept_id = str(concept["id"])
        concept_key = f"concept:{concept_id}"
        visual_text = "\n\n".join(
            str(concept.get(field) or "")
            for field in ("title", "summary", "mental_model", "limitations")
            if concept.get(field)
        )
        add(
            LearningSourceInput(
                kind="visual",
                key=f"visual:{concept_id}",
                title=str(concept.get("title") or concept_id),
                text=visual_text,
                revision=revision,
                locator={
                    "route": "/learn?view=evidence",
                    "concept_id": concept_id,
                },
            ),
            concept_key,
            f"module:{concept.get('module_id')}",
        )
        paths: list[tuple[str, str]] = []
        detail_path = _github_path(concept.get("detail_href"))
        module_path = _github_path(concept.get("module_href"))
        if detail_path:
            paths.append((detail_path, "documentation"))
        if module_path:
            paths.append((module_path, "documentation"))
        for field, kind in (("sources", "code"), ("tests", "test"), ("evidence", "documentation")):
            for entry in concept.get(field, []):
                if isinstance(entry, dict) and entry.get("path"):
                    paths.append((str(entry["path"]), kind))
        for relative, kind in paths:
            for source in _collect_path(root, relative, revision, kind):
                add(source, concept_key, f"module:{concept.get('module_id')}")

    for relative in sorted(_ALLOWED_EXACT):
        path = root / relative
        if path.is_file():
            for source in collect_markdown(path, relative_path=relative, revision=revision):
                add(source, "view:architecture", "view:evidence")

    if media_catalog is not None:
        for source in collect_video_transcripts(
            media_catalog,
            artifact_ids=video_artifact_ids,
            include_review_ready=include_review_ready,
        ):
            add(source)
    return sorted(collected.values(), key=lambda source: (source.kind, source.key))


def _collect_path(root: Path, relative: str, revision: str, kind: str) -> list[LearningSourceInput]:
    relative = relative.replace("\\", "/")
    if relative not in _ALLOWED_EXACT and not relative.startswith(_ALLOWED_PREFIXES):
        raise ValueError(f"Learning source is outside the allowlist: {relative}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Learning source escaped repository root") from exc
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Learning source is missing or unsafe: {relative}")
    if path.suffix.lower() == ".md":
        return collect_markdown(path, relative_path=relative, revision=revision)
    source_kind = "test" if kind == "test" else "code"
    if path.suffix.lower() == ".py":
        return collect_python(
            path,
            relative_path=relative,
            revision=revision,
            kind=source_kind,
        )
    return collect_text_code(
        path,
        relative_path=relative,
        revision=revision,
        kind=source_kind,
    )


def _github_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    marker = "/blob/"
    if marker not in parsed.path:
        return None
    remainder = parsed.path.split(marker, 1)[1]
    if "/" not in remainder:
        return None
    return unquote(remainder.split("/", 1)[1])
