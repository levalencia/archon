# Documentation and Visual Learning refresh plan

## Goal

Bring Archon's public GitHub documentation and Visual Learning Studio sources into alignment with merged `main` at `1f71f0e1ada7da4989ef7e313581b7476f82c804`, while preserving historical evidence as historical evidence and avoiding claims not proven by current acceptance.

## Evidence baseline

- PR #10 merged as `041ff75a229932fdb995a0a5254bc3546af51262`.
- PR #11 merged as `1f71f0e1ada7da4989ef7e313581b7476f82c804`.
- Post-merge GitHub Actions run `33858051794` passed at the exact main SHA.
- That CI run reported backend 1,579 passed / 6 skipped / 87.15% coverage, Svelte 0 errors / 0 warnings, 15 Vitest files, and 35 Playwright tests.
- The retained local live-Foundry stack is healthy at Alembic `20260902_22`, but remains local-only rather than public/cloud deployment.
- Deterministic wiring proves `Settings.agent_max_tool_calls` reaches sync/SSE context and `RuntimeBudget`; live provider execution of more than eight approved tool calls is not yet accepted.

## Scope

1. Refresh current-state sections in:
   - `README.md`
   - `docs/IMPLEMENTATION-EVIDENCE.md`
   - `docs/ARCHITECTURE-DIAGRAMS.md`
   - `docs/REMAINING-DEFERRED-GAPS.md`
   - `docs/DEMO-SCRIPT.md`
   - `docs/architecture/skills-project-instructions.md`
   - `docs/evidence/skills-project-instructions-implementation.md`
2. Update course/Visual Learning source truth where recent runtime and migration behavior matters:
   - tool-budget configuration and prompt/runtime alignment;
   - budget-exhaustion synthesis with synthetic unexecuted-tool results;
   - request-sized monetary quote plus headroom and conservative eligible price class;
   - forward-head core-table reconciliation and accepted known PostgreSQL legacy forms;
   - current migration head and schema reference.
3. Reconcile `docs/implementation/CAPABILITY-ACCEPTANCE.yaml` wording and test pointers without upgrading unsupported dimensions.
4. Regenerate `frontend/static/learning/archon-studio.json` from canonical sources.
5. Add or extend documentation regression checks for current-state invariants and prohibited stale claims.

## Honesty constraints

- Keep `Deployed: No` for public/non-local deployment.
- Do not claim live provider execution above eight tools.
- Do not turn old revision-scoped evidence into current evidence; label it historical or superseded.
- Do not claim pgvector, production traffic, SLOs, cloud deployment, provider parity, native Foundry JSON Schema, or cache savings.
- Distinguish exact-head GitHub CI, deterministic local tests, retained local runtime, and live-provider observations.
- Avoid hardcoding mutable counts outside the README/current evidence summary unless they are explicitly revision-scoped.

## Execution sequence

1. Audit stale current-state claims and inspect source/tests for every replacement.
2. Edit the smallest set of canonical/public documents needed to remove contradictions.
3. Add regression assertions before or alongside the documentation changes.
4. Regenerate the Visual Learning manifest.
5. Run focused documentation and Visual Learning tests.
6. Run formatting/lint gates affected by changed scripts/tests.
7. Independently review the diff for overclaims, stale SHAs, broken links, and accidental rewriting of historical records.
8. Run final verification and create one local verified documentation commit.

## Verification

- `uv run python ../scripts/validate-course-docs.py`
- `uv run python ../scripts/build-visual-learning.py --check`
- focused backend documentation/visual-learning/migration/tool-budget tests
- frontend Visual Learning unit and Playwright tests after `npm ci`
- `git diff --check`
- stale-claim search for `63215bf`, candidate-not-pushed/deployed wording, and obsolete current head/count claims
- independent fresh-context review
