# Student guide

## What you will do

Across eight workshops you will trace Archon from agent anatomy through reliability, producing one evidence-backed artifact per session. The schedule and prereads are in the [company workshop track](../tracks/company-workshops.md); detailed tasks are in [exercises](exercises.md).

## Setup

Required for code labs: Git, Python 3.11, and `uv`. Node.js 22+ and Docker are needed only for exercises that explicitly name them. Use the repository root as your starting directory and confirm the revision supplied by your instructor.

```bash
git status --short --branch
git rev-parse --short HEAD
cd backend
uv sync
uv run pytest -q tests/unit/test_runtime_v2.py::test_typed_tool_round_trip_and_events
```

If setup cannot be completed, use the paper trace variant. Never claim you ran a command you only read.

## Keep secrets and data safe

- Copy the repository’s example environment file; never commit `.env`.
- Use only instructor-approved mock credentials and synthetic data.
- Do not paste tokens, cookies, JWTs, encryption keys, private documents, user messages, memory exports, database rows, raw tool arguments/results, or full exception payloads into artifacts.
- Before sharing terminal output, inspect and redact it. Hashes and redaction are controls, not permission to ingest sensitive data.
- Use disposable owner/project IDs and complete each cleanup step.
- If a secret is exposed, stop, tell the instructor, and follow rotation/reporting procedures.

## How to work

In pairs, one person drives and one navigates; switch halfway. For each task record:

```text
revision:
environment:
command or inspection path:
observed result:
source symbol:
behavior test:
claim supported:
not proved / limitation:
cleanup:
```

Ask for observable rationale, not private chain-of-thought. “I cannot verify that from available evidence” is a strong answer.

## Pacing and completion

Complete prereading before each 90-minute session. During class, reserve the final 20 minutes for artifact and self-check rather than continuing an unbounded debug session. Submit all eight sanitized artifacts. The capstone requires at least level 3 in every [rubric](capstone-rubric.md) dimension.

## Troubleshooting ladder

1. Re-read the exact task and done criteria.
2. Confirm current directory, revision, and command spelling.
3. Open the named source symbol and focused test in [code bookmarks](../reference/code-bookmarks.md).
4. Narrow a failing test to one node; preserve actual output.
5. Check prerequisites without changing global machine state.
6. Ask the instructor with revision, command, safe error summary, and what you already checked.

Do not disable encryption, authorization, TLS verification, validation, or cleanup just to obtain a green result. Do not run migrations or destructive commands against shared data.

## Language guardrails

Use “demonstrates under this revision/environment” rather than “guarantees.” Keep these distinctions explicit:

- local production-like Compose vs public production deployment;
- SQL JSON vectors/Python cosine vs pgvector;
- ReAct tool observations vs generic self-reflection;
- deterministic claim checks vs semantic truth;
- one bounded verifier specialist vs a dynamic swarm;
- a passing fixture vs broad model quality;
- measured restore observation vs guaranteed RTO/RPO.

## Where to look

[Glossary](../reference/glossary.md) · [API map](../reference/api-map.md) · [events](../reference/event-catalog.md) · [stop reasons](../reference/stop-reasons.md) · [schema](../reference/database-schema.md) · [tests](../reference/test-map.md)
