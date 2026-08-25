# Archon Implementation Status — Superseded

> **Archived on 2026-08-25.** The [canonical implementation evidence matrix](IMPLEMENTATION-EVIDENCE.md) replaces this document as the source of truth.

## Why this status was superseded

This file previously described a 2026-08-24 baseline at local `main` revision `9462518`. It reported 371 backend tests, 74% coverage, clean Ruff, 6 frontend unit tests, and a capability table based on **Implemented**, **Wired**, **Tested**, and **Demo-ready**.

Those values are an immutable historical snapshot, not current status. The superseding audit found meaningful test and local runtime evidence, but it did not establish green quality and release gates or a verified deployment. Exact current results and repository state are maintained only in [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md).

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
