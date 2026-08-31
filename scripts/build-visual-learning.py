#!/usr/bin/env python3
"""Build deterministic data for Archon's multi-view Visual Learning Studio."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/course/concept-catalog.yaml"
CURATION = ROOT / "docs/visual-learning/studio-curation.yaml"
NOTEBOOKS = ROOT / "docs/visual-learning/notebooklm-sources.yaml"
PROMPTBOOK = ROOT / "docs/visual-learning/notebooklm-promptbook.md"
RUNBOOK = ROOT / "docs/visual-learning/notebooklm-runbook.md"
DEFAULT_OUTPUT = ROOT / "frontend/static/learning/archon-studio.json"
ALLOWED_STATUSES = {"implemented", "partial", "deferred"}
GITHUB_BASE = "https://github.com/levalencia/archon/blob/main/"
CONCEPT_PAGE_ALIASES = {
    "python-protocols-di": "oop-protocols-dependency-injection",
    "runtime-state-machine": "state-machines",
    "react-loop": "react",
    "json-schema-subset": "json-schema",
}


def _section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    return match.group("body").strip() if match else ""


def _plain_text(markdown: str, *, limit: int = 520) -> str:
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[`*_>#|]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _module_metadata(module_path: Path) -> dict[str, str]:
    markdown = module_path.read_text(encoding="utf-8")
    title = next(
        (
            line.removeprefix("# ").strip()
            for line in markdown.splitlines()
            if line.startswith("# ")
        ),
        module_path.parent.name,
    )
    beginner = _section(markdown, "Beginner explanation")
    outcomes = _section(markdown, "Outcomes and prerequisites")
    mental_model = _section(markdown, "Mental model") or _section(
        markdown, "Problem and mental model"
    )
    return {
        "title": title,
        "summary": _plain_text(beginner or outcomes or mental_model),
        "mental_model": _plain_text(mental_model),
        "href": GITHUB_BASE + module_path.relative_to(ROOT).as_posix(),
    }


def _concept_metadata(concept_id: str) -> dict[str, str]:
    slug = CONCEPT_PAGE_ALIASES.get(concept_id, concept_id)
    path = ROOT / "docs/course/concepts" / f"{slug}.md"
    if not path.is_file():
        return {"summary": "", "mental_model": "", "href": ""}
    markdown = path.read_text(encoding="utf-8")
    mental_model = _section(markdown, "Problem and mental model") or _section(
        markdown, "Mental model"
    )
    return {
        "summary": _plain_text(_section(markdown, "Beginner explanation")),
        "mental_model": _plain_text(mental_model),
        "href": GITHUB_BASE + path.relative_to(ROOT).as_posix(),
    }


def _link(path: str) -> dict[str, str]:
    return {"path": path, "label": Path(path).name, "href": GITHUB_BASE + path}


def _validated_file(path: str, owner: str) -> None:
    candidate = (ROOT / path).resolve()
    if ROOT not in candidate.parents or not candidate.is_file():
        raise ValueError(f"{owner}: missing or unsafe referenced file: {path}")


def _load_concepts() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, int]
]:
    raw = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != 66:
        count = len(raw) if isinstance(raw, list) else "invalid"
        raise ValueError(f"expected 66 concepts, got {count}")
    ids = [item["id"] for item in raw]
    if len(ids) != len(set(ids)):
        raise ValueError("concept IDs must be unique")

    modules: dict[str, dict[str, Any]] = {}
    members: dict[str, list[str]] = defaultdict(list)
    concepts: list[dict[str, Any]] = []
    status_counts = {status: 0 for status in sorted(ALLOWED_STATUSES)}

    for item in raw:
        concept_id = item["id"]
        status = item["status"]
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"{concept_id}: unsupported status {status}")
        for group in ("sources", "tests", "evidence"):
            for path in item.get(group, []):
                _validated_file(path, concept_id)
        _validated_file(item["module"], concept_id)

        module_path = Path(item["module"])
        module_id = module_path.parent.name
        if module_id not in modules:
            modules[module_id] = {
                "id": module_id,
                **_module_metadata(ROOT / module_path),
            }
        members[module_id].append(concept_id)
        status_counts[status] += 1
        module = modules[module_id]
        detail = _concept_metadata(concept_id)
        summary = detail["summary"] or module["summary"]
        if not summary:
            raise ValueError(f"{concept_id}: no beginner explanation found")
        concepts.append(
            {
                "id": concept_id,
                "title": item["title"],
                "status": status,
                "module_id": module_id,
                "module_title": module["title"],
                "module_href": module["href"],
                "detail_href": detail["href"] or module["href"],
                "content_source": "concept" if detail["href"] else "module",
                "summary": summary,
                "mental_model": detail["mental_model"] or module["mental_model"],
                "limitations": item["limitations"],
                "sources": [_link(path) for path in item.get("sources", [])],
                "tests": [_link(path) for path in item.get("tests", [])],
                "evidence": [_link(path) for path in item.get("evidence", [])],
                "proof": {
                    "code": bool(item.get("sources")),
                    "tests": bool(item.get("tests")),
                    "evidence": bool(item.get("evidence")),
                },
            }
        )

    for module_id, concept_ids in members.items():
        modules[module_id]["concept_ids"] = concept_ids
        modules[module_id]["concept_count"] = len(concept_ids)

    return concepts, list(modules.values()), status_counts


def _complete_modules(
    modules: list[dict[str, Any]], roadmap: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {module["id"]: module for module in modules}
    ordered_ids: list[str] = []
    for phase in roadmap:
        for module_id in phase["module_ids"]:
            if module_id not in ordered_ids:
                ordered_ids.append(module_id)
            if module_id not in by_id:
                path = ROOT / "docs/course/modules" / module_id / "README.md"
                if not path.is_file():
                    raise ValueError(f"roadmap references unknown module: {module_id}")
                by_id[module_id] = {
                    "id": module_id,
                    **_module_metadata(path),
                    "concept_ids": [],
                    "concept_count": 0,
                }
    return [by_id[module_id] for module_id in ordered_ids]


def _validate_stories(
    stories: list[dict[str, Any]], known_concepts: set[str]
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    for story in stories:
        if story["id"] in seen or not story.get("steps"):
            raise ValueError(f"invalid or repeated story: {story['id']}")
        seen.add(story["id"])
        for index, step in enumerate(story["steps"], start=1):
            unknown = set(step.get("concept_ids", [])) - known_concepts
            if unknown:
                raise ValueError(f"story {story['id']} references {sorted(unknown)}")
            for field in ("title", "from", "to", "relationship", "explanation"):
                if not step.get(field):
                    raise ValueError(f"story {story['id']} step {index} lacks {field}")
            step["number"] = index
    return stories


def _validate_architecture(
    architecture: dict[str, Any], known_concepts: set[str]
) -> dict[str, Any]:
    components: set[str] = set()
    for layer in architecture.get("layers", []):
        for component in layer.get("components", []):
            component_id = component["id"]
            if component_id in components:
                raise ValueError(f"duplicate architecture component: {component_id}")
            components.add(component_id)
            unknown = set(component.get("concept_ids", [])) - known_concepts
            if unknown:
                raise ValueError(
                    f"component {component_id} references {sorted(unknown)}"
                )
    allowed_types = {
        "CALLS",
        "ROUTES",
        "AUTHORIZES",
        "BUILDS_CONTEXT_FOR",
        "PROPOSES",
        "GATES",
        "PERSISTS_TO",
        "READS",
        "EMITS",
        "SUPPLIES_RUNS_TO",
        "CONSTRAINS",
        "PROVES_READY",
    }
    for relation in architecture.get("relations", []):
        if relation["source"] not in components or relation["target"] not in components:
            raise ValueError(f"unknown architecture relation endpoint: {relation}")
        if relation["type"] not in allowed_types or not relation.get("label"):
            raise ValueError(f"invalid architecture relation: {relation}")
    return architecture


def _load_notebooks() -> dict[str, Any]:
    config = yaml.safe_load(NOTEBOOKS.read_text(encoding="utf-8"))
    ids: set[str] = set()
    priority = config.get("source_priority", [])
    for notebook in config.get("notebooks", []):
        if notebook["id"] in ids:
            raise ValueError(f"duplicate NotebookLM notebook: {notebook['id']}")
        ids.add(notebook["id"])
        notebook["sources"] = list(
            dict.fromkeys(priority + notebook.get("sources", []))
        )
        for path in notebook["sources"]:
            _validated_file(path, notebook["id"])
        notebook["source_count"] = len(notebook["sources"])
    for path in config.get("source_priority", []):
        _validated_file(path, "source_priority")
    _validated_file(str(PROMPTBOOK.relative_to(ROOT)), "NotebookLM promptbook")
    _validated_file(str(RUNBOOK.relative_to(ROOT)), "NotebookLM runbook")
    config["promptbook_href"] = GITHUB_BASE + PROMPTBOOK.relative_to(ROOT).as_posix()
    config["runbook_href"] = GITHUB_BASE + RUNBOOK.relative_to(ROOT).as_posix()
    return config


def build_studio() -> dict[str, Any]:
    concepts, partial_modules, status_counts = _load_concepts()
    curation = yaml.safe_load(CURATION.read_text(encoding="utf-8"))
    if curation.get("version") != 2:
        raise ValueError("studio curation version must be 2")
    known_concepts = {concept["id"] for concept in concepts}
    roadmap = curation.get("roadmap", [])
    modules = _complete_modules(partial_modules, roadmap)
    module_ids = {module["id"] for module in modules}
    for phase in roadmap:
        unknown = set(phase["module_ids"]) - module_ids
        if unknown:
            raise ValueError(
                f"roadmap phase {phase['id']} references {sorted(unknown)}"
            )
    stories = _validate_stories(curation.get("stories", []), known_concepts)
    architecture = _validate_architecture(
        curation.get("architecture", {}), known_concepts
    )
    notebooks = _load_notebooks()

    return {
        "schema": "archon.visual-learning-studio",
        "version": 2,
        "generated_from": [
            "docs/course/concept-catalog.yaml",
            "docs/course/concepts/*.md",
            "docs/course/modules/*/README.md",
            "docs/visual-learning/studio-curation.yaml",
            "docs/visual-learning/notebooklm-sources.yaml",
            "docs/visual-learning/notebooklm-promptbook.md",
            "docs/visual-learning/notebooklm-runbook.md",
        ],
        "stats": {
            "concepts": len(concepts),
            "modules": len(modules),
            "stories": len(stories),
            "architecture_layers": len(architecture.get("layers", [])),
            "notebooks": len(notebooks.get("notebooks", [])),
            "statuses": status_counts,
        },
        "roadmap": roadmap,
        "modules": modules,
        "concepts": concepts,
        "stories": stories,
        "architecture": architecture,
        "notebooklm": notebooks,
    }


def render(studio: dict[str, Any]) -> str:
    return json.dumps(studio, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = render(build_studio())
    if args.check:
        if (
            not args.output.is_file()
            or args.output.read_text(encoding="utf-8") != payload
        ):
            raise SystemExit(
                f"visual learning studio is stale: run {Path(__file__).name}"
            )
        print("Visual learning studio is current: 66 concepts, 16 modules")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(f"Wrote {args.output.relative_to(ROOT)} with 66 concepts and 16 modules")


if __name__ == "__main__":
    main()
