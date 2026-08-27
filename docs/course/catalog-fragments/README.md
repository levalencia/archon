# Concept Catalog Fragments

Catalog fragments are review-sized YAML inputs for the future generated `../concept-catalog.yaml`. They make concept-to-code-to-test-to-evidence traceability reviewable by curriculum area. The composed catalog, once generated, is the machine-readable index; canonical prose remains in each concept page.

Do not hand-maintain duplicate entries in multiple fragments. Use one stable concept ID and one owning fragment.

## Planned fragments

| File | Scope | Plan task |
|---|---|---:|
| `00-foundations.yaml` | Modules 00–05: agent/runtime, Python architecture, ReAct, tools, policy, approvals | 2 |
| `01-knowledge.yaml` | Modules 06–10: context/memory, ledger, RAG, evaluation, resilience | 3 |
| `02-advanced.yaml` | Modules 11–15: verifier, MCP, UI/observability, operations, capstone | 4 |

These files are **planned** and intentionally absent in Task 1.

## Fragment shape

Each fragment is a YAML mapping with a schema version and a `concepts` list:

```yaml
schema_version: 1
fragment: foundations
concepts:
  - id: example-concept
    title: Example concept
    status: partial
    status_boundary: >-
      Useful behavior exists, but the named live-path or evidence boundary is incomplete.
    canonical_page: docs/course/concepts/example-concept.md
    modules:
      - docs/course/modules/00-example/README.md
    prerequisites:
      - prerequisite-concept-id
    source_symbols:
      - path: backend/path/to/module.py
        symbol: ExampleClass.example_method
        role: Contract or behavior demonstrated by this symbol.
    tests:
      - path: backend/tests/unit/test_example.py
        symbol: test_example_contract
        proves: The specific behavior asserted by this test.
        does_not_prove: External-provider, scale, or production behavior.
    evidence:
      - path: docs/IMPLEMENTATION-EVIDENCE.md
        anchor: capability-matrix
        proves: The relevant current evidence dimension.
        scope: Local, tested, observed, UI, or deployment boundary.
    limitations:
      - A precise implementation or production gap.
```

The example shows shape only. Replace every example path and symbol with an existing reviewed target before adding a real fragment.

## Required fields

| Field | Rule |
|---|---|
| `schema_version` | Integer shared by all fragments; start at `1`. |
| `fragment` | Unique stable kebab-case fragment name. |
| `concepts` | List of concept records; may not duplicate an ID from another fragment. |
| `id` | Unique stable kebab-case identifier; do not encode module order in reusable concept IDs. |
| `title` | Human-readable canonical English name. |
| `status` | Exactly `implemented`, `partial`, `not-implemented`, or `deferred`. |
| `status_boundary` | Required precise explanation of what is and is not present. |
| `canonical_page` | Repository-relative path to the single concept explanation. |
| `modules` | One or more repository-relative module paths that teach or use the concept. |
| `prerequisites` | Concept IDs; use `[]` only for true roots. No dependency cycles. |
| `source_symbols` | List of `path`, `symbol`, and `role`; required and non-empty for `implemented`. |
| `tests` | List of `path`, `symbol`, `proves`, and `does_not_prove`; required and non-empty for `implemented`. |
| `evidence` | List of `path`, optional `anchor`, `proves`, and `scope`; required and non-empty for `implemented`. |
| `limitations` | At least one concrete boundary for `implemented` and `partial`; use a clear non-goal for deferred concepts. |

`not-implemented` and `deferred` concepts may use empty `source_symbols`, `tests`, and `evidence` lists. If partial code exists, include it under `partial`; do not use `not-implemented` to hide a useful but incomplete implementation.

## Status and evidence rules

- **`implemented`:** meaningful behavior is wired, tested, and evidenced. A source file alone is insufficient.
- **`partial`:** name the exact incomplete wiring, test, evidence, safety, UX, scale, or provider boundary.
- **`not-implemented`:** no meaningful current implementation; stubs and historical experiments do not count.
- **`deferred`:** deliberately out of scope, without an implied delivery date.
- Keep Exists, Wired, Tested, Observed, UI, and Deployed dimensions independent in `evidence.scope`.
- Link current status to `docs/IMPLEMENTATION-EVIDENCE.md`; use historical audits only as labeled context.
- Paths are repository-relative, use `/`, must not escape the repository, and must resolve when their fragment is merged.
- Source and test `symbol` values must name exact classes, functions, methods, or tests—not merely files.
- Runtime evidence must be committed, redacted, deterministic where claimed, and free of secrets or ephemeral local paths.

## Terminology safeguards

Create separate IDs and pages for:

- bounded ReAct control-loop behavior;
- deterministic claim verification;
- bounded verifier delegation;
- post-run evaluation;
- generic self-reflection.

Generic self-reflection must not be `implemented` based on retries, tool-error feedback, claim filtering, verifier delegation, or evaluation. Likewise, use `sql-json-cosine`, not pgvector; one verifier specialist, not a dynamic swarm; production-like local Compose, not public deployment.

## Composition and review

Before a fragment can be composed:

1. confirm every canonical page and module path exists;
2. confirm every source/test/evidence path and named symbol exists;
3. inspect the test to ensure `proves` is accurate;
4. verify implemented entries have source, test, and evidence lists;
5. check prerequisite IDs exist and form no cycle;
6. ensure current evidence supports the status at the reviewed revision;
7. ensure no secret, generated runtime artifact, private paid-content path, or absolute workstation path is referenced;
8. run the course validator when it is introduced in Task 5.

Fragments are inputs, not alternate prose documentation. Keep explanations in canonical concept pages and keep mutable evidence in the existing evidence matrix.
