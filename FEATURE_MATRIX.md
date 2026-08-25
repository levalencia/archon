# Archon Feature Matrix — Archived

> **Superseded on 2026-08-25.** This file is retained as a historical pointer only. It is not a current feature-completion or competitor-parity scorecard.

The sole canonical status matrix is [Implementation Evidence](docs/IMPLEMENTATION-EVIDENCE.md). It evaluates Archon using six independent dimensions: **Exists**, **Wired**, **Tested**, **Observed**, **UI**, and **Deployed**.

## Why the prior matrix was retired

The previous table was not a defensible status source:

- its headline claimed `37/37`, while the competitor table contained 38 rows;
- it treated classes, routes, mocks, stubs, configuration flags, manifests, and unit tests as completed product capabilities;
- it marked capabilities as wired even when they were absent from the default/live path;
- it did not distinguish direct runtime observation, UI evidence, or deployment;
- it collapsed unequal products into a binary parity score;
- its course totals (`26/30` and `29/33`) overstated implementation depth.

The fresh audit found a mixed portfolio:

- **Strong:** typed budgeted runtime, native Anthropic/Foundry tools, live SSE events, authenticated conversations, tool contracts, and broad backend tests.
- **Partial:** provider portability, context/memory, permissions, web evidence, RAG, observability, cost reporting, and product UX.
- **Scaffolded or unsafe:** host execution called a sandbox, MCP routes, background tasks, sequential multi-agent orchestration, encrypted-memory claims, and mock evaluation/A-B flows.
- **Missing or unverified:** durable run replay/fork/compare, real isolation, real pgvector deployment, secure owner-scoped memory, a verified cloud environment, and green remote CI for the audited work.

## Historical course framing

The course mapping still has educational value, but it is not a completion score. The detailed reclassification in [Feature and Course Concept Audit v2](docs/FEATURE-AND-COURSE-AUDIT-V2.md) found:

- 3 of 30 days with strong live implementation;
- 16 meaningful but partial live implementations;
- 10 scaffold/demo/isolated concepts;
- 1 missing/deferred concept.

That audit also preserves the detailed competitor and curriculum comparison without presenting it as parity.

## Current evidence

Use these documents in order:

1. [Implementation Evidence](docs/IMPLEMENTATION-EVIDENCE.md) — canonical current status and gate evidence.
2. [Archon GPT-5.6 Re-Audit](docs/ARCHON-GPT56-REAUDIT-2026-08-25.md) — security, architecture, frontend, CI, and deployment findings.
3. [Feature and Course Concept Audit v2](docs/FEATURE-AND-COURSE-AUDIT-V2.md) — detailed competitor/course analysis.

Do not revive a single completion percentage or parity count without proving all six evidence dimensions at a named revision.
