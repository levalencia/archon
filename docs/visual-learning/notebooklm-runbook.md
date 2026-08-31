# NotebookLM Runbook for Archon

NotebookLM is the generation lane for Visual Learning Studio media. It does not become Archon's source of truth.

## Prerequisites

- A Google account with NotebookLM access.
- The canonical Archon repository checked out on `main` with a clean working tree.
- No secrets, `.env` files, profile memories, Tolaria private notes, backups, tokens, cookies, or paid-course raw material in any source pack.

## 1. Generate the packs

From the canonical repository:

```bash
cd /Users/luisvalencia/Documents/archon
backend/.venv/bin/python scripts/build-notebooklm-source-packs.py
```

Output:

```text
/Users/luisvalencia/Documents/archon-notebooklm/source-packs/
├── manifest.json
├── system-overview/
├── request-lifecycle/
├── memory-rag-evaluation/
├── reliability-operations/
└── interview-demo/
```

Each notebook folder contains:

- `00-ARCHON-TRUTH-BOUNDARIES.md`;
- numbered public source files;
- `UPLOAD-README.md` for humans only.

`manifest.json` records the exact Git commit, canonical source path, output filename, and SHA-256 for every uploaded source.

## 2. Create one notebook

Start with the pilot:

```text
Archon — Request Lifecycle and Governed Tools
```

In NotebookLM:

1. Select **Create notebook**.
2. Use the exact title above.
3. Open `archon-notebooklm/source-packs/request-lifecycle/`.
4. Upload `00-ARCHON-TRUTH-BOUNDARIES.md` first.
5. Upload every numbered source file.
6. Do not upload `UPLOAD-README.md` or `manifest.json` as sources.
7. Wait until every source finishes processing.

## 3. Validate the notebook before generating

Ask in NotebookLM chat:

```text
Using only the uploaded sources, list:
1. the authoritative implementation-evidence source;
2. the machine-readable capability-acceptance source;
3. the authoritative deferred-gap source;
4. the difference between mock and live inference;
5. the difference between health and readiness;
6. five claims that these sources do not support.
Cite every answer.
```

Stop if NotebookLM cannot answer these boundaries correctly.

## 4. Generate artifacts

Open **Studio** and generate one artifact at a time. Use the matching section in [`notebooklm-promptbook.md`](notebooklm-promptbook.md).

Pilot order:

1. Audio Overview — deep dive, long.
2. Video Overview — explainer, whiteboard.
3. Slide Deck — presenter format.
4. Infographic — landscape, detailed.
5. Mind Map.
6. Flashcards — hard, more.
7. Quiz — hard, more.
8. Study Guide / Report — detailed custom report.

Generate only one version of each before reviewing. Multiple variants make comparison harder.

## 5. Download and store artifacts

Use this external directory:

```text
/Users/luisvalencia/Documents/archon-notebooklm/artifacts/
├── audio/
├── video/
├── slides/
├── infographics/
├── mind-maps/
├── flashcards/
├── quizzes/
└── reports/
```

Large generated media does not belong in the Git repository. Copy [`notebooklm-artifact-review-template.json`](notebooklm-artifact-review-template.json) beside each downloaded artifact and complete:

```json
{
  "source_commit": "<40-character git commit>",
  "notebook_id": "request-lifecycle",
  "artifact_type": "audio",
  "promptbook_section": "Audio Overview — system deep dive",
  "selected_sources": [],
  "generated_at": "<UTC timestamp>",
  "review": {
    "comprehension": 0,
    "structure": 0,
    "relationships": 0,
    "accuracy": 0,
    "boundaries": 0,
    "interview_value": 0,
    "accepted": false
  }
}
```

## 6. Review before reuse

Reject any artifact that:

- calls Archon publicly deployed or production-ready;
- presents mock output as live inference;
- claims provider-live embeddings;
- claims native JSON Schema parity;
- claims Jaeger or Azure Monitor trace storage;
- treats similarity as factual grounding;
- treats approval-gated candidates as autonomous production optimization;
- cannot cite the evidence behind a claim.

Accept an artifact only after Luis rates comprehension, structure, relationships, accuracy, boundaries, and interview value.

## 7. Repeat with focused notebooks

Recommended order:

1. Request Lifecycle and Governed Tools
2. System Overview
3. Memory, RAG, and Evaluation
4. Reliability, Security, and Operations
5. Interview and Demo Preparation

Do not merge all five packs into one notebook. Focused source sets produce clearer artifacts.

## Optional automation

The unofficial `notebooklm-py` CLI can create notebooks, upload sources, generate artifacts, and download outputs. It requires interactive Google login and stores browser authentication state under `~/.notebooklm/`.

Do not install, log in, copy authentication state, or automate uploads without Luis's explicit authorization. The official NotebookLM UI is the default pilot path.
