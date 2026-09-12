"""Collect allowlisted repository and video content into typed learning sources."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.learning_media.catalog import LearningMediaCatalog

_REVISION = re.compile(r"^(?:[0-9a-f]{40}|working-tree:[0-9a-f]{16,64})$")


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or "\0" in value or ".." in path.parts:
        raise ValueError("Invalid relative path")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class LearningSourceInput:
    kind: str
    key: str
    title: str
    text: str
    revision: str
    locator: dict[str, Any]
    context_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"documentation", "code", "test", "video", "visual"}:
            raise ValueError("Unsupported learning source kind")
        if not self.key or not self.title or not self.text.strip():
            raise ValueError("Learning source fields must not be empty")
        if not _REVISION.fullmatch(self.revision):
            raise ValueError("Learning source revision is invalid")
        if "path" in self.locator:
            _safe_relative_path(str(self.locator["path"]))

    @property
    def id(self) -> str:
        return hashlib.sha256(f"{self.kind}:{self.key}".encode()).hexdigest()[:32]

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "title": self.title,
                "text": self.text,
                "locator": self.locator,
                "context_keys": self.context_keys,
            },
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def collect_markdown(
    path: str | Path, *, relative_path: str, revision: str
) -> list[LearningSourceInput]:
    """Split Markdown by h1/h2/h3 headings while retaining exact source lines."""
    relative_path = _safe_relative_path(relative_path)
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8").splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines, 1):
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    if not headings:
        text = "\n".join(lines).strip()
        return (
            [
                LearningSourceInput(
                    kind="documentation",
                    key=relative_path,
                    title=source_path.stem,
                    text=text,
                    revision=revision,
                    locator={"path": relative_path, "line_start": 1, "line_end": len(lines)},
                )
            ]
            if text
            else []
        )
    root_title = headings[0][2]
    result: list[LearningSourceInput] = []
    for offset, (start, level, heading) in enumerate(headings):
        end = headings[offset + 1][0] - 1 if offset + 1 < len(headings) else len(lines)
        text = "\n".join(lines[start - 1 : end]).strip()
        if not text:
            continue
        title = root_title if level == 1 else f"{root_title} — {heading}"
        anchor = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        result.append(
            LearningSourceInput(
                kind="documentation",
                key=f"{relative_path}#{anchor}",
                title=title,
                text=text,
                revision=revision,
                locator={"path": relative_path, "line_start": start, "line_end": end},
            )
        )
    return result


def collect_python(
    path: str | Path,
    *,
    relative_path: str,
    revision: str,
    kind: str = "code",
) -> list[LearningSourceInput]:
    """Collect Python module preamble and top-level class/function symbols."""
    relative_path = _safe_relative_path(relative_path)
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text, filename=relative_path)
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    result: list[LearningSourceInput] = []
    first_symbol = min((node.lineno for node in nodes), default=len(lines) + 1)
    preamble = "\n".join(lines[: first_symbol - 1]).strip()
    if preamble:
        result.append(
            LearningSourceInput(
                kind=kind,
                key=f"{relative_path}#module",
                title=f"{source_path.name} — module",
                text=preamble,
                revision=revision,
                locator={"path": relative_path, "line_start": 1, "line_end": first_symbol - 1},
            )
        )
    for node in nodes:
        end = int(node.end_lineno or node.lineno)
        symbol = node.name
        result.append(
            LearningSourceInput(
                kind=kind,
                key=f"{relative_path}#{symbol}",
                title=f"{source_path.name} — {symbol}",
                text="\n".join(lines[node.lineno - 1 : end]),
                revision=revision,
                locator={
                    "path": relative_path,
                    "symbol": symbol,
                    "line_start": node.lineno,
                    "line_end": end,
                    "language": "python",
                },
            )
        )
    return result


def collect_text_code(
    path: str | Path,
    *,
    relative_path: str,
    revision: str,
    kind: str = "code",
    lines_per_chunk: int = 80,
) -> list[LearningSourceInput]:
    """Collect non-Python source in deterministic line windows."""
    relative_path = _safe_relative_path(relative_path)
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    result: list[LearningSourceInput] = []
    for start in range(1, len(lines) + 1, lines_per_chunk):
        end = min(start + lines_per_chunk - 1, len(lines))
        text = "\n".join(lines[start - 1 : end]).strip()
        if text:
            result.append(
                LearningSourceInput(
                    kind=kind,
                    key=f"{relative_path}#L{start}-L{end}",
                    title=f"{Path(relative_path).name} — lines {start}-{end}",
                    text=text,
                    revision=revision,
                    locator={
                        "path": relative_path,
                        "line_start": start,
                        "line_end": end,
                        "language": Path(relative_path).suffix.lstrip("."),
                    },
                )
            )
    return result


def collect_video_transcripts(
    catalog: LearningMediaCatalog,
    *,
    artifact_ids: set[str] | None = None,
    include_review_ready: bool = False,
) -> list[LearningSourceInput]:
    """Collect validated JSON transcript segments with exact seek metadata."""
    result: list[LearningSourceInput] = []
    for pack in catalog.public_catalog().get("packs", []):
        for summary in pack.get("artifacts", []):
            artifact_id = str(summary.get("id") or "")
            if summary.get("type") != "video" or (
                artifact_ids is not None and artifact_id not in artifact_ids
            ):
                continue
            if summary.get("status") != "published" and not (
                include_review_ready and summary.get("status") == "review-ready"
            ):
                continue
            artifact = catalog.artifact(artifact_id)
            if artifact.content_path is None or artifact.content_path.suffix.lower() != ".json":
                continue
            payload = json.loads(artifact.content_path.read_text(encoding="utf-8"))
            if payload.get("schema") != "cogentrex.video-transcript":
                raise ValueError(f"Artifact {artifact_id} has an invalid transcript schema")
            for index, segment in enumerate(payload.get("segments", [])):
                if not isinstance(segment, dict):
                    continue
                text = str(segment.get("text") or "").strip()
                start = segment.get("start_seconds")
                end = segment.get("end_seconds")
                if (
                    not text
                    or not isinstance(start, (int, float))
                    or not isinstance(end, (int, float))
                    or float(end) <= float(start)
                ):
                    raise ValueError(f"Artifact {artifact_id} has an invalid timed segment")
                result.append(
                    LearningSourceInput(
                        kind="video",
                        key=f"video:{artifact_id}:{index}",
                        title=(
                            f"{summary['title']} — "
                            f"{segment.get('chapter') or f'Segment {index + 1}'}"
                        ),
                        text=text,
                        revision=str(summary["source_commit"]),
                        locator={
                            "artifact_id": artifact_id,
                            "pack_id": str(pack["id"]),
                            "chapter": str(segment.get("chapter") or "Transcript"),
                            "start_seconds": float(start),
                            "end_seconds": float(end),
                            "sources": list(segment.get("sources", [])),
                        },
                        context_keys=(f"artifact:{artifact_id}",),
                    )
                )
    return result
