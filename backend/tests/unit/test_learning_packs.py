# ruff: noqa: E501  # Test expectations retain descriptive paths and predicates.
"""Deterministic contracts for all source-authored Visual Learning Studio packs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-learning-packs.py"
PILOT_SCRIPT = ROOT / "scripts" / "build-learning-pilot.py"
SPEC = importlib.util.spec_from_file_location("build_learning_packs", SCRIPT)
PILOT_SPEC = importlib.util.spec_from_file_location(
    "build_learning_pilot_for_library", PILOT_SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
assert PILOT_SPEC is not None and PILOT_SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
pilot = importlib.util.module_from_spec(PILOT_SPEC)
SPEC.loader.exec_module(builder)
PILOT_SPEC.loader.exec_module(pilot)


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / "visual-learning" / f"{name}.schema.json").read_text())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_builds_all_six_catalog_packs_with_complete_structured_artifacts(tmp_path: Path) -> None:
    pilot.build(tmp_path)
    catalog_path = builder.build(tmp_path)
    catalog = json.loads(catalog_path.read_text())
    Draft202012Validator(_schema("learning-library")).validate(catalog)
    assert {pack["id"] for pack in catalog["packs"]} == {
        "request-lifecycle",
        "system-overview",
        "memory-rag-evaluation",
        "reliability-operations",
        "interview-demo",
        "hybrid-agent-orchestration",
    }

    for pack in catalog["packs"]:
        if pack["id"] == "request-lifecycle":
            continue
        artifacts = {item["type"]: item for item in pack["artifacts"]}
        assert set(artifacts) == {
            "deck",
            "diagram",
            "infographic",
            "mind-map",
            "flashcards",
            "quiz",
            "study-guide",
        }
        assert sum(item["type"] == "diagram" for item in pack["artifacts"]) == 2
        assert all(item["status"] == "review-ready" for item in pack["artifacts"])
        assert all(item["language"] == "en" for item in pack["artifacts"])
        for item in pack["artifacts"]:
            primary = tmp_path / item["file"]
            assert primary.is_file() and primary.stat().st_size > 0
            assert _digest(primary) == item["sha256"]
            if "content_file" in item:
                content = tmp_path / item["content_file"]
                assert _digest(content) == item["content_sha256"]

        deck_item = next(item for item in pack["artifacts"] if item["type"] == "deck")
        deck = json.loads((tmp_path / deck_item["content_file"]).read_text())
        Draft202012Validator(_schema("deck")).validate(deck)
        assert len(deck["slides"]) == 10
        assert all(len(slide["presenter_script"].split()) >= 75 for slide in deck["slides"])
        html = (tmp_path / deck_item["file"]).read_text().lower()
        assert "github.com/levalencia/cogentrex/blob/" in html
        assert all(phrase not in html for phrase in builder.FORBIDDEN_PHRASES)

        diagram_items = [
            item for item in pack["artifacts"] if item["type"] in {"diagram", "infographic"}
        ]
        for item in diagram_items:
            diagram = json.loads((tmp_path / item["content_file"]).read_text())
            Draft202012Validator(_schema("diagram")).validate(diagram)
            assert all(len(node["details"].split()) >= 60 for node in diagram["nodes"])
            assert all(len(edge["explanation"].split()) >= 45 for edge in diagram["edges"])
            assert all(node["sources"] for node in diagram["nodes"])
            assert all(edge["sources"] for edge in diagram["edges"])
            root = ElementTree.parse(tmp_path / item["file"]).getroot()
            ns = {"svg": "http://www.w3.org/2000/svg"}
            assert root.attrib["role"] == "img"
            assert root.find("svg:title", ns) is not None
            assert root.find("svg:desc", ns) is not None

        infographic_item = next(item for item in pack["artifacts"] if item["type"] == "infographic")
        infographic = json.loads((tmp_path / infographic_item["content_file"]).read_text())
        assert len(infographic["modules"]) == 10
        assert all(
            "What this does not prove" in module["details"] for module in infographic["modules"]
        )

        cards_item = next(item for item in pack["artifacts"] if item["type"] == "flashcards")
        cards = json.loads((tmp_path / cards_item["file"]).read_text())
        Draft202012Validator(_schema("flashcards")).validate(cards)
        assert len(cards["cards"]) == 20
        assert len({card["question"] for card in cards["cards"]}) == 20
        assert all(len(card["explanation"].split()) >= 8 for card in cards["cards"])

        quiz_item = next(item for item in pack["artifacts"] if item["type"] == "quiz")
        quiz = json.loads((tmp_path / quiz_item["file"]).read_text())
        Draft202012Validator(_schema("quiz")).validate(quiz)
        assert len(quiz["questions"]) == 10
        assert all(len(question["options"]) >= 4 for question in quiz["questions"])
        assert all(
            len(set(question["options"])) == len(question["options"])
            for question in quiz["questions"]
        )

        guide_item = next(item for item in pack["artifacts"] if item["type"] == "study-guide")
        guide = json.loads((tmp_path / guide_item["file"]).read_text())
        Draft202012Validator(_schema("study-guide")).validate(guide)
        assert len(guide["sections"]) == 12
        assert guide["sections"][-1]["heading"] == "What this does not prove"

        audio_script = (
            tmp_path / "published" / pack["id"] / f"{pack['id']}-audio" / "audio-script.json"
        )
        storyboard = tmp_path / "published" / pack["id"] / f"{pack['id']}-video" / "storyboard.json"
        Draft202012Validator(_schema("audio-script")).validate(json.loads(audio_script.read_text()))
        Draft202012Validator(_schema("video-storyboard")).validate(
            json.loads(storyboard.read_text())
        )


def test_pack_specs_use_only_declared_existing_sources() -> None:
    config = builder.yaml.safe_load(builder.MANIFEST.read_text())
    declarations = {item["id"]: item for item in config["packs"]}
    for pack_id in builder.PACK_IDS:
        spec = json.loads((builder.PACK_DIR / f"{pack_id}.json").read_text())
        allowed = set(config["source_priority"]) | set(declarations[pack_id]["sources"])
        builder._validate_spec(spec, allowed)
        for concept in spec["concepts"]:
            assert all((ROOT / source).is_file() for source in concept["sources"])


def test_builder_refuses_nonempty_unowned_output(tmp_path: Path) -> None:
    (tmp_path / "unrelated.txt").write_text("keep")
    try:
        builder.build(tmp_path)
    except ValueError as error:
        assert "unowned" in str(error)
    else:
        raise AssertionError("builder accepted an unowned output directory")


def test_library_schema_requires_content_checksum_pair() -> None:
    payload = {
        "schema": "cogentrex.learning-library",
        "version": 1,
        "generated_at": "2026-09-04T00:00:00Z",
        "source_commit": "a" * 40,
        "packs": [
            {
                "id": "test-pack",
                "title": "Test pack",
                "purpose": "Exercise the schema.",
                "artifacts": [
                    {
                        "id": "test-deck",
                        "type": "deck",
                        "title": "Test deck",
                        "status": "review-ready",
                        "language": "en",
                        "file": "published/test/deck.html",
                        "media_type": "text/html",
                        "sha256": "b" * 64,
                        "source_commit": "a" * 40,
                        "limitations": ["Derived material."],
                        "content_file": "published/test/deck.json",
                    }
                ],
            }
        ],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(_schema("learning-library")).validate(payload)
