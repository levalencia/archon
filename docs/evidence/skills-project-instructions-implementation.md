# Skills + Project Instructions — Implementation Evidence

## Scope and claim boundary

- Candidate: local `feature/spi-docscore`, based on `a642952` before this documentation commit.
- Deployed baseline: `main` at `63215bf`.
- Push/deploy: none for this candidate.
- Integrated verification: no final `verify.sh` count is claimed in this packet.

This packet records only the implemented core and direct observations. It does not prove public deployment, broad semantic-selection quality, arbitrary repository trust, a public skill marketplace, generic MCP OAuth, or multi-region operation.

## Implemented core

- Alembic migrations `20260901_15` through `20260901_21`.
- 41 ORM tables at candidate head.
- Ten repository-owned bundled skills.
- Immutable skill revisions and exact owner/project/revision bindings.
- Approved immutable project-instruction snapshots with deterministic precedence.
- One request-context preparation path used by sync and SSE.
- Metadata-first discovery across skills, native tools, and enabled MCP tools.
- Optional GodMode catalog adapter that returns metadata only; it is disabled by default and cannot install or trust content.
- Governed allowlisted stdio and bounded Streamable HTTP MCP profiles; discovery remains separate from policy, approval, and execution-time validation.
- Exact Run Ledger effective-context provenance for instruction revisions, skill revisions, capability IDs, and schema hashes; raw bodies and hidden reasoning are not stored in that snapshot.

## Focused automated coverage

The candidate's focused suites are:

```text
backend/tests/unit/test_skill_parser.py
backend/tests/unit/test_skills_security.py
backend/tests/unit/test_skill_catalog.py
backend/tests/unit/test_skill_persistence.py
backend/tests/unit/test_skill_discovery_enrichment.py
backend/tests/unit/test_instruction_loaders.py
backend/tests/unit/test_instruction_precedence.py
backend/tests/unit/test_instruction_snapshots.py
backend/tests/unit/test_capability_selector.py
backend/tests/unit/test_capability_governance.py
backend/tests/integration/test_skill_migration.py
backend/tests/integration/test_instruction_snapshot_api.py
backend/tests/integration/test_instruction_snapshot_migration.py
backend/tests/integration/test_mcp_transport_governance.py
backend/tests/integration/test_mcp_transport_migration.py
```

Documentation/manifest contracts are checked separately with:

```text
backend/tests/unit/test_capability_acceptance_manifest.py
backend/tests/unit/test_ci_local_run_documentation.py
```

Verification during this documentation update was intentionally recorded without
turning it into a full-suite claim:

- the 15 focused files above collected 67 tests: 66 passed and
  `test_live_native_inventory_has_safe_stable_execution_mapping` failed because
  the live registry returned seven descriptors while the pre-existing test
  requires at least nine;
- the documentation/manifest selection passed 10 tests, with the strict baseline
  check deselected; when included, that check rejects the new capability ID
  because `app/capabilities/acceptance.py` still fixes the baseline to the prior
  16 IDs;
- schema parsing with `require_baseline=False` loaded all 17 entries and every
  source, test, evidence, and owner-module path resolved;
- `git diff --check` passed.

Those two failures require application/test ownership outside this docs-only
change. They are not hidden by a focused-pass or integrated-pass claim.

## Real Foundry acceptance

An operator-authorized acceptance run used provider `foundry` and model `claude-opus-4-6`. It rejected a missing response, a mock response, a missing bound skill, missing instruction/skill provenance, and capability entries without 64-character schema hashes.

Sanitized observed result:

| Field | Result |
|---|---|
| Status | PASS |
| Provider/model | `foundry` / `claude-opus-4-6` |
| Selected skills | 1 |
| Approved instruction revisions | 1 |
| Capability provenance references | 9 |
| Run ID | Present |

No prompt, model response, credential, endpoint, or raw provider error is retained here. One passing run proves this bounded path only; it is not a general model-quality or selector-quality benchmark.

## Temporary PostgreSQL migration acceptance

A disposable PostgreSQL database was created on the retained local stack, migrated with the candidate code, downgraded, re-upgraded, queried, and dropped.

| Check | Result |
|---|---|
| Upgrade head | PASS — `20260901_21` |
| Candidate integrity triggers | 5 |
| Composite owner foreign keys | 2 |
| `mcp_servers.enabled` default | `false` |
| Round trip | PASS — revision 14 → 21 |
| Cleanup | Temporary database dropped |

The observed controls are migration-level evidence on temporary PostgreSQL. They do not mean revision 21 is deployed on `main`.

## Evidence interpretation

`Exists`, `Wired`, `Tested`, `Observed`, `UI`, `Live provider`, and `Deployed` remain independent. For `skills-project-instructions`, the capability manifest records all implemented/local dimensions explicitly and keeps `deployed: no`.
