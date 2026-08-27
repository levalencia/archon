# Archon Course Syllabus

## Course purpose

Build enough shared vocabulary and implementation understanding to explain, inspect, exercise, and defend Archon's reliability architecture. The course serves three uses without duplicating content: beginner onboarding, Luis's interview study, and contributor reference.

Use the [course home](README.md) for module navigation and the [concept map](concept-map.md) for dependencies. Current capability status remains in the [implementation evidence matrix](../IMPLEMENTATION-EVIDENCE.md).

## Prerequisites

Required:

- basic Python: functions, classes, imports, exceptions, and type hints;
- basic HTTP and JSON: request, response, status code, and JSON object;
- basic command-line and Git use;
- ability to read a small automated test.

Helpful but taught or refreshed in the course:

- `async`/`await`, Protocols, dependency injection, state machines, and JSON Schema;
- model tool calling, ReAct, embeddings, retrieval, and evaluation;
- Docker Compose, relational databases, SSE, metrics, and traces.

Environment for executable labs:

- Python 3.11 and `uv`;
- Docker Desktop for local deployment and recovery exercises;
- Node.js 22+ for frontend checks.

A learner may complete reading and diagram exercises without running the full stack. Every practical task must state its narrower prerequisites and done criteria.

## Learning outcomes

By the end, a learner can:

1. trace an agent request from API input through runtime, policy, tools, evidence, and terminal stop reason;
2. explain OOP, Protocols, dependency injection, async execution, typed state, and explicit boundaries in this codebase;
3. distinguish a ReAct control loop from generic self-reflection, deterministic verification, verifier delegation, and post-run evaluation;
4. register and reason about a typed tool contract, schema, risk metadata, policy decision, and exact-bound approval;
5. explain context, conversation state, encrypted memory, ownership, and persistence boundaries;
6. inspect durable run events and correctly describe replay, fork, compare, and their limitations;
7. distinguish documents, chunks, embeddings, retrieval, grounding, faithfulness, and citations, including Archon's SQL JSON cosine boundary;
8. evaluate a recorded run and interpret regression evidence without turning fixtures into model-quality claims;
9. reason about retries, idempotency, timeouts, cancellation, circuit breakers, fallback, and rate limits;
10. explain why the verifier is one bounded evidence-only child rather than a swarm or general reflection loop;
11. trace governed MCP discovery and execution through existing policy and approval controls;
12. follow an observable request across auth, API, SSE, logs, metrics, traces, UI, and owner scope;
13. explain the verified local Docker target, migrations, CI evidence, backup/restore, and unverified production gaps;
14. deliver defensible 2-, 15-, and 45-minute capstone walkthroughs with source, test, runtime evidence, and limitations.

## Sequence and estimated pacing

The default pace is **32–48 focused hours**. Estimates are guidance, not evidence of mastery.

| Phase | Modules | Focus | Estimate |
|---|---|---|---:|
| Foundations | 00–02 | Agent vocabulary, Python architecture, typed runtime/state | 5–7 h |
| Controlled action | 03–05 | ReAct, budgets, tools, policy, approvals | 6–9 h |
| Durable knowledge | 06–08 | Context/memory, Run Ledger, grounded RAG | 7–10 h |
| Measurement and resilience | 09–10 | Recorded-run evaluation and failure handling | 4–6 h |
| Advanced boundaries | 11–13 | Bounded verifier, MCP, auth/UI/observability | 5–8 h |
| Operations and capstone | 14–15 | Local operations, recovery, demo, interviews | 5–8 h |

Suggested formats:

- **Self-study:** two modules per week for eight weeks, with one artifact per module.
- **Coworker workshop:** four half-days: foundations; controlled action; evidence/evaluation; operations/capstone.
- **Interview refresh:** modules 00–03, 05, 07–11, and 13–15; answer self-checks aloud and verify every implementation claim.

## Module completion contract

A module is complete only when the learner can:

- define its prerequisite vocabulary in plain English;
- redraw or explain its architecture and request flow;
- locate the named source symbols and tests;
- run the command or complete the bounded exercise and evaluate its done criteria;
- identify at least one security or failure mode and its evidence path;
- state the lab-vs-production boundary;
- give the module's interview answer without overstating implementation status.

