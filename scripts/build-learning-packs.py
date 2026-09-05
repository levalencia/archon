#!/usr/bin/env python3
# ruff: noqa: E501  # Standalone educational HTML/SVG templates are intentionally readable.
"""Build the source-authored Visual Learning Studio packs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "docs/visual-learning/packs"
MANIFEST = ROOT / "docs/visual-learning/learning-artifacts.yaml"
DEFAULT_OUTPUT = ROOT.parent / "archon-learning-media"
OWNER = ".archon-learning-library"
PACK_IDS = (
    "system-overview",
    "memory-rag-evaluation",
    "reliability-operations",
    "interview-demo",
    "hybrid-agent-orchestration",
)
FORBIDDEN_PHRASES = (
    "owns one explicit responsibility",
    "identifies which component initiates",
    "lorem ipsum",
    "todo",
    "placeholder",
    "generic explanation",
)
PALETTE = {
    "canvas": "#050b16",
    "surface": "#0f172a",
    "raised": "#111c2e",
    "text": "#f8fafc",
    "muted": "#94a3b8",
    "orange": "#f59e0b",
    "green": "#22c55e",
    "coral": "#fb7185",
    "blue": "#3b82f6",
    "purple": "#a78bfa",
    "border": "#334155",
}
KIND_COLORS = {
    "frontend": ("#3a2608", PALETTE["orange"]),
    "backend": ("#0b2447", PALETTE["blue"]),
    "database": ("#21163b", PALETTE["purple"]),
    "security": ("#2b1420", PALETTE["coral"]),
    "external": ("#1e293b", PALETTE["muted"]),
}


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


def _json(path: Path, value: Any) -> None:
    _write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _schema(name: str) -> dict[str, Any]:
    return json.loads(
        (ROOT / "schemas/visual-learning" / f"{name}.schema.json").read_text(encoding="utf-8")
    )


def _base(spec: dict[str, Any], artifact_id: str, title: str, schema: str) -> dict[str, Any]:
    return {
        "schema": schema,
        "version": 1,
        "artifact_id": artifact_id,
        "pack_id": spec["pack_id"],
        "title": title,
        "language": "en",
        "source_commit": _commit(),
        "limitations": spec["limitations"],
        "sources": sorted({source for concept in spec["concepts"] for source in concept["sources"]}),
    }


def _details(concept: dict[str, Any]) -> str:
    teaching = concept["teaching"]
    return " ".join(
        [
            teaching["definition"],
            teaching["responsibility"],
            teaching["failure_behavior"],
            teaching["why_it_matters"],
            f"Limitation: {concept['boundary']}",
        ]
    )


def _edge(source: dict[str, Any], target: dict[str, Any], index: int) -> dict[str, Any]:
    payload = f"{'; '.join(source['teaching']['produces'])} move from {source['label']} toward {target['label']}."
    teaching = {
        "payload": payload,
        "transformation": f"The handoff occurs only after {source['label']} completes its responsibility: {source['teaching']['responsibility']}",
        "trust_boundary": f"Responsibility crosses from {source['label']} to {target['label']}; the receiving component still applies its own controls rather than trusting prose or labels.",
        "precondition": f"Upstream scope and controls must hold, including {source['teaching']['controls'][0].lower()}.",
        "failure_behavior": f"If the handoff cannot satisfy that precondition, processing stops or records an explicit failure; {target['label']} must not infer success.",
        "why_it_matters": f"This separation keeps {source['label']}'s output distinct from {target['label']}'s responsibility: {target['teaching']['responsibility']}",
    }
    return {
        "id": f"edge-{index}-{source['id']}-{target['id']}",
        "source": source["id"],
        "target": target["id"],
        "label": f"{source['label']} → {target['label']}",
        "explanation": " ".join(teaching.values()),
        "teaching": teaching,
        "sources": sorted(set(source["sources"] + target["sources"])),
    }


def _diagram(spec: dict[str, Any], flow: dict[str, Any], artifact_id: str, *, modules: bool = False) -> dict[str, Any]:
    concepts = {item["id"]: item for item in spec["concepts"]}
    selected = [concepts[item] for item in flow["nodes"]]
    nodes = [
        {
            "id": item["id"],
            "label": item["label"],
            "kind": item["kind"],
            "summary": item["summary"],
            "details": _details(item),
            "teaching": item["teaching"],
            "sources": item["sources"],
        }
        for item in selected
    ]
    edges = [_edge(left, right, index) for index, (left, right) in enumerate(zip(selected, selected[1:], strict=False), 1)]
    payload = {
        **_base(spec, artifact_id, flow["title"], "archon.learning.diagram"),
        "description": flow["description"],
        "nodes": nodes,
        "edges": edges,
    }
    if modules:
        payload["modules"] = [
            {
                "id": f"module-{item['id']}",
                "label": item["label"],
                "category": ("principle", "architecture", "impact")[index % 3],
                "summary": item["summary"],
                "details": f"{_details(item)} What this does not prove: {item['boundary']}",
                "sources": item["sources"],
            }
            for index, item in enumerate(spec["concepts"])
        ]
    Draft202012Validator(_schema("diagram")).validate(payload)
    return payload


def _svg(diagram: dict[str, Any]) -> str:
    nodes = diagram["nodes"]
    width, height = 1600, 620
    box_w, box_h, gap, x0, y = 180, 112, 44, 44, 240
    total = len(nodes) * box_w + max(0, len(nodes) - 1) * gap
    scale = min(1.0, (width - 88) / total)
    slot = (box_w + gap) * scale
    actual_w = box_w * scale
    boxes: list[str] = []
    arrows: list[str] = []
    centers: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(nodes):
        x = x0 + index * slot
        fill, stroke = KIND_COLORS.get(node["kind"], KIND_COLORS["external"])
        centers[node["id"]] = (x + actual_w / 2, y + box_h / 2)
        words = node["label"].split()
        midpoint = max(1, len(words) // 2)
        lines = [" ".join(words[:midpoint]), " ".join(words[midpoint:])] if len(words) > 2 else [node["label"]]
        text = "".join(
            f'<text x="{x + actual_w / 2:.1f}" y="{y + 49 + line * 24}" text-anchor="middle" fill="{PALETTE["text"]}" font-size="{max(16, 22 * scale):.1f}" font-family="system-ui" font-weight="700">{html.escape(value)}</text>'
            for line, value in enumerate(lines)
        )
        boxes.append(f'<g role="group" aria-label="{html.escape(node["label"])}"><rect x="{x:.1f}" y="{y}" width="{actual_w:.1f}" height="{box_h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="3"/>{text}</g>')
    for edge in diagram["edges"]:
        sx, sy = centers[edge["source"]]
        tx, ty = centers[edge["target"]]
        arrows.append(f'<path d="M {sx + actual_w / 2:.1f} {sy:.1f} L {tx - actual_w / 2:.1f} {ty:.1f}" stroke="{PALETTE["orange"]}" stroke-width="3" marker-end="url(#arrow)"/><rect x="{(sx+tx)/2-42:.1f}" y="{sy-20:.1f}" width="84" height="24" rx="8" fill="{PALETTE["canvas"]}"/><text x="{(sx+tx)/2:.1f}" y="{sy-4:.1f}" text-anchor="middle" fill="{PALETTE["text"]}" font-size="11" font-family="system-ui">handoff</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc"><title id="title">{html.escape(diagram["title"])}</title><desc id="desc">{html.escape(diagram["description"])}</desc><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M0 0 L10 5 L0 10z" fill="{PALETTE["orange"]}"/></marker><pattern id="grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke="{PALETTE["border"]}" stroke-width=".5"/></pattern></defs><rect width="100%" height="100%" fill="{PALETTE["canvas"]}"/><rect width="100%" height="100%" fill="url(#grid)"/><text x="44" y="62" fill="{PALETTE["text"]}" font-size="34" font-family="system-ui" font-weight="800">{html.escape(diagram["title"])}</text><text x="44" y="98" fill="{PALETTE["muted"]}" font-size="18" font-family="system-ui">{html.escape(diagram["description"])}</text>{''.join(arrows)}{''.join(boxes)}<text x="44" y="570" fill="{PALETTE["muted"]}" font-size="15" font-family="system-ui">Select nodes and arrows in Archon for detailed teaching and commit-pinned sources.</text></svg>'''


def _slides(spec: dict[str, Any]) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    for index, concept in enumerate(spec["concepts"], 1):
        t = concept["teaching"]
        script = " ".join(
            [
                t["definition"],
                f"It receives {', '.join(t['receives'])}.",
                t["responsibility"],
                f"It produces {', '.join(t['produces'])}.",
                f"Its main controls are {', '.join(t['controls'])}.",
                t["failure_behavior"],
                t["why_it_matters"],
                f"Keep this evidence boundary explicit: {concept['boundary']}",
            ]
        )
        slides.append(
            {
                "id": f"slide-{index}",
                "title": concept["label"],
                "message": concept["summary"],
                "visual": spec["flows"][0 if index <= len(spec["concepts"]) // 2 else 1]["id"],
                "notes": f"Teach {concept['label']} through responsibility, controls, failure behavior, and evidence boundary.",
                "presenter_script": script,
                "key_terms": [{"term": concept["label"], "definition": t["definition"]}],
                "common_misconception": f"Misconception: {concept['label']} proves more than its boundary. Correction: {concept['boundary']}",
                "transition": f"Next, connect this responsibility to {spec['concepts'][index % len(spec['concepts'])]['label']} without collapsing their boundaries.",
                "sources": concept["sources"],
            }
        )
    return slides


def _deck_html(deck: dict[str, Any], svgs: dict[str, str]) -> str:
    sections = []
    total = len(deck["slides"])
    for index, slide in enumerate(deck["slides"], 1):
        links = "".join(f'<li><a href="https://github.com/levalencia/archon/blob/{deck["source_commit"]}/{html.escape(source)}" target="_blank" rel="noopener noreferrer">{html.escape(source)}</a></li>' for source in slide["sources"])
        sections.append(f'''<section class="slide" id="slide-{index}" aria-label="Slide {index} of {total}"><span class="counter">{index:02d}/{total:02d}</span><p class="eyebrow">ARCHON EVIDENCE DARK</p><h2>{html.escape(slide["title"])}</h2><p class="message">{html.escape(slide["message"])}</p><div class="visual">{svgs[slide["visual"]]}</div><details><summary>Teach this slide</summary><h3>Presenter script</h3><p>{html.escape(slide["presenter_script"])}</p><h3>Common misconception</h3><p>{html.escape(slide["common_misconception"])}</p><h3>Transition</h3><p>{html.escape(slide["transition"])}</p><h3>Sources</h3><ul>{links}</ul></details><nav><a href="#slide-{max(1,index-1)}" aria-label="Previous slide">←</a><a href="#slide-{min(total,index+1)}" aria-label="Next slide">→</a></nav></section>''')
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in deck["limitations"])
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(deck["title"])}</title><style>:root{{--bg:#050b16;--panel:#0f172a;--text:#f8fafc;--muted:#94a3b8;--accent:#f59e0b;--border:#334155}}*{{box-sizing:border-box}}html{{scroll-snap-type:y mandatory;scroll-behavior:smooth}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,sans-serif}}.slide{{position:relative;min-height:100vh;padding:5vh 6vw;display:grid;grid-template-rows:auto auto auto 1fr auto;gap:1rem;scroll-snap-align:start;border-bottom:1px solid var(--border)}}.counter{{position:absolute;right:3vw;top:3vh;color:var(--muted);font-family:monospace}}.eyebrow{{color:var(--accent);font:bold .75rem monospace;letter-spacing:.17em}}h2{{font-size:clamp(2rem,5vw,4.5rem);line-height:1;margin:0}}.message{{font-size:clamp(1rem,2vw,1.4rem);color:#cbd5e1;max-width:72ch}}.visual{{min-height:280px;border:1px solid var(--border);border-radius:18px;overflow:auto;background:#07101f}}.visual svg{{display:block;width:100%;height:auto}}details{{color:var(--muted);line-height:1.65}}details h3,a{{color:var(--accent)}}nav{{position:absolute;right:3vw;bottom:3vh;display:flex;gap:.5rem}}nav a{{display:grid;place-items:center;width:44px;height:44px;border:1px solid var(--accent);border-radius:50%;color:var(--text);text-decoration:none;box-shadow:0 0 18px rgba(245,158,11,.22)}}.limits{{padding:2rem 6vw;color:var(--muted)}}@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}</style></head><body>{''.join(sections)}<footer class="limits"><h2>What this does not prove</h2><ul>{limits}</ul><p>Source commit <code>{deck["source_commit"]}</code></p></footer></body></html>'''


def _mind_map(spec: dict[str, Any]) -> dict[str, Any]:
    concepts = {item["id"]: item for item in spec["concepts"]}
    children = []
    for group_index, group in enumerate(spec["mind_groups"], 1):
        members = [concepts[item] for item in group["concepts"]]
        children.append(
            {
                "id": f"group-{group_index}",
                "label": group["label"],
                "summary": " · ".join(item["label"] for item in members),
                "details": " ".join(item["summary"] for item in members),
                "sources": sorted({source for item in members for source in item["sources"]}),
                "children": [
                    {"id": item["id"], "label": item["label"], "summary": item["summary"], "details": _details(item), "sources": item["sources"], "children": []}
                    for item in members
                ],
            }
        )
    return {"id": spec["pack_id"], "label": spec["title"], "summary": spec["purpose"], "details": "Explore each branch progressively; sources and limitations remain attached to every concept.", "sources": sorted({source for item in spec["concepts"] for source in item["sources"]}), "children": children}


def _audio(spec: dict[str, Any]) -> list[dict[str, Any]]:
    segments = []
    pairs = [spec["concepts"][index:index + 2] for index in range(0, len(spec["concepts"]), 2)]
    for pair in pairs:
        text = " ".join(f"{item['narration']} Evidence boundary: {item['boundary']}" for item in pair)
        segments.append({"speaker": "narrator", "chapter": " and ".join(item["label"] for item in pair), "text": text, "sources": sorted({source for item in pair for source in item["sources"]})})
    return segments


def _video_segments(spec: dict[str, Any]) -> list[dict[str, Any]]:
    segments = [{
        "speaker": "narrator",
        "chapter": spec["title"],
        "text": f"{spec['purpose']} Follow the evidence, not the feature list.",
        "sources": spec["concepts"][0]["sources"],
    }]
    for index in range(0, len(spec["concepts"]), 2):
        pair = spec["concepts"][index:index + 2]
        segments.append({
            "speaker": "narrator",
            "chapter": " and ".join(item["label"] for item in pair),
            "text": " ".join(item["summary"] for item in pair),
            "sources": sorted({source for item in pair for source in item["sources"]}),
        })
    segments.append({
        "speaker": "narrator",
        "chapter": "Evidence boundary",
        "text": "Technical checks make this pack review-ready, not accepted. Final educational quality remains a human decision, and no artifact proves public deployment.",
        "sources": ["docs/IMPLEMENTATION-EVIDENCE.md", "docs/REMAINING-DEFERRED-GAPS.md"],
    })
    return segments


def _probe(path: Path) -> dict[str, Any]:
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type,width,height:format=duration,size", "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return json.loads(raw.stdout)


def _validate_spec(spec: dict[str, Any], allowed: set[str]) -> None:
    if spec.get("language") != "en" or spec.get("pack_id") not in PACK_IDS:
        raise ValueError("pack language or ID is invalid")
    if len(spec.get("concepts", [])) != 10:
        raise ValueError(f"{spec.get('pack_id')} must author exactly ten concepts")
    serialized = json.dumps(spec).lower()
    if any(phrase in serialized for phrase in FORBIDDEN_PHRASES):
        raise ValueError(f"{spec['pack_id']} contains a placeholder phrase")
    ids = [item["id"] for item in spec["concepts"]]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{spec['pack_id']} concept IDs must be unique")
    required_teaching = {"definition", "receives", "responsibility", "produces", "controls", "failure_behavior", "why_it_matters"}
    for concept in spec["concepts"]:
        if set(concept["teaching"]) != required_teaching or len(_details(concept).split()) < 60:
            raise ValueError(f"{spec['pack_id']} concept {concept['id']} lacks pedagogical depth")
        if not set(concept["sources"]).issubset(allowed):
            raise ValueError(f"{spec['pack_id']} concept {concept['id']} uses an undeclared source")
        for source in concept["sources"]:
            candidate = (ROOT / source).resolve()
            if ROOT not in candidate.parents or not candidate.is_file():
                raise ValueError(f"unsafe or missing source: {source}")
        if len(concept["options"]) < 4 or not 0 <= concept["correct_index"] < len(concept["options"]):
            raise ValueError(f"{spec['pack_id']} concept {concept['id']} has an invalid scenario")


def build(output: Path, media_root: Path | None = None) -> Path:
    config = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    declarations = {item["id"]: item for item in config["packs"]}
    output = output.expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not (output / OWNER).is_file():
        raise ValueError("refusing non-empty unowned learning-media directory")
    output.mkdir(parents=True, exist_ok=True)
    _write(output / OWNER, "archon.learning-library/v1\n")
    catalog_path = output / "catalog.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.is_file() else {"schema":"archon.learning-library","version":1,"generated_at":"","source_commit":_commit(),"packs":[]}
    catalog["packs"] = [pack for pack in catalog["packs"] if pack["id"] not in PACK_IDS]

    for pack_id in PACK_IDS:
        spec = json.loads((PACK_DIR / f"{pack_id}.json").read_text(encoding="utf-8"))
        declaration = declarations[pack_id]
        allowed = set(config.get("source_priority", [])) | set(declaration["sources"])
        _validate_spec(spec, allowed)
        published = output / "published" / pack_id
        artifacts: list[dict[str, Any]] = []

        def add(artifact_id: str, kind: str, title: str, primary: Path, content: Path | None = None, duration: float | None = None, *, spec_ref: dict[str, Any] = spec, artifacts_ref: list[dict[str, Any]] = artifacts) -> None:
            item: dict[str, Any] = {"id":artifact_id,"type":kind,"title":title,"status":"review-ready","language":"en","file":primary.relative_to(output).as_posix(),"media_type":{ ".html":"text/html", ".svg":"image/svg+xml", ".json":"application/json", ".mp3":"audio/mpeg", ".mp4":"video/mp4"}[primary.suffix.lower()],"sha256":_sha(primary),"source_commit":_commit(),"limitations":spec_ref["limitations"]}
            if content is not None:
                item["content_file"] = content.relative_to(output).as_posix()
                item["content_sha256"] = _sha(content)
            if duration is not None:
                item["duration_seconds"] = duration
            artifacts_ref.append(item)

        diagrams: list[dict[str, Any]] = []
        svg_by_flow: dict[str, str] = {}
        for flow_index, flow in enumerate(spec["flows"], 1):
            artifact_id = f"{pack_id}-diagram-{flow_index}"
            diagram = _diagram(spec, flow, artifact_id)
            diagrams.append(diagram)
            svg = _svg(diagram)
            svg_by_flow[flow["id"]] = svg
            directory = published / artifact_id
            data_path, svg_path = directory / "diagram.json", directory / "diagram.svg"
            _json(data_path, diagram)
            _write(svg_path, svg)
            add(artifact_id, "diagram", flow["title"], svg_path, data_path)

        infographic_id = f"{pack_id}-infographic"
        infographic_flow = {"id":"infographic","title":f"{spec['title']} — Evidence Modules","description":"Select a module to inspect its responsibility, failure behavior, sources, and evidence boundary.","nodes":[item["id"] for item in spec["concepts"][:6]]}
        infographic = _diagram(spec, infographic_flow, infographic_id, modules=True)
        infographic_dir = published / infographic_id
        _json(infographic_dir / "infographic.json", infographic)
        _write(infographic_dir / "infographic.svg", _svg(infographic))
        add(infographic_id, "infographic", infographic_flow["title"], infographic_dir / "infographic.svg", infographic_dir / "infographic.json")

        deck_id = f"{pack_id}-deck"
        deck = {**_base(spec, deck_id, f"{spec['title']} — Presentation", "archon.learning.deck"), "slides": _slides(spec)}
        Draft202012Validator(_schema("deck")).validate(deck)
        deck_dir = published / deck_id
        _json(deck_dir / "deck.json", deck)
        _write(deck_dir / "deck.html", _deck_html(deck, svg_by_flow))
        add(deck_id, "deck", deck["title"], deck_dir / "deck.html", deck_dir / "deck.json")

        mind_id = f"{pack_id}-mind-map"
        mind = {**_base(spec, mind_id, f"{spec['title']} — Mind Map", "archon.learning.mind-map"), "root": _mind_map(spec)}
        Draft202012Validator(_schema("mind-map")).validate(mind)
        mind_path = published / mind_id / "mind-map.json"
        _json(mind_path, mind)
        add(mind_id,"mind-map",mind["title"],mind_path)

        cards_id = f"{pack_id}-flashcards"
        cards = []
        for index, concept in enumerate(spec["concepts"], 1):
            cards.extend([
                {"id":f"card-{index}-definition","question":f"What is {concept['label']} responsible for?","answer":concept["teaching"]["responsibility"],"explanation":concept["teaching"]["why_it_matters"],"misconception":f"It is not evidence beyond this boundary: {concept['boundary']}","sources":concept["sources"]},
                {"id":f"card-{index}-failure","question":f"How does {concept['label']} fail safely, and what remains unproven?","answer":concept["teaching"]["failure_behavior"],"explanation":concept["boundary"],"misconception":"A controlled failure or deterministic test is not automatically a successful live or deployed outcome.","sources":concept["sources"]},
            ])
        flashcards = {**_base(spec,cards_id,f"{spec['title']} — Flashcards","archon.learning.flashcards"),"cards":cards}
        Draft202012Validator(_schema("flashcards")).validate(flashcards)
        cards_path=published/cards_id/"flashcards.json"
        _json(cards_path,flashcards)
        add(cards_id,"flashcards",flashcards["title"],cards_path)

        quiz_id=f"{pack_id}-quiz"
        questions=[{"id":f"question-{index}","scenario":item["scenario"],"options":item["options"],"correct_index":item["correct_index"],"explanation":item["scenario_explanation"],"sources":item["sources"]} for index,item in enumerate(spec["concepts"],1)]
        quiz={**_base(spec,quiz_id,f"{spec['title']} — Scenario Quiz","archon.learning.quiz"),"questions":questions}
        Draft202012Validator(_schema("quiz")).validate(quiz)
        quiz_path=published/quiz_id/"quiz.json"
        _json(quiz_path,quiz)
        add(quiz_id,"quiz",quiz["title"],quiz_path)

        guide_id=f"{pack_id}-study-guide"
        sections=[{"heading":"Mental model","body":spec["purpose"]+" Use the diagrams to follow responsibilities and the mind map to compare boundaries.","sources":spec["concepts"][0]["sources"]}]
        sections += [{"heading":item["label"],"body":_details(item),"sources":item["sources"]} for item in spec["concepts"]]
        sections.append({"heading":"What this does not prove","body":" ".join(spec["limitations"]),"sources":["docs/IMPLEMENTATION-EVIDENCE.md","docs/REMAINING-DEFERRED-GAPS.md"]})
        guide={**_base(spec,guide_id,f"{spec['title']} — Study Guide","archon.learning.study-guide"),"sections":sections}
        Draft202012Validator(_schema("study-guide")).validate(guide)
        guide_path=published/guide_id/"study-guide.json"
        _json(guide_path,guide)
        add(guide_id,"study-guide",guide["title"],guide_path)

        audio_id=f"{pack_id}-audio"
        segments=_audio(spec)
        audio_script={**_base(spec,audio_id,f"{spec['title']} — Audio Lesson","archon.learning.audio-script"),"format":"narration","segments":segments}
        Draft202012Validator(_schema("audio-script")).validate(audio_script)
        audio_dir=published/audio_id
        _json(audio_dir/"audio-script.json",audio_script)
        _write(audio_dir/"transcript.md","\n\n".join(f"## {item['chapter']}\n\n{item['text']}" for item in segments)+"\n")

        video_segments = _video_segments(spec)
        video_script = {**_base(spec,f"{pack_id}-video-script",f"{spec['title']} — Video Transcript","archon.learning.audio-script"),"format":"narration","segments":video_segments}
        Draft202012Validator(_schema("audio-script")).validate(video_script)
        video_dir = published / f"{pack_id}-video"
        _json(video_dir / "video-script.json", video_script)
        storyboard_id=f"{pack_id}-video-storyboard"
        scenes=[{"id":f"scene-{index}","duration_seconds":12,"narration":segment["text"],"visual":segment["chapter"],"sources":segment["sources"]} for index,segment in enumerate(video_segments,1)]
        storyboard={**_base(spec,storyboard_id,f"{spec['title']} — Video Storyboard","archon.learning.video-storyboard"),"width":1920,"height":1080,"fps":30,"scenes":scenes}
        Draft202012Validator(_schema("video-storyboard")).validate(storyboard)
        _json(video_dir/"storyboard.json",storyboard)

        if media_root is not None:
            audio_source=media_root/pack_id/f"{pack_id}.mp3"
            video_source=media_root/pack_id/f"{pack_id}.mp4"
            if audio_source.is_file():
                target=audio_dir/f"{pack_id}.mp3"
                shutil.copyfile(audio_source,target)
                probe=_probe(target)
                add(audio_id,"audio",audio_script["title"],target,audio_dir/"audio-script.json",float(probe["format"]["duration"]))
            if video_source.is_file():
                target=video_dir/f"{pack_id}.mp4"
                shutil.copyfile(video_source,target)
                probe=_probe(target)
                add(f"{pack_id}-video","video",f"{spec['title']} — Explainer Video",target,video_dir/"video-script.json",float(probe["format"]["duration"]))

        catalog["packs"].append({"id":pack_id,"title":spec["title"],"purpose":spec["purpose"],"artifacts":artifacts})

    catalog["generated_at"] = datetime.now(UTC).isoformat()
    catalog["source_commit"] = _commit()
    Draft202012Validator(_schema("learning-library")).validate(catalog)
    _json(catalog_path, catalog)
    return catalog_path


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument("--media-root",type=Path)
    args=parser.parse_args()
    print(build(args.output,args.media_root))


if __name__ == "__main__":
    main()
