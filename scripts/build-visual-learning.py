#!/usr/bin/env python3
"""Build the deterministic data graph used by Archon's visual learning map."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/course/concept-catalog.yaml"
CURATION = ROOT / "docs/visual-learning/map-curation.yaml"
DEFAULT_OUTPUT = ROOT / "frontend/static/learning/archon-graph.json"
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
    title_line = next(
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
        "title": title_line,
        "summary": _plain_text(beginner or outcomes or mental_model),
        "mental_model": _plain_text(mental_model),
        "href": GITHUB_BASE + module_path.relative_to(ROOT).as_posix(),
    }


def _concept_metadata(concept_id: str) -> dict[str, str]:
    page_slug = CONCEPT_PAGE_ALIASES.get(concept_id, concept_id)
    path = ROOT / "docs" / "course" / "concepts" / f"{page_slug}.md"
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
    return {
        "path": path,
        "label": Path(path).name,
        "href": GITHUB_BASE + path,
    }


def _validated_path(path: str, concept_id: str) -> None:
    candidate = ROOT / path
    if not candidate.is_file():
        raise ValueError(f"{concept_id}: missing referenced file: {path}")


def build_graph() -> dict[str, Any]:
    concepts = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    curation = yaml.safe_load(CURATION.read_text(encoding="utf-8"))
    if not isinstance(concepts, list) or len(concepts) != 66:
        raise ValueError(
            f"expected 66 concepts, got {len(concepts) if isinstance(concepts, list) else 'invalid'}"
        )

    ids = [item["id"] for item in concepts]
    if len(ids) != len(set(ids)):
        raise ValueError("concept IDs must be unique")
    known = set(ids)

    module_cache: dict[str, dict[str, str]] = {}
    module_members: dict[str, list[str]] = defaultdict(list)
    nodes: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {status: 0 for status in sorted(ALLOWED_STATUSES)}

    for item in concepts:
        concept_id = item["id"]
        status = item["status"]
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"{concept_id}: unsupported status {status}")
        for group in ("sources", "tests", "evidence"):
            for path in item.get(group, []):
                _validated_path(path, concept_id)
        _validated_path(item["module"], concept_id)

        module_path = Path(item["module"])
        module_id = module_path.parent.name
        if module_id not in module_cache:
            module_cache[module_id] = _module_metadata(ROOT / module_path)
        module_members[module_id].append(concept_id)
        status_counts[status] += 1
        metadata = module_cache[module_id]
        concept_metadata = _concept_metadata(concept_id)
        summary = concept_metadata["summary"] or metadata["summary"]
        if not summary:
            raise ValueError(f"{concept_id}: no beginner explanation found")
        nodes.append(
            {
                "id": concept_id,
                "title": item["title"],
                "status": status,
                "module_id": module_id,
                "module_title": metadata["title"],
                "module_href": metadata["href"],
                "detail_href": concept_metadata["href"] or metadata["href"],
                "content_source": "concept" if concept_metadata["href"] else "module",
                "summary": summary,
                "mental_model": concept_metadata["mental_model"]
                or metadata["mental_model"],
                "limitations": item["limitations"],
                "sources": [_link(path) for path in item.get("sources", [])],
                "tests": [_link(path) for path in item.get("tests", [])],
                "evidence": [_link(path) for path in item.get("evidence", [])],
            }
        )

    edge_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
    edge_labels: dict[tuple[str, str], set[str]] = defaultdict(set)

    def add_edge(source: str, target: str, kind: str, label: str = "") -> None:
        if source not in known or target not in known:
            raise ValueError(f"unknown edge endpoint: {source} -> {target}")
        key = tuple(sorted((source, target)))
        edge_kinds[key].add(kind)
        if label:
            edge_labels[key].add(label)

    for module_id, members in module_members.items():
        for source, target in pairwise(members):
            add_edge(source, target, "module-sequence", module_id)

    tours: list[dict[str, Any]] = []
    for tour in curation.get("tours", []):
        concept_ids = tour["concept_ids"]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError(f"tour {tour['id']} repeats a concept")
        for concept_id in concept_ids:
            if concept_id not in known:
                raise ValueError(
                    f"tour {tour['id']} references unknown concept {concept_id}"
                )
        for source, target in pairwise(concept_ids):
            add_edge(source, target, f"tour:{tour['id']}", tour["title"])
        tours.append(
            {
                "id": tour["id"],
                "title": tour["title"],
                "description": tour["description"],
                "concept_ids": concept_ids,
            }
        )

    for relation in curation.get("connections", []):
        add_edge(relation["source"], relation["target"], "curated", relation["label"])

    edges = [
        {
            "source": source,
            "target": target,
            "kinds": sorted(edge_kinds[(source, target)]),
            "labels": sorted(edge_labels[(source, target)]),
        }
        for source, target in sorted(edge_kinds)
    ]

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    visited: set[str] = set()
    queue: deque[str] = deque([ids[0]])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency[current] - visited)
    if visited != known:
        missing = sorted(known - visited)
        raise ValueError(f"visual graph is disconnected: {', '.join(missing)}")

    modules = [
        {
            "id": module_id,
            "title": module_cache[module_id]["title"],
            "summary": module_cache[module_id]["summary"],
            "mental_model": module_cache[module_id]["mental_model"],
            "href": module_cache[module_id]["href"],
            "concept_count": len(module_members[module_id]),
        }
        for module_id in sorted(module_members)
    ]

    return {
        "schema": "archon.visual-learning-graph",
        "version": 1,
        "generated_from": [
            "docs/course/concept-catalog.yaml",
            "docs/visual-learning/map-curation.yaml",
            "docs/course/concepts/*.md",
            "docs/course/modules/*/README.md",
        ],
        "stats": {
            "concepts": len(nodes),
            "modules": len(modules),
            "edges": len(edges),
            "tours": len(tours),
            "statuses": status_counts,
        },
        "modules": modules,
        "nodes": nodes,
        "edges": edges,
        "tours": tours,
    }


def render(graph: dict[str, Any]) -> str:
    return json.dumps(graph, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = render(build_graph())
    if args.check:
        if (
            not args.output.is_file()
            or args.output.read_text(encoding="utf-8") != payload
        ):
            raise SystemExit(
                f"visual learning graph is stale: run {Path(__file__).name}"
            )
        print("Visual learning graph is current: 66 concepts")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    print(f"Wrote {args.output.relative_to(ROOT)} with 66 concepts")


if __name__ == "__main__":
    main()
