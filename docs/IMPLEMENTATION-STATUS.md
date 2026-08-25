# Archon Implementation Status — Superseded

> **Archived on 2026-08-25.** The [canonical implementation evidence matrix](IMPLEMENTATION-EVIDENCE.md) replaces this document as the source of truth.

## Why this status was superseded

This file previously described a 2026-08-24 baseline at local `main` revision `9462518`. It reported 371 backend tests, 74% coverage, clean Ruff, 6 frontend unit tests, and a capability table based on **Implemented**, **Wired**, **Tested**, and **Demo-ready**.

Those values are historical, not current. A fresh audit at `27952f4` found:

- 466 backend tests passed, 0 skipped, with 81.84% aggregate coverage;
- Ruff failed with 50 errors and 16 files needing formatting;
- 4 Vitest tests and 2 Playwright scenarios;
- Svelte check at 0 errors and 1 warning, with a passing frontend build;
- a passing local Docker `/healthz` smoke using `mock-model/mock`;
- the last 10 remote CI runs failed, while local `main` was 54 commits ahead and had not been pushed.

The prior capability table also overstated several areas. In particular, it did not represent the approval bypass, host-process execution, global plaintext memory, PII-before-persistence, mock/default RAG, MCP/task scaffolding, sequential multi-agent pipeline, mock evaluations, transient run evidence, or absent deployment proof with enough precision.

## Current claim policy

Use [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md), which separates:

1. **Exists** — meaningful code or artifact presence;
2. **Wired** — invocation by a product/API path;
3. **Tested** — relevant automated behavior evidence;
4. **Observed** — behavior directly exercised during audit;
5. **UI** — visible or operable product evidence;
6. **Deployed** — verified non-local environment evidence.

A source file does not imply wiring. Wiring does not imply tests. Tests do not imply direct observation, UI completion, deployment, security, or production readiness. Mocks, stubs, flags, manifests, and local container smoke must remain explicitly labeled.

The historical matrix is available in git history. It is intentionally not duplicated here so this file cannot drift into a second source of truth.
