#!/usr/bin/env python3
# ruff: noqa: E501  # Embedded HyperFrames HTML/CSS remains readable.
"""Generate maintainable HyperFrames projects for the source-authored learning packs."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "docs/visual-learning/packs"
MEDIA_ROOT = ROOT.parent / "archon-learning-media"
PROJECT_ROOT = ROOT / "spikes/learning-media-videos"
PACK_IDS = (
    "system-overview",
    "memory-rag-evaluation",
    "reliability-operations",
    "interview-demo",
    "hybrid-agent-orchestration",
)
DURATION = 112
SCENE_DURATION = 16

DESIGN = """# Archon Evidence Dark — {title}

## Style Prompt
Technical, evidence-first, calm, and precise. A dark observability-console composition with one focal idea per scene, connected cards, explicit evidence boundaries, and no decorative AI imagery.

## Colors
- Canvas: `#050b16`
- Panel: `#0f172a`
- Raised panel: `#111c2e`
- Text: `#f8fafc`; muted: `#94a3b8`
- Archon identity, selection, and active-path glow: `#f59e0b`
- Success / ALLOW: `#22c55e`
- Failure / DENY: `#fb7185`
- Runtime / information: `#3b82f6`
- Evidence / evaluation: `#a78bfa`

## Typography
System sans-serif for teaching copy; system monospace for state and evidence labels.

## Motion
Measured, directional, deterministic entrances. One orange focal glow per scene. No infinite loops, random values, wall-clock logic, or jump cuts.

