# Archon Capstone Course Documentation Implementation Plan

> **For Hermes:** Use subagent-driven-development to implement this plan task-by-task. No push without Luis's explicit approval.

**Goal:** Transform Archon's existing portfolio/operations documentation into one canonical Markdown knowledge system that supports zero-to-capstone learning, company workshops, interview preparation, and technical reference without duplicating concept explanations.

**Architecture:** Use one source of truth per concept and multiple audience tracks that link to canonical concept/module pages. Every implemented claim maps to source symbols, tests, runtime evidence, diagrams, limitations, an interview explanation, and a practical exercise. Historical planning/audit documents remain clearly separated from current learning navigation.

**Tech stack:** Markdown, Mermaid, YAML concept catalog, Python 3.11 documentation validator, Git/GitHub links, existing pytest/CI.

---

## Non-negotiable content contract

Every module must include:

1. beginner explanation and prerequisite vocabulary;
2. problem and mental model;
3. architecture/component diagram;
4. startup sequence and per-request sequence;
5. exact source symbols and tests to inspect;
6. executable commands or a bounded exercise;
7. security and failure modes;
8. observability/evidence path;
9. lab-vs-production limitations;
10. interview explanation and self-check questions.

Concept status must be one of `implemented`, `partial`, `not-implemented`, or `deferred`. Generic self-reflection must not be claimed as implemented; distinguish ReAct, deterministic claim verification, verifier delegation, and post-run evaluation.

## Target information architecture

- `docs/course/README.md` — canonical documentation home
- `docs/course/syllabus.md` — prerequisites, outcomes, schedule, artifacts
- `docs/course/concept-map.md` — curriculum and dependencies
- `docs/course/concept-catalog.yaml` — machine-readable concept→code→test→evidence registry
- `docs/course/templates/` — module and concept contracts
- `docs/course/modules/00-15/` — ordered zero-to-capstone modules
- `docs/course/concepts/` — canonical reusable explanations
- `docs/course/code-walkthroughs/` — interview-ready source tours
- `docs/course/tracks/` — learn, interview, workshops, operations
- `docs/course/reference/` — glossary, events, stop reasons, schemas, test map
- `docs/course/workshops/` — instructor/student guides, exercises, rubric
- `scripts/validate-course-docs.py` — links, required sections, catalog paths/statuses, code/test references
- `backend/tests/unit/test_course_documentation.py` — validator contract

## Module sequence

| Module | Topic | Primary artifact |
|---:|---|---|
| 00 | Agent anatomy | lifecycle map |
| 01 | Python architecture, OOP, Protocols, DI, async | dependency diagram |
| 02 | Typed runtime and state machine | minimal runtime trace |
| 03 | ReAct loop, budgets, stop reasons | bounded loop exercise |
| 04 | Tool contracts and schemas | registered typed tool |
| 05 | Policy and durable approvals | deny/ask/allow probe |
| 06 | Context, conversation, encrypted memory | context boundary note |
| 07 | Durable Run Ledger, replay, fork, compare | event timeline |
| 08 | Documents, embeddings, RAG, grounding, faithfulness | cited grounded answer |
| 09 | Evaluation harness and regression | recorded-run eval |
| 10 | Reliability: idempotency, retry, timeout, breaker, fallback, rate limit | failure drill |
| 11 | Bounded verifier delegation | parent-child evidence graph |
| 12 | Governed MCP | discovered/approved tool call |
| 13 | Auth, UI, SSE, logs, metrics, traces | observable request walkthrough |
| 14 | Docker, CI, migrations, backup/restore | recovery report |
| 15 | Capstone demo and interviews | 2/15/45-minute walkthrough |

## Task 1: Create navigation, templates and catalog schema

**Files:**
- Create `docs/course/README.md`
- Create `docs/course/syllabus.md`
- Create `docs/course/concept-map.md`
- Create `docs/course/templates/module-template.md`
- Create `docs/course/templates/concept-template.md`
- Create `docs/course/catalog-fragments/README.md`

