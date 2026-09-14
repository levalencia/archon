"""Contracts for the canonical Visual Learning vocabulary system."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-learning-vocabulary.py"
SOURCE = ROOT / "docs" / "course" / "reference" / "vocabulary.yaml"
GLOSSARY = ROOT / "docs" / "course" / "reference" / "glossary.md"
AUDIT = ROOT / "docs" / "course" / "reference" / "vocabulary-audit.json"
CATALOG = ROOT / "docs" / "course" / "concept-catalog.yaml"
EVALS = ROOT / "backend" / "evals" / "learning_tutor" / "concepts-v1.json"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_learning_vocabulary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vocabulary_is_extensive_unique_and_beginner_grounded() -> None:
    builder = _load_builder()
    vocabulary = builder.load_vocabulary(SOURCE)
    entries = vocabulary["entries"]

    assert len(entries) >= 200
    ids = [entry["id"] for entry in entries]
    normalized_terms = [builder.normalize_term(entry["term"]) for entry in entries]
    assert len(ids) == len(set(ids))
    assert len(normalized_terms) == len(set(normalized_terms))

    known_ids = set(ids)
    for entry in entries:
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry["id"])
        assert entry["category"] in builder.ALLOWED_CATEGORIES
        assert entry["level"] in {"beginner", "intermediate", "advanced"}
        assert len(entry["definition"]) >= 40
        assert len(entry["cogentrex"]) >= 40
        assert len(entry["learn_more"]) >= 1
        assert all((ROOT / path).is_file() for path in entry["learn_more"])
        assert set(entry.get("related_ids", [])) <= known_ids


def test_vocabulary_covers_catalog_eval_and_published_video_terms() -> None:
    builder = _load_builder()
    vocabulary = builder.load_vocabulary(SOURCE)
    covered_catalog_concepts = {
        concept_id for entry in vocabulary["entries"] for concept_id in entry["concept_ids"]
    }
    catalog_ids = {item["id"] for item in yaml.safe_load(CATALOG.read_text())}
    assert catalog_ids <= covered_catalog_concepts

    dataset = json.loads(EVALS.read_text())
    eval_ids = {
        concept_id
        for case in dataset["cases"]
        for concept_id in case.get("expected_concepts", [])
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", concept_id)
    }
    covered_eval_concepts = {
        concept_id
        for entry in vocabulary["entries"]
        for concept_id in (*entry["concept_ids"], *entry.get("eval_concept_ids", []))
    }
    assert eval_ids <= covered_eval_concepts

    normalized = {
        builder.normalize_term(value)
        for entry in vocabulary["entries"]
        for value in (entry["term"], *entry.get("aliases", []))
    }
    required_video_terms = {
        "preflight",
        "construct",
        "yield",
        "serve",
        "teardown",
        "runcontext",
        "event sink",
        "effect ledger",
        "budget provider",
        "tool authorizer",
        "runtime budget",
        "port",
        "adapter",
        "composition root",
        "structural subtyping",
    }
    assert required_video_terms <= normalized


def test_generated_glossary_and_coverage_audit_are_current() -> None:
    builder = _load_builder()
    vocabulary = builder.load_vocabulary(SOURCE)

    assert GLOSSARY.read_text() == builder.render_glossary(vocabulary)
    assert json.loads(AUDIT.read_text()) == builder.build_coverage_audit(vocabulary)


def test_module_and_concept_vocabulary_sections_are_fully_mapped() -> None:
    builder = _load_builder()
    vocabulary = builder.load_vocabulary(SOURCE)
    mapped = {
        builder.normalize_term(value)
        for entry in vocabulary["entries"]
        for value in (entry["term"], *entry.get("aliases", []))
    }
    declared: set[str] = set()
    for path in (ROOT / "docs" / "course").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for heading in ("Prerequisites and vocabulary", "Precision vocabulary"):
            match = re.search(
                rf"^## {re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)",
                text,
                re.MULTILINE | re.DOTALL,
            )
            if match:
                declared.update(
                    builder.normalize_term(term.rstrip("*"))
                    for term in re.findall(
                        r"^\s*-\s+\*\*(.+?)(?::|\*\*)", match.group(1), re.MULTILINE
                    )
                )

    assert declared <= mapped
