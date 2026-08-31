"""Contracts for the generated Visual Learning Studio manifest."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-visual-learning.py"
OUTPUT = ROOT / "frontend/static/learning/archon-studio.json"
SPEC = importlib.util.spec_from_file_location("build_visual_learning", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_studio_preserves_catalog_and_view_counts() -> None:
    studio = builder.build_studio()

    assert studio["schema"] == "archon.visual-learning-studio"
    assert studio["version"] == 2
    assert studio["stats"] == {
        "concepts": 66,
        "modules": 16,
        "stories": 5,
        "architecture_layers": 5,
        "notebooks": 5,
        "statuses": {"deferred": 6, "implemented": 46, "partial": 14},
    }


def test_every_concept_has_truthful_learning_and_proof_metadata() -> None:
    studio = builder.build_studio()

    for concept in studio["concepts"]:
        assert concept["title"]
        assert concept["summary"]
        assert concept["limitations"]
        assert concept["detail_href"].startswith("https://github.com/levalencia/archon/blob/main/")
        assert concept["content_source"] in {"concept", "module"}
        assert concept["proof"] == {
            "code": bool(concept["sources"]),
            "tests": bool(concept["tests"]),
            "evidence": bool(concept["evidence"]),
        }
        if concept["status"] != "deferred":
            assert concept["sources"]
            assert concept["tests"]
        for group in ("sources", "tests", "evidence"):
            for link in concept[group]:
                assert (ROOT / link["path"]).is_file()


def test_aliases_fallbacks_and_roadmap_are_explicit() -> None:
    studio = builder.build_studio()
    by_id = {concept["id"]: concept for concept in studio["concepts"]}

    assert sum(item["content_source"] == "concept" for item in studio["concepts"]) == 64
    assert {item["id"] for item in studio["concepts"] if item["content_source"] == "module"} == {
        "public-anonymous-sharing",
        "autonomous-unapproved-production-optimization",
    }
    assert by_id["python-protocols-di"]["detail_href"].endswith(
        "docs/course/concepts/oop-protocols-dependency-injection.md"
    )
    assert by_id["runtime-state-machine"]["detail_href"].endswith(
        "docs/course/concepts/state-machines.md"
    )
    roadmap_modules = [
        module_id for phase in studio["roadmap"] for module_id in phase["module_ids"]
    ]
    assert len(roadmap_modules) == len(set(roadmap_modules)) == 16
    assert set(roadmap_modules) == {module["id"] for module in studio["modules"]}


def test_stories_use_small_directional_scenes() -> None:
    studio = builder.build_studio()
    known = {concept["id"] for concept in studio["concepts"]}

    assert {story["id"] for story in studio["stories"]} == {
        "request-lifecycle",
        "governed-tool",
        "memory-rag",
        "observability",
        "local-startup",
    }
    for story in studio["stories"]:
        assert 4 <= len(story["steps"]) <= 8
        assert [step["number"] for step in story["steps"]] == list(
            range(1, len(story["steps"]) + 1)
        )
        for step in story["steps"]:
            assert step["from"] != step["to"]
            assert step["relationship"].strip()
            assert "+" not in step["relationship"]
            assert set(step["concept_ids"]) <= known


def test_architecture_relations_are_typed_and_not_implicit() -> None:
    architecture = builder.build_studio()["architecture"]
    components = {
        component["id"] for layer in architecture["layers"] for component in layer["components"]
    }

    assert len(architecture["layers"]) == 5
    assert len(components) == 17
    assert len(architecture["relations"]) == 14
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
    assert {relation["type"] for relation in architecture["relations"]} <= allowed_types
    for relation in architecture["relations"]:
        assert relation["source"] in components
        assert relation["target"] in components
        assert relation["source"] != relation["target"]
        assert relation["type"]
        assert relation["label"]


def test_force_map_is_retired_and_legacy_route_redirects() -> None:
    package = json.loads((ROOT / "frontend/package.json").read_text())
    dependencies = package.get("dependencies", {}) | package.get("devDependencies", {})

    assert "d3" not in dependencies
    assert "@types/d3" not in dependencies
    assert not (ROOT / "frontend/src/lib/components/VisualLearningMap.svelte").exists()
    assert not (ROOT / "frontend/static/learning/archon-graph.json").exists()
    redirect = (ROOT / "frontend/src/routes/learn/map/+page.ts").read_text()
    assert "redirect(307, '/learn?view=stories')" in redirect


def test_notebooklm_recipes_and_committed_manifest_are_current() -> None:
    studio = builder.build_studio()

    assert {notebook["id"] for notebook in studio["notebooklm"]["notebooks"]} == {
        "system-overview",
        "request-lifecycle",
        "memory-rag-evaluation",
        "reliability-operations",
        "interview-demo",
    }
    for notebook in studio["notebooklm"]["notebooks"]:
        assert notebook["source_count"] == len(notebook["sources"])
        assert notebook["artifacts"]
    assert OUTPUT.is_file()
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == studio
