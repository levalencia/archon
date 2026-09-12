# Contextual Visual Learning Tutor Implementation Plan

## Goal

Add an authenticated, context-aware tutor to every Visual Learning view and video. The tutor opens in a collapsible right-side panel, answers from a curated local knowledge index, cites commit-pinned documentation/code/tests and timestamped videos, includes relevant code excerpts, and can return evidence-linked structured diagrams.

## Architecture

- Reuse Cogentrex's configured model provider, embedding service, monetary budget wrapper, run ledger, compliance controls, verifier, and PostgreSQL service.
- Keep the tutor read-only. Do not expose the general chat tool registry, web search, file writes, terminal, MCP, or sandbox.
- Store curated learning sources in dedicated `learning_sources` and `learning_chunks` tables so application-owned knowledge cannot mix with tenant-uploaded documents.
- Store user-owned conversations in dedicated `learning_tutor_sessions` and `learning_tutor_turns` tables with immutable context/evidence snapshots.
- Reuse SQL-JSON embeddings and cosine similarity. Add context-first hybrid scoring (anchor + lexical + dense) before considering another vector database.
- Resolve all client context IDs server-side against the generated Visual Learning manifest and validated learning-media catalog.
- Render diagrams from a strict node/edge JSON contract through a first-party Svelte/SVG renderer. Never execute model-authored HTML, SVG, JavaScript, or Mermaid.

## TDD slices

1. Context contracts and server-side resolver.
2. Dedicated knowledge schema, migration, and repository.
3. Source-aware Markdown/code/video chunking and idempotent sync command.
4. Context-first hybrid retrieval and typed citations.
5. Grounded tutor workflow with strict structured output, verification, code excerpts, budgets, and abstention.
6. Authenticated API, durable sessions/turns, and lifecycle streaming.
7. Universal Visual Learning trigger and responsive right-side panel.
8. Video timestamp capture and citation seek links.
9. Structured diagram rendering and accessibility fallback.
10. Deterministic, PostgreSQL integration, browser, adversarial, and live-provider evaluation.
11. Canonical documentation, capability acceptance, and operations runbook.

## First vertical acceptance case

From Video 2, ask: `What is a service slot?`

The answer must:

- explain the concept for a beginner;
- quote a relevant code excerpt rather than only linking to it;
- cite the Video 2 application-state segment with exact start/end seconds;
- cite `backend/app/main.py` with exact lines;
- cite the canonical application-composition concept;
- distinguish an initially empty application-owned slot from a constructed runtime service;
- include a small evidence-linked lifecycle diagram when useful;
- make no unsupported runtime or deployment claim.

## Verification ladder

- Unit: parsers, context validation, ranking, citation integrity, prompt-injection boundaries, diagram validation.
- SQLite integration: repository CRUD, idempotent sync, owner isolation, session reload.
- PostgreSQL integration: migration round trip, unique/check constraints, concurrent sync safety, real SQL-JSON retrieval.
- API: auth, rate limit, invalid/forged context, no-evidence abstention, persisted history.
- Frontend: all seven views, keyboard/focus behavior, mobile Sheet, video seek, source links, diagram fallback.
- Deterministic evaluation: real repository and Video 1/2 content, citation precision/recall, timestamp correctness, unsupported-claim rate.
- Live-provider acceptance: difficult questions using real embeddings/model; mocks do not count as semantic evidence.

## Boundaries

- No commit, push, merge, deployment, gateway start, or provider-budget spend without explicit authorization.
- Indexing with mock embeddings proves deterministic plumbing only.
- Index only allowlisted canonical sources and validated media; exclude credentials, `.env`, history, arbitrary workspaces, and unpublished media in production.
