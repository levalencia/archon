# Documentation Guide

> Conventions for writing and maintaining Archon documentation.

---

## Audience

Archon docs serve three audiences:

1. **Reviewers** — quick understanding of what exists, how it
   was proven, and where the boundaries are.
2. **Operators and learners** — task-focused runbooks and structured explanations.
3. **Contributors** — onboarding, architecture context, writing
   conventions.

Write for the first audience that applies. Prefer short sentences and concrete
evidence over marketing language.

## Status conventions

### Capability status

Capability status is maintained in two canonical sources only:

- **[IMPLEMENTATION-EVIDENCE.md](IMPLEMENTATION-EVIDENCE.md)** — mutable prose
  with revision-scoped claims.
- **[implementation/CAPABILITY-ACCEPTANCE.yaml](implementation/CAPABILITY-ACCEPTANCE.yaml)**
  — machine-readable per-dimension manifest.

Other documents must not introduce independent status claims. When referencing
capability status, link to the canonical source rather than restating values
that will drift.

### Evidence dimensions

Use the six-axis framework consistently:

| Dimension | Question it answers |
|-----------|--------------------|
| Exists | Is there meaningful code or artifact? |
| Wired | Does a live product/API path invoke it? |
| Tested | Do automated tests exercise the contract? |
| Observed | Was it directly exercised in a local evidence run? |
| UI | Does a product surface expose it? |
| Deployed | Was it verified outside the local machine? |

### Document lifecycle

| Status | Meaning |
|--------|---------|
| **Active** | Current and maintained |
| **Superseded** | Replaced by a named successor; kept for traceability |
| **Draft** | Work in progress; not yet reviewed |
| **Archived** | No longer relevant; retained in git history |

## Front matter

Every new Markdown document should open with a title (`# …`) and a brief
scope statement. For documents that carry status, add a blockquote after the
title:

```markdown
# Document Title

> **Status:** Active | Superseded by a named document | Draft
> **Scope:** One sentence describing what this document covers.
```

Plans use the date-prefixed filename convention:
`docs/plans/YYYY-MM-DD-slug.md`.

## Writing principles

1. **Source-grounded.** Every claim must trace to code, a test, a CI run, or a
   direct observation. Do not invent counts, percentages, or status values.
2. **Boundary-honest.** State what is *not* claimed with the same care as what
   is. Mocks, stubs, local-only results, and feature flags must be labeled.
3. **Human-first.** Explain why something matters before explaining its internals.
4. **Concise.** Prefer short paragraphs, concrete examples, and descriptive links.
   Remove filler, repeated caveats, commit IDs, CI run IDs, and mutable counts
   from human-facing pages.
5. **Humble.** Archon is a portfolio project with local evidence. Do not use
   "production-grade," "enterprise-ready," or similar phrasing unless
   qualified by the exact deployment and evidence scope.
6. **English.** All documentation is in English.

## File organization

Documentation lives under `docs/` with this layout:

```
docs/
├── README.md                  ← reader-intent index (this layer)
├── EVIDENCE.md                ← human evidence summary
├── DOCUMENTATION-GUIDE.md     ← this file
├── IMPLEMENTATION-EVIDENCE.md ← canonical mutable status
├── implementation/            ← machine-readable manifests
├── architecture/              ← architecture decision context
├── adr/                       ← architecture decision records
├── course/                    ← structured learning material
├── evidence/                  ← evidence artifacts (JSON, etc.)
├── history/                   ← superseded plans, audits, and research
├── operations/                ← operational runbooks
├── plans/                     ← dated plan documents
└── visual-learning/           ← learning media and studio
```

## Linking

- Use relative paths from the current file's location.
- Verify that the target file exists before adding a link.
- Prefer linking to the canonical source over duplicating content.

## What not to do

- Do not add status tables that compete with `IMPLEMENTATION-EVIDENCE.md`.
- Do not commit generated artifacts (audio, video, images) to the docs tree.
- Do not reference test counts or coverage numbers outside the canonical
  evidence file — they change with every CI run.
- Move superseded plans, audits, and research into `docs/history/`; preserve
  current evidence and operational paths.
