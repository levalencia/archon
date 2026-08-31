"""Contracts for the generated visual-learning graph."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-visual-learning.py"
OUTPUT = ROOT / "frontend" / "static" / "learning" / "archon-graph.json"
SPEC = importlib.util.spec_from_file_location("build_visual_learning", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_graph_preserves_catalog_status_and_module_counts() -> None:
    graph = builder.build_graph()

    assert graph["schema"] == "archon.visual-learning-graph"
    assert graph["stats"] == {
        "concepts": 66,
        "modules": 15,
        "edges": graph["stats"]["edges"],
        "tours": 4,
        "statuses": {"deferred": 6, "implemented": 46, "partial": 14},
    }
    assert graph["stats"]["edges"] >= 65


def test_every_node_has_learning_copy_and_valid_evidence_links() -> None:
    graph = builder.build_graph()

    for node in graph["nodes"]:
        assert node["title"]
        assert node["summary"]
        assert node["limitations"]
        assert node["detail_href"].startswith("https://github.com/levalencia/archon/blob/main/")
        assert node["content_source"] in {"concept", "module"}
        assert node["module_href"].startswith("https://github.com/levalencia/archon/blob/main/")
        assert any(node[group] for group in ("sources", "tests", "evidence"))
        if node["status"] != "deferred":
            assert node["sources"]
            assert node["tests"]
        for group in ("sources", "tests", "evidence"):
            for link in node[group]:
                assert (ROOT / link["path"]).is_file()
                assert link["href"].endswith(link["path"])


def test_concept_page_aliases_and_module_fallbacks_are_explicit() -> None:
    graph = builder.build_graph()
    by_id = {node["id"]: node for node in graph["nodes"]}

    assert sum(node["content_source"] == "concept" for node in graph["nodes"]) == 64
    assert {node["id"] for node in graph["nodes"] if node["content_source"] == "module"} == {
        "public-anonymous-sharing",
        "autonomous-unapproved-production-optimization",
    }
    assert by_id["python-protocols-di"]["detail_href"].endswith(
        "docs/course/concepts/oop-protocols-dependency-injection.md"
    )
    assert by_id["runtime-state-machine"]["detail_href"].endswith(
        "docs/course/concepts/state-machines.md"
    )
    assert by_id["react-loop"]["detail_href"].endswith("docs/course/concepts/react.md")
    assert by_id["json-schema-subset"]["detail_href"].endswith(
        "docs/course/concepts/json-schema.md"
    )


def test_tours_and_edges_reference_known_concepts_and_connect_the_graph() -> None:
    graph = builder.build_graph()
    known = {node["id"] for node in graph["nodes"]}

    assert {tour["id"] for tour in graph["tours"]} == {
        "lifecycle",
        "tool-execution",
        "memory-rag",
        "observability",
    }
    for tour in graph["tours"]:
        assert len(tour["concept_ids"]) >= 8
        assert set(tour["concept_ids"]) <= known
    for edge in graph["edges"]:
        assert edge["source"] in known
        assert edge["target"] in known
        assert edge["source"] != edge["target"]
        assert edge["kinds"]


def test_committed_graph_matches_the_generator() -> None:
    assert OUTPUT.is_file()
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == builder.build_graph()
