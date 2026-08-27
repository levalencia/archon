# Archon Course

The canonical learning home for Archon. This course teaches the system from agent fundamentals to an evidence-backed capstone while keeping one canonical page per concept. Modules sequence the learning; future audience tracks will link back to the same modules and concepts rather than copy explanations.

Archon is a local Agent Reliability Workbench, not a publicly deployed production service. For current implementation facts, use the [canonical evidence matrix](../IMPLEMENTATION-EVIDENCE.md); for system views, use the existing [architecture diagrams](../ARCHITECTURE-DIAGRAMS.md). This course does not replace either source.

> **Luis study note (optional):** Read the interview route before a screening, then use module self-checks to find gaps. The English pages remain canonical; add only short personal callouts like this one.

## Who this is for

- **Learn from zero:** coworkers who know basic programming but are new to agents.
- **Interview study:** Luis or any engineer preparing concise architecture and trade-off explanations.
- **Technical reference:** contributors tracing a concept to exact code, tests, and runtime evidence.

Start with the [syllabus](syllabus.md) for prerequisites, outcomes, pacing, and capstone artifacts. Use the [concept map](concept-map.md) when a module assumes unfamiliar vocabulary.

## Information architecture

```mermaid
flowchart TD
    Home[Course home] --> Syllabus[Syllabus and pacing]
    Home --> Map[Concept map and dependencies]
    Home --> Modules[Modules 00–15]
    Home --> Tracks[Audience routes]
    Home --> Reference[Reference]

    Modules --> Concepts[Canonical concept pages]
    Tracks --> Modules
    Tracks --> Concepts
    Concepts --> Walkthroughs[Code walkthroughs]
    Modules --> Walkthroughs

    Concepts --> Catalog[Concept catalog]
    Walkthroughs --> Source[Source symbols and tests]
    Catalog --> Source
    Source --> Evidence[Canonical evidence and runtime artifacts]

    Modules --> Workshops[Exercises and workshops]
    Workshops --> Capstone[Capstone artifacts]
```

The `modules`, `concepts`, `code-walkthroughs`, `tracks`, `reference`, and `workshops` areas are added in later plan tasks. Planned links below are intentionally labeled so they are not mistaken for missing current documentation.

## Learning routes

| Route | Use it when | Path |
|---|---|---|
| Zero-to-capstone | You are new to agent systems | Read the [syllabus](syllabus.md), then modules 00–15 in order. |
| Interview preparation | You need a defensible short or deep explanation | Modules 00–03 → 05 → 07–11 → 13–15; use each module's interview answer and evidence links. Future index: `tracks/interview.md` (**planned**). |
| Coworker workshop | You need a shared vocabulary and hands-on reliability exercise | Modules 00 → 03–05 → 07 → 09–10, then one capstone scenario. Future index: `tracks/workshops.md` (**planned**). |
| Technical reference | You already know the system and need implementation detail | Start at the [concept map](concept-map.md), then follow future concept catalog, code walkthrough, source, test, and evidence links. Future index: `tracks/operations.md` (**planned**). |

All current routes reach every module directly from this page; future track indexes are navigation views, not alternate concept sources.

## Modules

| # | Module | Primary artifact | Availability |
|---:|---|---|---|
| 00 | [Agent anatomy](modules/00-agent-anatomy/README.md) | Lifecycle map | **Planned** |
| 01 | [Python architecture: OOP, Protocols, DI, async](modules/01-python-architecture/README.md) | Dependency diagram | **Planned** |
| 02 | [Typed runtime and state machine](modules/02-typed-runtime/README.md) | Minimal runtime trace | **Planned** |
| 03 | [ReAct loop, budgets, and stop reasons](modules/03-react-loop/README.md) | Bounded-loop exercise | **Planned** |
| 04 | [Tool contracts and schemas](modules/04-tools-and-schemas/README.md) | Registered typed tool | **Planned** |
| 05 | [Policy and durable approvals](modules/05-policy-and-approvals/README.md) | Deny/ask/allow probe | **Planned** |
| 06 | [Context, conversation, and encrypted memory](modules/06-context-and-memory/README.md) | Context-boundary note | **Planned** |
| 07 | [Durable Run Ledger, replay, fork, and compare](modules/07-run-ledger/README.md) | Event timeline | **Planned** |
| 08 | [Documents, embeddings, RAG, grounding, and faithfulness](modules/08-rag-grounding/README.md) | Cited grounded answer | **Planned** |
| 09 | [Evaluation harness and regression](modules/09-evaluation-harness/README.md) | Recorded-run evaluation | **Planned** |
| 10 | [Reliability and resilience](modules/10-resilience/README.md) | Failure drill | **Planned** |
| 11 | [Bounded verifier delegation](modules/11-bounded-delegation/README.md) | Parent-child evidence graph | **Planned** |
| 12 | [Governed MCP](modules/12-governed-mcp/README.md) | Discovered and approved tool call | **Planned** |
| 13 | [Auth, UI, SSE, logs, metrics, and traces](modules/13-auth-ui-observability/README.md) | Observable request walkthrough | **Planned** |
| 14 | [Docker, CI, migrations, and recovery](modules/14-local-operations/README.md) | Recovery report | **Planned** |
| 15 | [Capstone demo and interviews](modules/15-capstone/README.md) | 2/15/45-minute walkthroughs | **Planned** |

## Canonical-source rule

1. A concept has one canonical explanation under the future `concepts/` directory.
2. Modules teach a sequence and link to concepts; tracks curate modules and never fork their explanations.
3. Code walkthroughs explain source flow and link back to concepts.
4. Implementation claims defer to the [evidence matrix](../IMPLEMENTATION-EVIDENCE.md), rather than restating mutable test counts or deployment results.
5. Historical plans and audits are context, not the current learning or status source.

## Status vocabulary

### Course-content status

| Status | Meaning |
|---|---|
| **planned** | Named in the approved information architecture, but its canonical page is not yet available. |
| **draft** | Page exists and is usable for review, but links, exercises, or technical claims may still be incomplete. |
| **reviewed** | Required sections, links, terminology, and evidence references have been checked at the stated revision. |
| **current** | Reviewed and aligned with the current accepted evidence baseline. This does not mean production-ready. |

These labels describe documentation maturity only. They never imply that a runtime capability exists.

### Concept implementation status

Every concept catalog entry uses exactly one of these:

- **`implemented`** — meaningful behavior is wired into a current path and has source, tests, and evidence.
- **`partial`** — useful behavior exists, but wiring, coverage, evidence, safety, scale, UX, or provider support is incomplete.
- **`not-implemented`** — no meaningful current implementation exists; an interface, stub, historical experiment, or discussion is insufficient.
- **`deferred`** — deliberately outside the current scope; do not infer a delivery date.

Status is concept-specific and must include its boundary. In particular, ReAct, deterministic claim verification, bounded verifier delegation, post-run evaluation, and generic self-reflection are different concepts. Generic self-reflection is not implemented merely because tool errors return to the model.

## Authoring

Use the [module template](templates/module-template.md) and [concept template](templates/concept-template.md). Catalog fragment conventions are documented in [catalog-fragments/README.md](catalog-fragments/README.md).