## Capstone artifacts

Produce these artifacts by the end of module 15:

1. **Lifecycle map:** input → context → model → policy → approval/tool → evidence → stop reason.
2. **Dependency and state diagrams:** key Protocol/implementation relationships and runtime transitions.
3. **Typed tool and policy probe:** a bounded tool contract plus deny/ask/allow observations.
4. **Context-boundary note:** what is request-local, conversation-persistent, memory-persistent, encrypted, and owner/project scoped.
5. **Run evidence timeline:** ordered events with replay/fork/compare limits.
6. **Grounded answer:** cited claims and an explanation of retrieval, verification, faithfulness, and unsupported-claim behavior.
7. **Recorded-run evaluation:** dataset/version, result, limitations, and a defensible regression conclusion.
8. **Failure drill:** one controlled retry/timeout/breaker/fallback/rate-limit scenario with observations.
9. **Parent-child evidence graph:** verifier inputs, outputs, budgets, lineage, and fail-closed path.
10. **Observable request walkthrough:** auth, SSE/API, logs, metrics/trace, persistence, and UI evidence.
11. **Recovery report:** local deployment boundary, migration state, backup/restore result, RTO/RPO observation, and caveats.
12. **Interview package:** 2-minute overview, 15-minute architecture walkthrough, and 45-minute deep dive with questions.

Artifacts may link to repository evidence; do not copy mutable evidence tables into course pages.

## Assessment

Use each module's exercise, done criteria, self-check, and interview answer. For workshops, assess each artifact on:

- technical correctness;
- traceability to source, tests, and runtime evidence;
- explicit security and failure boundaries;
- implementation-status accuracy;
- clarity for a beginner;
- no-hype communication.

A polished diagram without traceable evidence is incomplete. A passing test without an explanation of scope is also incomplete.

## No-hype evidence policy

Apply this policy exactly to every module, concept, exercise, and interview answer:

1. **Record the revision, environment, and command** for observed behavior.
2. **Keep evidence dimensions independent:** code existence, live wiring, automated tests, direct observation, UI exposure, and non-local deployment are separate claims.
3. **Use only the four concept statuses** `implemented`, `partial`, `not-implemented`, and `deferred`, and state the limiting boundary.
4. **Link claims to exact source symbols, behavior-focused tests, and the canonical evidence path.** A route, class, manifest, mock, fixture, or passing import alone does not prove a live capability.
5. **Label mocks, scripted adapters, fixtures, deterministic data, local smokes, and historical artifacts.** Never present them as external-provider, model-quality, load, SLO, or public-production evidence.
6. **Never translate local Docker evidence into deployment.** Archon's verified target is production-like local Docker Compose; public/cloud deployment remains unverified and deferred.
7. **Do not claim pgvector.** Current retrieval uses PostgreSQL JSON embeddings with cosine computed in Python (`sql-json-cosine`), not an indexed vector service.
8. **Do not claim generic self-reflection.** ReAct tool-result feedback, deterministic claim verification, one bounded verifier child, and post-run evaluation are distinct mechanisms.
9. **Do not claim a dynamic multi-agent swarm.** The evidence-backed capability is one constrained verifier specialist with explicit context, tools, budgets, and lineage.
10. **Do not claim provider parity, production readiness, remote CI state, test counts, or benchmark results without direct current evidence.** Refer to the [canonical evidence matrix](../IMPLEMENTATION-EVIDENCE.md) for mutable facts.
11. **State lab-vs-production limits next to the claim, not in fine print.** Include security assumptions, trusted boundaries, untested scale, and absent operational proof.
12. **Prefer “the evidence demonstrates…” over “the system guarantees…”.** If evidence is missing or stale, downgrade the status or say “not verified.”

## Canonical references

- [Course home and routes](README.md)
- [Concept and module dependency map](concept-map.md)
- [Current implementation evidence](../IMPLEMENTATION-EVIDENCE.md)
- [Current architecture diagrams](../ARCHITECTURE-DIAGRAMS.md)
- [Historical feature/course audit](../FEATURE-AND-COURSE-AUDIT-V2.md) — useful context, not current status
- [Capstone documentation implementation plan](../plans/2026-08-27-capstone-course-documentation.md)
