#!/usr/bin/env python3
# ruff: noqa: E501  # Embedded SVG/HTML/CSS templates are intentionally kept readable in source.
"""Build the deterministic English request-lifecycle learning pilot."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs/visual-learning/pilot/request-lifecycle.json"
TEACHING = ROOT / "docs/visual-learning/pilot/diagram-teaching.json"
DEFAULT_OUTPUT = ROOT.parent / "cogentrex-learning-media"
OWNER = ".cogentrex-learning-library"
PALETTE = {
    "frontend": ("#3a2608", "#f6b44b"),
    "backend": ("#0b2447", "#6ee7ff"),
    "database": ("#21163b", "#a78bfa"),
    "security": ("#2b1420", "#fb7185"),
    "external": ("#1e293b", "#a9b4cc"),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _json(path: Path, payload: Any) -> None:
    _write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


@lru_cache(maxsize=1)
def _source_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _slug(label: str) -> str:
    return label.lower().replace(" ", "-")


def _node_details(teaching: dict[str, Any]) -> str:
    return " ".join(
        (
            teaching["definition"],
            teaching["responsibility"],
            teaching["failure_behavior"],
            teaching["why_it_matters"],
        )
    )


def _edge_explanation(teaching: dict[str, Any]) -> str:
    return " ".join(
        (
            teaching["payload"],
            teaching["transformation"],
            teaching["failure_behavior"],
            teaching["why_it_matters"],
        )
    )


def _diagram_content(
    diagram: dict[str, Any], teaching_spec: dict[str, Any]
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for label, kind in diagram["nodes"]:
        node_id = _slug(label)
        authored = teaching_spec["nodes"][node_id]
        teaching = authored["teaching"]
        nodes.append(
            {
                "id": node_id,
                "label": label,
                "kind": kind,
                "summary": authored["summary"],
                "details": _node_details(teaching),
                "teaching": teaching,
                "sources": authored["sources"],
            }
        )

    edges: list[dict[str, Any]] = []
    for source, target, label in diagram["edges"]:
        edge_id = f"{_slug(source)}-{_slug(target)}"
        authored = teaching_spec["edges"][edge_id]
        teaching = authored["teaching"]
        edges.append(
            {
                "id": edge_id,
                "source": _slug(source),
                "target": _slug(target),
                "label": label,
                "explanation": _edge_explanation(teaching),
                "teaching": teaching,
                "sources": authored["sources"],
            }
        )

    return {
        "description": diagram["description"],
        "nodes": nodes,
        "edges": edges,
        "modules": teaching_spec.get("modules", []),
    }


def _svg(diagram: dict[str, Any]) -> str:
    nodes = diagram["nodes"]
    width = 1400
    box_w, box_h, gap, x0, y = 130, 84, 24, 30, 170
    centers: dict[str, tuple[float, float]] = {}
    boxes: list[str] = []
    for index, (label, kind) in enumerate(nodes):
        x = x0 + index * (box_w + gap)
        fill, stroke = PALETTE.get(kind, PALETTE["external"])
        centers[label] = (x + box_w / 2, y + box_h / 2)
        wrapped = label.replace(" and ", "\nand ").split("\n")
        text = "".join(
            f'<text x="{x + box_w / 2}" y="{y + 37 + line_index * 18}" text-anchor="middle" fill="#f4f7fb" font-size="13">{html.escape(line)}</text>'
            for line_index, line in enumerate(wrapped)
        )
        boxes.append(
            f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2"/>{text}'
        )
    arrows: list[str] = []
    for source, target, label in diagram["edges"]:
        sx, sy = centers[source]
        tx, ty = centers[target]
        arrows.append(
            f'<path d="M {sx + box_w / 2} {sy} L {tx - box_w / 2} {ty}" stroke="#f6b44b" stroke-width="2" marker-end="url(#arrow)"/>'
            f'<text x="{(sx + tx) / 2}" y="{sy - 14}" text-anchor="middle" fill="#cbd5e1" font-size="10">{html.escape(label)}</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 430" role="img" aria-labelledby="title desc">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#f6b44b"/></marker><pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M 32 0 L 0 0 0 32" fill="none" stroke="#26324d" stroke-width="0.5"/></pattern></defs>
<title id="title">{html.escape(diagram["title"])}</title><desc id="desc">{html.escape(diagram["description"])}</desc>
<rect width="100%" height="100%" rx="18" fill="#050712"/><rect width="100%" height="100%" fill="url(#grid)"/>
<text x="32" y="52" fill="#f4f7fb" font-size="26" font-family="system-ui" font-weight="700">{html.escape(diagram["title"])}</text>
<text x="32" y="82" fill="#a9b4cc" font-size="14" font-family="system-ui">{html.escape(diagram["description"])}</text>
{"".join(arrows)}{"".join(boxes)}
<text x="32" y="385" fill="#a9b4cc" font-size="12" font-family="system-ui">Generated from reviewed Cogentrex sources · Derived learning material</text>
</svg>"""


