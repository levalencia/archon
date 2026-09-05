"""Deterministic contracts for the Hermes-authored request-lifecycle pilot."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-learning-pilot.py"
SPEC = importlib.util.spec_from_file_location("build_learning_pilot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _schema(name: str) -> dict:
    return json.loads(
        (ROOT / "schemas" / "visual-learning" / f"{name}.schema.json").read_text(encoding="utf-8")
    )


def test_pilot_builds_valid_english_visual_and_study_artifacts(tmp_path: Path) -> None:
    catalog_path = builder.build(tmp_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    Draft202012Validator(_schema("learning-library")).validate(catalog)

    artifacts = {item["id"]: item for pack in catalog["packs"] for item in pack["artifacts"]}
    assert set(artifacts) == {
        "request-deck",
        "request-diagram-1",
        "request-diagram-2",
        "request-diagram-3",
        "request-mind-map",
        "request-flashcards",
        "request-quiz",
        "request-study-guide",
    }
    assert all(item["language"] == "en" for item in artifacts.values())

    deck = json.loads((tmp_path / artifacts["request-deck"]["content_file"]).read_text())
    Draft202012Validator(_schema("deck")).validate(deck)
    assert 12 <= len(deck["slides"]) <= 15
    assert all(len(slide["presenter_script"].split()) >= 90 for slide in deck["slides"])
    assert all(slide["key_terms"] for slide in deck["slides"])
    assert all(slide["common_misconception"] for slide in deck["slides"])
    assert all(slide["transition"] for slide in deck["slides"])
    assert "<script" not in (tmp_path / artifacts["request-deck"]["file"]).read_text().lower()
    assert "Teach this slide" in (tmp_path / artifacts["request-deck"]["file"]).read_text()
    deck_html = (tmp_path / artifacts["request-deck"]["file"]).read_text()
    assert "github.com/levalencia/archon/blob/" in deck_html
    assert "What this does not prove" in deck_html
    spec = json.loads(builder.SPEC.read_text())
    assert all(limitation in deck_html for limitation in spec["limitations"])

    for artifact_id in ("request-diagram-1", "request-diagram-2", "request-diagram-3"):
        diagram = json.loads((tmp_path / artifacts[artifact_id]["content_file"]).read_text())
        Draft202012Validator(_schema("diagram")).validate(diagram)
        assert len(diagram["source_commit"]) == 40
        assert set(diagram["source_commit"]) <= set("0123456789abcdef")
        node_ids = {node["id"] for node in diagram["nodes"]}
        assert all(
            edge["source"] in node_ids and edge["target"] in node_ids for edge in diagram["edges"]
        )
        assert all(
            edge["label"] and edge["explanation"] and edge["sources"] for edge in diagram["edges"]
        )
        assert all(node["details"] and node["sources"] for node in diagram["nodes"])
        assert all(
            set(node["teaching"])
            == {
                "definition",
                "receives",
                "responsibility",
                "produces",
                "controls",
                "failure_behavior",
                "why_it_matters",
            }
            for node in diagram["nodes"]
        )
        assert all(
            set(edge["teaching"])
            == {
                "payload",
                "transformation",
                "trust_boundary",
                "precondition",
                "failure_behavior",
                "why_it_matters",
            }
            for edge in diagram["edges"]
        )
        assert "owns one explicit responsibility" not in json.dumps(diagram)
        assert "identifies which component initiates" not in json.dumps(diagram)
        svg_root = ElementTree.parse(tmp_path / artifacts[artifact_id]["file"]).getroot()
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        assert svg_root.find("svg:title", namespace) is not None
        assert svg_root.find("svg:desc", namespace) is not None
        assert diagram["nodes"][0]["label"] in "".join(svg_root.itertext())

    governed = json.loads((tmp_path / artifacts["request-diagram-1"]["content_file"]).read_text())
    governed_nodes = {node["id"]: node for node in governed["nodes"]}
    governed_edges = {edge["label"]: edge for edge in governed["edges"]}
    assert {"ALLOW", "ASK", "DENY"}.issubset(set(governed_nodes["policy"]["teaching"]["controls"]))
    assert "cannot authorize itself" in governed_nodes["policy"]["teaching"]["why_it_matters"]
    assert "not model memory" in governed_nodes["run-ledger"]["teaching"]["definition"]
    assert (
        "not automatically a successful result"
        in governed_edges["result event"]["teaching"]["payload"]
    )
    assert (
        "does not automatically prove"
        in governed_edges["run evidence"]["teaching"]["why_it_matters"]
    )

    infographic = json.loads(
        (tmp_path / artifacts["request-diagram-3"]["content_file"]).read_text()
    )
    assert len(infographic["modules"]) >= 10
    assert all(module["details"] and module["sources"] for module in infographic["modules"])

    mind_map = json.loads((tmp_path / artifacts["request-mind-map"]["file"]).read_text())
    Draft202012Validator(_schema("mind-map")).validate(mind_map)
    assert len(mind_map["root"]["children"]) <= 6
    assert all(branch["children"] for branch in mind_map["root"]["children"])

    flashcards = json.loads((tmp_path / artifacts["request-flashcards"]["file"]).read_text())
    Draft202012Validator(_schema("flashcards")).validate(flashcards)
    assert len(flashcards["cards"]) == 20

    quiz = json.loads((tmp_path / artifacts["request-quiz"]["file"]).read_text())
    Draft202012Validator(_schema("quiz")).validate(quiz)
    assert len(quiz["questions"]) == 10

    guide = json.loads((tmp_path / artifacts["request-study-guide"]["file"]).read_text())
    Draft202012Validator(_schema("study-guide")).validate(guide)
    assert any(section["heading"] == "What this does not prove" for section in guide["sections"])


def test_pilot_refuses_nonempty_unowned_output(tmp_path: Path) -> None:
    (tmp_path / "unrelated.txt").write_text("keep me", encoding="utf-8")
    try:
        builder.build(tmp_path)
    except ValueError as error:
        assert "unowned" in str(error)
    else:
        raise AssertionError("builder accepted an unowned output directory")
