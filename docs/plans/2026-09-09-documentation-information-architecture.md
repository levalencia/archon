# Plan: Human-first Documentation

> **Date:** 2026-09-09
> **Status:** Implemented candidate
> **Scope:** Clarify the documentation hierarchy without weakening technical evidence.

## Goal

Make the repository understandable to a new reader without forcing them through audit logs, historical plans, or machine-oriented evidence.

## Information architecture

1. **Root README:** short project landing page, architecture overview, quick start, limits, and routes into deeper documentation.
2. **Documentation index:** `docs/README.md`, organized by reader intent.
3. **Human evidence guide:** `docs/EVIDENCE.md`, explaining what the evidence means without duplicating mutable results.
4. **Technical evidence:** `docs/IMPLEMENTATION-EVIDENCE.md` and `docs/implementation/CAPABILITY-ACCEPTANCE.yaml` remain canonical.
5. **Specialized guides:** architecture, operations, course, visual learning, and reference material.
6. **Historical material:** retained at stable paths, but labeled so it cannot be mistaken for current status.

## Humanization rules

- Explain why before implementation detail.
- Prefer short paragraphs and concrete examples.
- Define specialized terms when first used.
- Keep commit IDs, CI run IDs, and mutable counts out of human entry points.
- Link to evidence instead of repeating it.
- State limitations once, plainly.
- Give long-lived documents an audience, purpose, and lifecycle status.

## Implemented scope

- Replaced the root README with a concise landing page.
- Added a reader-intent documentation index.
- Added a human evidence guide.
- Added documentation writing and lifecycle conventions.
- Classified the largest evidence, planning, research, audit, and launch documents.
- Preserved stable paths so existing evidence and course links continue to work.

## Deliberate limits

This pass does not rewrite every course module, technical reference, or historical document. Those files serve specialized readers and should be improved when their content next changes.

Physical relocation into `docs/history/` is deferred. Moving heavily referenced files now would create link churn without improving the primary reading path.

## Acceptance criteria

- [x] Root README is no longer an implementation inventory or audit log.
- [x] Root README contains no commit IDs, PR numbers, CI run IDs, or mutable test totals.
- [x] `docs/README.md` routes readers by intent.
- [x] `docs/EVIDENCE.md` explains evidence without becoming a competing status source.
- [x] Canonical evidence paths remain unchanged.
- [x] Large historical and specialist documents declare audience, purpose, and status.
- [x] Repository documentation and stale-claim checks pass.
- [x] All changed links resolve.