## What NOT to Do
- Do not turn every semantic state orange.
- Do not use generic purple gradients, stock AI imagery, unlabeled arrows, or tiny body copy.
- Do not imply public deployment, universal provider behavior, production SLOs, or educational acceptance.
"""

PACKAGE = """{
  "name": "archon-learning-pack-video",
  "private": true,
  "type": "module",
  "scripts": {
    "check": "npx --yes hyperframes@0.8.27 check --snapshots",
    "render": "npx --yes hyperframes@0.8.27 render"
  }
}
"""

HYPERFRAMES = """{
  "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
  "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
  "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
  "media": {"autoProxy": true}
}
"""


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def _composition(spec: dict[str, Any], video_script: dict[str, Any], audio_duration: float) -> str:
    scenes = []
    palette = ["blue", "orange", "green", "purple", "blue", "orange", "purple"]
    for index, segment in enumerate(video_script["segments"]):
        start = index * SCENE_DURATION
        related = spec["concepts"][max(0, (index - 1) * 2):max(0, (index - 1) * 2) + 2]
        cards = "".join(
            f'<div class="card {html.escape(palette[index])}"><span>{html.escape(item["label"])}</span><p>{html.escape(item["summary"])}</p></div>'
            for item in related
        )
        if not cards:
            cards = '<div class="evidence-line"><span>CODE</span><b>→</b><span>TESTS</span><b>→</b><span>OBSERVATION</span><b>→</b><span>QUALIFIED CLAIM</span></div>'
        scenes.append(f'''<section id="scene-{index + 1}" class="clip scene" data-start="{start}" data-duration="{SCENE_DURATION}" data-track-index="1"><p class="kicker">ARCHON · EVIDENCE PATH</p><h1>{html.escape(segment["chapter"])}</h1><p class="narration">{html.escape(segment["text"])}</p><div class="cards">{cards}</div><div class="source">REVIEW-READY · SOURCE-PINNED · HUMAN ACCEPTANCE PENDING</div></section>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(spec["title"])}</title><script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script><style>
:root{{--bg:#050b16;--panel:#0f172a;--raised:#111c2e;--text:#f8fafc;--muted:#94a3b8;--orange:#f59e0b;--green:#22c55e;--coral:#fb7185;--blue:#3b82f6;--purple:#a78bfa;--border:#334155}}*{{box-sizing:border-box}}html,body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:var(--bg);color:var(--text);font-family:Arial,system-ui,sans-serif}}.root{{position:relative;width:1920px;height:1080px;background:radial-gradient(circle at 78% 10%,rgba(245,158,11,.11),transparent 32%),linear-gradient(rgba(51,65,85,.22) 1px,transparent 1px),linear-gradient(90deg,rgba(51,65,85,.22) 1px,transparent 1px),var(--bg);background-size:auto,48px 48px,48px 48px}}.scene{{position:absolute;inset:0;padding:82px 120px 76px;display:flex;flex-direction:column;justify-content:center;opacity:0}}.kicker{{margin:0;color:var(--orange);font:700 22px ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase}}h1{{margin:24px 0 20px;max-width:1500px;font-size:76px;line-height:1.02}}.narration{{max-width:1460px;margin:0;color:#cbd5e1;font-size:31px;line-height:1.38}}.cards{{display:flex;gap:34px;align-items:stretch;margin-top:48px}}.card{{flex:1;min-height:230px;padding:30px;border:3px solid var(--blue);border-radius:20px;background:rgba(15,23,42,.96)}}.card span{{font:800 28px ui-monospace,monospace;color:var(--text)}}.card p{{font-size:25px;line-height:1.35;color:#cbd5e1}}.card.orange{{border-color:var(--orange);box-shadow:0 0 0 1px rgba(245,158,11,.42),0 0 28px rgba(245,158,11,.25)}}.card.green{{border-color:var(--green)}}.card.purple{{border-color:var(--purple)}}.card.blue{{border-color:var(--blue)}}.evidence-line{{display:flex;align-items:center;justify-content:center;gap:24px;width:100%;padding:44px;border:3px solid var(--orange);border-radius:20px;background:rgba(15,23,42,.96);box-shadow:0 0 30px rgba(245,158,11,.25);font:800 24px ui-monospace,monospace}}.evidence-line b{{color:var(--orange);font-size:42px}}.source{{position:absolute;left:120px;bottom:34px;color:var(--muted);font:18px ui-monospace,monospace;letter-spacing:.08em}}</style></head><body><div class="root" data-composition-id="{html.escape(spec['pack_id'])}" data-width="1920" data-height="1080" data-start="0" data-duration="{DURATION}">{''.join(scenes)}<audio id="narration" src="assets/narration.mp3" data-start="0" data-duration="{audio_duration:.3f}" data-track-index="2"></audio></div><script>const tl=gsap.timeline({{paused:true}});const scenes=[...document.querySelectorAll('.scene')];scenes.forEach((scene,index)=>{{const start=index*{SCENE_DURATION};tl.set(scene,{{autoAlpha:0}},0);tl.fromTo(scene,{{autoAlpha:0,x:80}},{{autoAlpha:1,x:0,duration:1,ease:'power2.out'}},start);if(index<scenes.length-1)tl.to(scene,{{autoAlpha:0,duration:.8,ease:'power2.in'}},start+{SCENE_DURATION - 0.8});}});window.__timelines['{html.escape(spec['pack_id'])}']=tl;</script></body></html>'''


def build(media_root: Path = MEDIA_ROOT, project_root: Path = PROJECT_ROOT) -> None:
    for pack_id in PACK_IDS:
        spec = json.loads((PACK_DIR / f"{pack_id}.json").read_text())
        video_script_path = media_root / "published" / pack_id / f"{pack_id}-video" / "video-script.json"
        video_script = json.loads(video_script_path.read_text())
        source_audio = media_root / "generated-video-audio" / pack_id / f"{pack_id}.mp3"
        if not source_audio.is_file():
            raise ValueError(f"missing generated narration: {source_audio}")
        project = project_root / pack_id
        (project / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_audio, project / "assets" / "narration.mp3")
        (project / "DESIGN.md").write_text(DESIGN.format(title=spec["title"]), encoding="utf-8")
        (project / "SCRIPT.md").write_text("# Video narration\n\n" + "\n\n".join(item["text"] for item in video_script["segments"]) + "\n", encoding="utf-8")
        rows = ["# Storyboard", "", "| Time | Scene |", "|---|---|"]
        for index, segment in enumerate(video_script["segments"]):
            rows.append(f"| {index * SCENE_DURATION}–{(index + 1) * SCENE_DURATION}s | {segment['chapter']} |")
        (project / "STORYBOARD.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
        (project / "package.json").write_text(PACKAGE, encoding="utf-8")
        (project / "hyperframes.json").write_text(HYPERFRAMES, encoding="utf-8")
        (project / "index.html").write_text(_composition(spec, video_script, _probe_duration(source_audio)), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-root", type=Path, default=MEDIA_ROOT)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    build(args.media_root, args.project_root)


if __name__ == "__main__":
    main()