def _deck_html(spec: dict[str, Any], diagrams: dict[str, str]) -> str:
    slides = []
    source_commit = _source_commit()
    for index, slide in enumerate(spec["slides"], start=1):
        visual = diagrams.get(slide["visual"], "")
        sources = "".join(
            f'<li><a href="https://github.com/levalencia/cogentrex/blob/{source_commit}/{html.escape(source)}" target="_blank" rel="noopener noreferrer">{html.escape(source)}</a></li>'
            for source in slide["sources"]
        )
        terms = "".join(
            f'<dt>{html.escape(item["term"])}</dt><dd>{html.escape(item["definition"])}</dd>'
            for item in slide["key_terms"]
        )
        slides.append(f"""<section class="slide" id="slide-{index}" aria-label="Slide {index} of {len(spec["slides"])}">
<div class="counter">{index:02d} / {len(spec["slides"]):02d}</div><p class="eyebrow">COGENTREX REQUEST LIFECYCLE</p>
<h2>{html.escape(slide["title"])}</h2><p class="message">{html.escape(slide["message"])}</p>
<div class="visual">{visual or f'<div class="concept">{html.escape(slide["visual"].replace("-", " ").title())}</div>'}</div>
<details><summary>Teach this slide</summary><h3>Presenter script</h3><p>{html.escape(slide["presenter_script"])}</p><h3>Key terms</h3><dl>{terms}</dl><h3>Common misconception</h3><p>{html.escape(slide["common_misconception"])}</p><h3>Transition</h3><p>{html.escape(slide["transition"])}</p><h3>Supporting documentation</h3><ul>{sources}</ul></details>
<nav><a href="#slide-{max(1, index - 1)}" aria-label="Previous slide">←</a><a href="#slide-{min(len(spec["slides"]), index + 1)}" aria-label="Next slide">→</a></nav></section>""")
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in spec["limitations"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(spec["title"])}</title><style>
:root{{--bg:#050712;--panel:#0a1022;--text:#f4f7fb;--muted:#a9b4cc;--accent:#f6b44b;--border:#26324d}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-snap-type:y mandatory}}body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}}.slide{{position:relative;min-height:100vh;padding:6vh 7vw;scroll-snap-align:start;display:grid;grid-template-rows:auto auto auto 1fr auto;gap:1rem;border-bottom:1px solid var(--border)}}.eyebrow,.counter{{font:700 .72rem ui-monospace;letter-spacing:.16em;color:var(--accent)}}.counter{{position:absolute;right:3vw;top:3vh;color:var(--muted)}}h2{{font-size:clamp(2rem,5vw,4.6rem);line-height:1;margin:0;max-width:18ch}}.message{{font-size:clamp(1rem,2vw,1.45rem);line-height:1.5;color:#cbd5e1;max-width:70ch}}.visual{{display:grid;place-items:center;min-height:300px;border:1px solid var(--border);border-radius:18px;background:#07101f;overflow:auto}}.visual svg{{width:100%;height:auto}}.concept{{font-size:clamp(2rem,6vw,5rem);font-weight:800;color:var(--accent);text-align:center;text-transform:uppercase}}details{{color:var(--muted);font-size:.82rem;line-height:1.65}}details h3{{color:var(--accent);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;margin:1rem 0 .35rem}}details dl{{display:grid;grid-template-columns:auto 1fr;gap:.35rem .75rem}}details dt{{color:var(--text);font-weight:700}}details dd{{margin:0}}details a{{color:var(--accent)}}summary{{cursor:pointer;color:#cbd5e1;font-weight:700}}nav{{position:absolute;right:3vw;bottom:3vh;display:flex;gap:.5rem}}nav a{{display:grid;place-items:center;width:44px;height:44px;border:1px solid var(--border);border-radius:50%;color:var(--text);text-decoration:none}}.limits{{padding:2rem;max-width:900px;margin:auto;color:var(--muted)}}@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}@media print{{html{{scroll-snap-type:none}}.slide{{break-after:page;min-height:95vh}}nav{{display:none}}}}</style></head><body>{"".join(slides)}<footer class="limits"><h2>What this does not prove</h2><ul>{limitations}</ul></footer></body></html>"""


def _artifact_payload(spec: dict[str, Any], kind: str, content: Any, schema: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "artifact_id": f"request-{kind}",
        "pack_id": spec["pack_id"],
        "title": f"{spec['title']} — {kind.replace('-', ' ').title()}",
        "language": "en",
        "source_commit": _source_commit(),
        "limitations": spec["limitations"],
        "sources": spec["sources"],
        **content,
    }


def build(output: Path, *, audio: Path | None = None, video: Path | None = None) -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    teaching_specs = json.loads(TEACHING.read_text(encoding="utf-8"))
    if spec.get("language") != "en":
        raise ValueError("pilot content must be English")
    for source in spec["sources"]:
        candidate = (ROOT / source).resolve()
        if ROOT not in candidate.parents or not candidate.is_file():
            raise ValueError(f"unsafe or missing source: {source}")

    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not (output / OWNER).is_file():
        raise ValueError("refusing non-empty unowned learning-media directory")
    output.mkdir(parents=True, exist_ok=True)
    _write(output / OWNER, "cogentrex.learning-library/v1\n")
    published = output / "published" / spec["pack_id"]
    published.mkdir(parents=True, exist_ok=True)

    diagram_svgs = {item["id"]: _svg(item) for item in spec["diagrams"]}
    artifacts: list[dict[str, Any]] = []

    def add(
        artifact_id: str,
        kind: str,
        title: str,
        primary: Path,
        content: Path | None = None,
        duration: float | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "id": artifact_id,
            "type": kind,
            "title": title,
            "status": "review-ready",
            "language": "en",
            "file": primary.relative_to(output).as_posix(),
            "media_type": {
                ".html": "text/html",
                ".json": "application/json",
                ".svg": "image/svg+xml",
                ".mp3": "audio/mpeg",
                ".mp4": "video/mp4",
            }[primary.suffix.lower()],
            "sha256": _sha(primary),
            "source_commit": _source_commit(),
            "limitations": spec["limitations"],
        }
        if content is not None:
            item["content_file"] = content.relative_to(output).as_posix()
            item["content_sha256"] = _sha(content)
        if duration is not None:
            item["duration_seconds"] = duration
        artifacts.append(item)

    deck_dir = published / "request-deck"
    deck_data = _artifact_payload(spec, "deck", {"slides": spec["slides"]}, "cogentrex.learning.deck")
    _json(deck_dir / "deck.json", deck_data)
    _write(deck_dir / "deck.html", _deck_html(spec, diagram_svgs))
    add(
        "request-deck",
        "deck",
        "Request Lifecycle Visual Deck",
        deck_dir / "deck.html",
        deck_dir / "deck.json",
    )

    for index, diagram in enumerate(spec["diagrams"]):
        directory = published / f"request-diagram-{index + 1}"
        diagram_data = _artifact_payload(
            spec,
            f"diagram-{index + 1}",
            _diagram_content(diagram, teaching_specs[diagram["id"]]),
            "cogentrex.learning.diagram",
        )
        _json(directory / "diagram.json", diagram_data)
        _write(directory / "diagram.svg", diagram_svgs[diagram["id"]])
        add(
            f"request-diagram-{index + 1}",
            "diagram" if index < 2 else "infographic",
            diagram["title"],
            directory / "diagram.svg",
            directory / "diagram.json",
        )

    mind = _artifact_payload(
        spec, "mind-map", {"root": spec["mind_map"]}, "cogentrex.learning.mind-map"
    )
    mind_path = published / "request-mind-map" / "mind-map.json"
    _json(mind_path, mind)
    add("request-mind-map", "mind-map", "Request Lifecycle Mind Map", mind_path)

    cards = []
    for index, (question, answer, explanation, misconception) in enumerate(spec["flashcards"], 1):
        cards.append(
            {
                "id": f"card-{index}",
                "question": question,
                "answer": answer,
                "explanation": explanation,
                "misconception": misconception,
                "sources": spec["sources"][:2],
            }
        )
    flashcards = _artifact_payload(
        spec, "flashcards", {"cards": cards}, "cogentrex.learning.flashcards"
    )
    cards_path = published / "request-flashcards" / "flashcards.json"
    _json(cards_path, flashcards)
    add("request-flashcards", "flashcards", "Request Lifecycle Flashcards", cards_path)

    questions = []
    for index, question in enumerate(spec["quiz"], 1):
        questions.append({"id": f"question-{index}", **question, "sources": spec["sources"][:2]})
    quiz = _artifact_payload(spec, "quiz", {"questions": questions}, "cogentrex.learning.quiz")
    quiz_path = published / "request-quiz" / "quiz.json"
    _json(quiz_path, quiz)
    add("request-quiz", "quiz", "Request Lifecycle Scenario Quiz", quiz_path)

    sections = [{**section, "sources": spec["sources"][:2]} for section in spec["study_guide"]]
    guide = _artifact_payload(
        spec, "study-guide", {"sections": sections}, "cogentrex.learning.study-guide"
    )
    guide_path = published / "request-study-guide" / "study-guide.json"
    _json(guide_path, guide)
    add("request-study-guide", "study-guide", "Request Lifecycle Study Guide", guide_path)

    audio_script = _artifact_payload(
        spec,
        "audio-script",
        {
            "format": "narration",
            "segments": [
                {"speaker": "narrator", **segment, "sources": spec["sources"][:2]}
                for segment in spec["audio_script"]
            ],
        },
        "cogentrex.learning.audio-script",
    )
    audio_script_path = published / "request-audio" / "audio-script.json"
    _json(audio_script_path, audio_script)
    transcript = "\n\n".join(
        f"## {item['chapter']}\n\n{item['text']}" for item in spec["audio_script"]
    )
    _write(published / "request-audio" / "transcript.md", transcript + "\n")
    if audio is not None:
        audio_target = published / "request-audio" / "request-lifecycle.mp3"
        _write(audio_target, audio.read_bytes())
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(audio_target),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        add(
            "request-audio",
            "audio",
            "Request Lifecycle Audio Lesson",
            audio_target,
            audio_script_path,
            float(probe.stdout.strip()),
        )

    if video is not None:
        video_target = published / "request-video" / "request-lifecycle.mp4"
        _write(video_target, video.read_bytes())
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(video_target),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        add(
            "request-video",
            "video",
            "Request Lifecycle Explainer",
            video_target,
            audio_script_path,
            float(probe.stdout.strip()),
        )

    catalog = {
        "schema": "cogentrex.learning-library",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": _source_commit(),
        "packs": [
            {
                "id": spec["pack_id"],
                "title": spec["title"],
                "purpose": spec["purpose"],
                "artifacts": artifacts,
            }
        ],
    }
    _json(output / "catalog.json", catalog)
    return output / "catalog.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--video", type=Path)
    args = parser.parse_args()
    print(build(args.output, audio=args.audio, video=args.video))


if __name__ == "__main__":
    main()
