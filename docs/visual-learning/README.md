# Visual Learning Studio

The Visual Learning Studio is a derived learning interface for Archon's canonical course and evidence system. It does not replace Markdown, the capability catalog, source code, tests, or implementation evidence.

## Open it

With the managed application running, authenticate and visit:

```text
/learn/map
```

Use the **Learn** destination in desktop or mobile navigation.

## What the MVP provides

- D3 force-directed exploration of all 66 catalog concepts;
- module, status, and text filtering;
- explicit `implemented`, `partial`, and `deferred` states;
- concept/module explanations sourced from canonical course pages;
- direct links to source code, tests, evidence, and limitations;
- four guided journeys: lifecycle, governed tools, memory/RAG, and observability;
- local-only explored-node progress;
- keyboard-selectable graph nodes and responsive desktop/mobile layouts.

## One-source pipeline

```mermaid
flowchart LR
  C[concept-catalog.yaml] --> G[build-visual-learning.py]
  M[module and concept Markdown] --> G
  R[map-curation.yaml relations and tours] --> G
  G --> J[archon-graph.json]
  J --> S[Svelte VisualLearningMap]
  S --> U[/learn/map]
```

Canonical inputs:

- `docs/course/concept-catalog.yaml` — generated concept status/path contracts;
- `docs/course/concepts/*.md` — concept-level beginner explanations and mental models;
- `docs/course/modules/*/README.md` — module fallback text;
- `docs/visual-learning/map-curation.yaml` — visual-only cross-links and guided-journey ordering.

Generated output:

- `frontend/static/learning/archon-graph.json`.

## Regenerate and verify

```bash
backend/.venv/bin/python scripts/build-visual-learning.py
backend/.venv/bin/python scripts/build-visual-learning.py --check
backend/.venv/bin/pytest -q backend/tests/unit/test_visual_learning_graph.py
cd frontend
npm run check
npx vitest run
npx playwright test tests/visual-learning.spec.ts
```

The generator fails when concept IDs repeat, referenced files are missing, statuses drift, tours contain unknown IDs, or the visual graph becomes disconnected. The test fails when the committed JSON differs from regenerated output.

## Honesty boundaries

- A visual node does not upgrade capability status.
- Deferred concepts may intentionally have no source or test link.
- Some concepts do not yet have an individual page; those nodes explicitly link to their module fallback.
- `localStorage` records only that a node was opened on the current browser. It is not course completion evidence.
- GitHub links target public `main`; local unmerged edits are not represented there.

## Planned extensions

The shared graph can later power guided animated sequences, an evidence heatmap, Reveal.js presentations, audio transcripts/TTS, and quizzes. Those are not part of this MVP until separately implemented and tested.
