# Archon Remaining Reliability Work Implementation Plan

> **For Hermes:** Execute task-by-task with isolated worktrees, integrate in dependency order, and run `./scripts/verify.sh` after each slice.

**Goal:** Finish Archon's remaining reliability-workbench capabilities without adding disconnected feature files.

**Architecture:** Extend the existing typed runtime, user-scoped repositories, persisted runtime events, and Svelte Workbench. Every capability must be wired through the live path, owner-scoped, deterministic in CI, visible in the UI where relevant, and proven with a real-provider regression when provider behavior is involved.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, pytest, SvelteKit, TypeScript, Vitest, Playwright, Docker, OpenTelemetry.

---

## Verified starting point

- Local `main` at `2120d44`, ahead of remote; no push authorized.
- `./scripts/verify.sh`: 371 backend tests, zero skipped, Ruff/format/Bandit, 6 Vitest, 2 Playwright, build, Docker smoke — all pass.
- Foundry + Brave regression for the ten-smallest-countries query: 5 distinct searches, zero duplicate calls, 3 iterations, `completed`, 4,757-character answer.
- Runtime events are persisted but not owner-scoped or exposed through a replay API/UI.

## Task 1: Durable, owner-scoped run replay

**Files:**
- Modify: `backend/app/services/db_store.py`
- Modify: `backend/app/services/conversations.py`
- Create: `backend/app/routes/runs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_run_replay.py`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/components/Inspector.svelte`
- Modify: `frontend/src/lib/components/Workbench.svelte`
- Test: `frontend/src/lib/RunReplay.test.ts`
- Modify: `frontend/tests/workbench.spec.ts`

**Acceptance:**
1. Persist `user_id` on runtime events.
2. List runs only for the authenticated user's conversations.
3. Fetch one ordered event trajectory by `run_id`; cross-user access returns 404.
4. Inspector can load a persisted run after page reload and display stop reason, tools, iterations, usage, and trajectory.
5. Persistence survives repository/application restart.
6. Full acceptance gate passes and tree is clean.

## Task 2: Permission policy and human approval

**Files:**
- Create: `backend/app/security/tool_policy.py`
- Modify: `backend/app/tools/registry.py`
- Modify: `backend/app/runtime/engine.py`
- Create: `backend/app/routes/approvals.py`
- Test: `backend/tests/security/test_tool_approvals.py`
- Modify Workbench/Inspector approval UI and tests.

**Acceptance:** enforce `allow | ask | deny` before execution; pending approvals are user/run scoped; denial is auditable; resumed execution preserves event order; dangerous tools never execute before approval.

## Task 3: Governed MCP adapter

**Files:**
- Create: `backend/app/mcp/{models,client,adapter}.py`
- Modify tool registry/config/startup.
- Add deterministic fake-MCP contract tests and one opt-in live smoke.

**Acceptance:** MCP tools normalize into existing `ToolDefinition/ToolCall`; policy applies identically to built-ins; server failures produce typed events and stop reasons; no server means no advertised tools.

## Task 4: One bounded specialist delegation workflow

**Acceptance:** one coordinator → specialist handoff with explicit budget, isolated context, typed events, cancellation, and deterministic tests. No general multi-agent feature expansion.

## Task 5: Deployment and evidence

**Acceptance:** deploy the already-tested image to one real target, verify `/healthz`, `/readyz`, auth, chat/SSE, run replay, and one research query; publish benchmark/eval output and update README/status only from evidence.

## Universal gates

```bash
./scripts/verify.sh
```

Additionally:
- zero skipped tests;
- no secrets/runtime DBs in Git;
- `git diff --check` clean;
- desktop and mobile Playwright pass;
- real-provider regression for changes affecting model/tool behavior;
- no push without Luis's explicit confirmation.
