"""Contracts for generated HyperFrames learning-video projects."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / "scripts" / "build-learning-video-projects.py"
SPEC = importlib.util.spec_from_file_location("build_learning_video_projects", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_generated_video_avoids_duplicate_intro_cards_and_black_scene_boundaries() -> None:
    concepts = [
        {
            "label": "Policy",
            "summary": "Policy summary that belongs in narration.",
            "teaching": {"controls": ["ALLOW, ASK, or DENY", "Exact approval binding"]},
        },
        {
            "label": "Ledger",
            "summary": "Ledger summary that belongs in narration.",
            "teaching": {"controls": ["Ordered events", "Terminal state"]},
        },
    ]
    video_script = {
        "segments": [
            {"chapter": "Overview", "text": "Follow the evidence."},
            {"chapter": "Policy and Ledger", "text": "Policy summary. Ledger summary."},
            {"chapter": "Evidence boundary", "text": "Technical review is not publication."},
        ]
    }

    rendered = builder._composition(
        {"pack_id": "test-pack", "title": "Test Pack", "concepts": concepts},
        video_script,
        20.0,
    )

    assert rendered.count("MODEL INTENT") == 1
    assert "Controls: ALLOW, ASK, or DENY · Exact approval binding" in rendered
    assert rendered.count("Policy summary that belongs in narration.") == 0
    assert 'id="transition-curtain"' in rendered
    assert "tl.to(curtain,{autoAlpha:1,duration:.3" in rendered
    assert "tl.set(previous,{autoAlpha:0},start-.5)" in rendered
    assert "tl.set(scene,{autoAlpha:1,x:0},start-.5)" in rendered
    assert "xPercent" not in rendered