**Acceptance:** audience tracks and all modules are reachable within three links; templates include every non-negotiable section; terminology policy is explicit.

## Task 2: Foundations and trust modules

**Files:**
- Create modules `00-agent-anatomy` through `05-policy-and-approvals`
- Create matching concept pages for agent, runtime, ReAct, state machine, Protocols/DI/OOP/async, tools, JSON Schema, policy, approvals and idempotency
- Create walkthroughs for runtime, tool registry, policy and approval
- Create `catalog-fragments/00-foundations.yaml`

**Acceptance:** every code symbol and test path exists; ReAct and self-reflection are distinguished; exercises have commands and done criteria.

## Task 3: State, knowledge, evaluation and resilience modules

**Files:**
- Create modules `06-context-and-memory` through `10-resilience`
- Create concept pages for context, memory, encryption, Run Ledger, RAG, embeddings, retrieval, groundedness, faithfulness, citations, evaluation, retries, timeouts, cancellation, circuit breaker, fallback and rate limiting
- Create walkthroughs for memory, Run Ledger, grounded RAG and evaluation harness
- Create `catalog-fragments/01-knowledge.yaml`

**Acceptance:** RAG terms are compared precisely; SQL JSON cosine is distinguished from pgvector; tests/evidence and production gaps are explicit.

## Task 4: Advanced integration, operations and capstone modules

**Files:**
- Create modules `11-bounded-delegation` through `15-capstone`
- Create concept pages for delegation, MCP, authentication/authorization, SSE, logging, metrics, tracing, health/readiness, Docker, migrations, DR and CI
- Create walkthroughs for verifier child, MCP runtime, observability and local deployment
- Create all four track indexes, workshop guides and reference pages
- Create `catalog-fragments/02-advanced.yaml`

**Acceptance:** company workshops and interview routes reuse canonical concept pages; public deployment remains deferred; demo claims match evidence.

## Task 5: Compose catalog and add documentation CI

**Files:**
- Generate `docs/course/concept-catalog.yaml` from reviewed fragments
- Create `scripts/validate-course-docs.py`
- Create `backend/tests/unit/test_course_documentation.py`
- Add validator to `.github/workflows/ci.yml`
- Link course home from `README.md`

**Validator contracts:**
- every module contains required headings;
- every catalog status is allowed;
- referenced source/test/evidence paths exist;
- every implemented concept has at least one source and test;
- Markdown internal links resolve;
- Mermaid fences balance;
- no concept claims `implemented` without evidence;
- no secret/runtime artifact is referenced as course content.

## Task 6: Final curriculum and architecture review

Review dimensions:

- beginner comprehensibility;
- concept completeness against `FEATURE-AND-COURSE-AUDIT-V2.md`;
- architecture/code accuracy;
- no duplicated canonical explanations;
- interview usability;
- workshop usability;
- executable commands;
- truthful implementation statuses;
- no paid-content mirroring;
- no false production/provider/pgvector/self-reflection claims.

Run:

```bash
python3 scripts/validate-course-docs.py
cd backend
uv run pytest -q tests/unit/test_course_documentation.py
uv run ruff check ../scripts/validate-course-docs.py tests/unit/test_course_documentation.py
uv run ruff format --check ../scripts/validate-course-docs.py tests/unit/test_course_documentation.py
```

Then run the existing full repository acceptance before integration.

## Commit sequence

1. `docs: define capstone course architecture`
2. `docs: add agent runtime and trust curriculum`
3. `docs: add memory rag evaluation curriculum`
4. `docs: add mcp operations and capstone curriculum`
5. `test: validate course documentation contracts`
6. `docs: integrate capstone learning system`

## Explicit non-goals

- No duplicate Spanish and English page trees.
- No copying paid AIAMastery lesson bodies.
- No claim that every discussed concept is implemented.
- No public deployment.
- No source-code behavior changes.
- No push without explicit approval.
