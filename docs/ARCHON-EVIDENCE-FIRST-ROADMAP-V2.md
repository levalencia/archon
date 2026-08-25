# Archon Evidence-First Feature Roadmap v2

> **For Hermes:** Use subagent-driven-development to execute this plan task-by-task. Every slice requires spec review, code review, and a green acceptance gate before integration.

**Goal:** Turn Archon's broad course/competitor feature coverage into five deep, credible, end-to-end Agent Reliability Workbench capabilities that demonstrate employability.

**Architecture:** Keep the existing custom typed runtime, provider protocols, FastAPI backend, SvelteKit frontend, and local-first operation. Do not add another agent framework. Build vertical slices around immutable run evidence, explicit policy, grounded evaluation, and bounded delegation. Existing mock/stub features must either become real or be renamed/removed from the demo path.

**Tech stack:** Python 3.11, FastAPI, Pydantic, SQLAlchemy async, PostgreSQL/SQLite fallback, pgvector where genuinely configured, SvelteKit, TypeScript, Vitest, Playwright, pytest, Ruff, Bandit, Mypy ratchet, Docker Compose, OpenTelemetry.

**Source audits:**

- `docs/FEATURE-AND-COURSE-AUDIT-V2.md`
- `docs/ARCHON-GPT56-REAUDIT-2026-08-25.md`

---

# Product thesis

Archon will not claim generic parity with Hermes, Codex, Claude Code, or OpenCode.

Its portfolio differentiator will be this inspectable workflow:

> configure policy → run agent → approve/deny action → inspect context/evidence/tools → evaluate result → checkpoint → fork → compare

Five capabilities must be deep and demo-ready:

1. **Trust and policy layer**
2. **Durable Run Ledger**
3. **Grounded knowledge and real evaluation**
4. **One bounded specialist delegation workflow**
5. **Evidence-first responsive Workbench**

MCP and deployment support those capabilities; they are not headline feature-count metrics.

---

# Definition of done for every slice

A slice is done only when all applicable columns are Yes:

| Exists | Wired | Tested | Observed | UI | Documented |
|---|---|---|---|---|---|
| Meaningful code | Default/live path | Deterministic contract tests | Real smoke or browser evidence | User can inspect/control it | Claim matches evidence |

Required gate after every integrated slice:

```bash
cd backend
uv run ruff check app tests
uv run ruff format --check app tests
uv run bandit -r app -ll
uv run pytest -q --disable-warnings

cd ../frontend
npm run check
npm test -- --run
npm run build
npx playwright test

cd ..
./scripts/verify.sh
```

Additional rules:

- Zero skipped tests.
- Do not lower assertions to make tests pass.
- Do not count mocks as live provider evidence.
- Do not claim Redis/Postgres/OTEL because a container is running; prove the request path uses it.
- Ratchet Mypy on touched/new modules; do not block all work on the existing full-app backlog.
- One green local commit per slice.
- No push without Luis's approval.

---

# Sprint 0 — Restore a truthful green baseline

**Course concepts:** Day 27 Testing and QA, Day 30 Production Deployment  
**Competitor patterns:** verification evidence, reproducible runs, trustworthy status

## Task 0.1 — Preserve audits and freeze the evidence baseline

**Files:**

- Add: `docs/FEATURE-AND-COURSE-AUDIT-V2.md`
- Add: `docs/ARCHON-GPT56-REAUDIT-2026-08-25.md`
- Create: `docs/IMPLEMENTATION-EVIDENCE.md`

**Steps:**

1. Create one canonical evidence table with `Exists/Wired/Tested/Observed/UI/Deployed`.
2. Link old matrices as historical, not authoritative.
3. Record audited revision and exact commands.
4. Verify no secrets or paid lesson text are present.
5. Commit documentation separately.

## Task 0.2 — Restore local code-quality gates

**Files:** all files reported by Ruff/format; no behavior changes mixed into this task.

**Steps:**

1. Save current Ruff output.
2. Run `uv run ruff check app tests --fix`.
3. Run `uv run ruff format app tests`.
4. Review every semantic autofix.
5. Fix the dead frontend eval CSS warning.
6. Run backend/frontend gates.
7. Commit formatting/lint only.

**Acceptance:** Ruff, format, Bandit, 466+ tests, Svelte check, Vitest, build and Playwright pass.

## Task 0.3 — Correct public claims

**Files:**

- Modify: `README.md`
- Replace or deprecate: `EXECUTIVE_SUMMARY.md`
- Replace or deprecate: `FEATURE_MATRIX.md`
- Modify: `docs/IMPLEMENTATION-STATUS.md`

**Steps:**

1. Remove `37/37`, `zero dead code`, and `production-grade` claims.
2. Use the canonical evidence table.
3. State which provider/backends the demo actually uses.
4. Distinguish local tests from remote CI and deployment.
5. Commit docs.

## Task 0.4 — Obtain remote evidence

1. Present local commits and gate output to Luis.
2. Ask permission to push.
3. Push only after approval.
4. Watch GitHub Actions.
5. Fix remote-only failures.
6. Record green run URL in `IMPLEMENTATION-EVIDENCE.md`.

**Sprint done:** clean local tree, full local gate green, remote CI green, documentation consistent.

---

# Sprint 1 — Trust and policy layer

**Course concepts:** Day 2 Secure Memory, Day 3 Secure Tools, Day 4 Resilience, Day 10 Secure Code Execution, Day 15 Multi-Agent Security, Day 22 API Gateway, Day 24 Compliance  
**Competitor patterns:** Hermes/Codex/Claude/OpenCode approval policy and isolation

## Task 1.1 — Create explicit policy domain models

**Files:**

- Create: `backend/app/security/policy.py`
- Create: `backend/tests/security/test_policy_engine.py`

**Models:**

- `PolicyAction`: `allow | ask | deny`
- `ApprovalScope`: `once | run | session | rule`
- `ResourcePattern`
- `PolicyRule`
- `PolicyDecision`
- `RiskClass`: `read | write | execute | network | secret | external_side_effect`

**TDD contracts:**

1. Last matching specific rule wins.
2. Deny wins when equal specificity conflicts.
3. Unknown side-effecting action fails closed.
4. Path/host/tool matching is canonicalized before evaluation.
5. Decision includes matched rule and human-readable reason.

## Task 1.2 — Unify sync and SSE runtime construction

**Files:**

- Create: `backend/app/runtime/factory.py`
- Modify: `backend/app/routes/chat.py`
- Modify: `backend/app/routes/stream.py`
- Test: `backend/tests/integration/test_runtime_route_parity.py`

**Contracts:**

- Both routes use the same provider, registry, budget, event sink and approval policy.
- Approval-required action with no approval service returns explicit denied/fail-closed stop reason.
- Sync chat cannot bypass approval.

## Task 1.3 — Persist owner-scoped approvals

**Files:**

- Modify: `backend/app/services/db_store.py`
- Create: `backend/app/security/approvals.py`
- Modify: `backend/app/routes/stream.py`
- Create: `backend/app/routes/approvals.py`
- Test: `backend/tests/security/test_approval_ownership.py`

**Persist:** user, conversation, run, tool call, normalized arguments hash, risk, policy result, status, scope, expiry, approver, timestamp.

**Attack tests:**

- User B cannot view/approve User A's request.
- Replayed approval ID fails.
- Expired approval fails.
- Modified arguments invalidate approval.
- Restart preserves pending/decided history.

## Task 1.4 — Make memory user/project scoped and truly encrypted

**Files:**

- Replace live use of `backend/app/memory/persistent.py`
- Extend: `backend/app/services/db_store.py`
- Modify: `backend/app/tools/memory_tools.py`
- Modify: `backend/app/runtime/context.py`
- Create: `backend/tests/security/test_memory_isolation_encryption.py`

**Contracts:**

- Memory row includes user, optional project, source conversation/run/message, created/updated, expiry and status.
- Encryption applies to persisted value, not an unused side store.
- User B never receives User A's memory.
- List/edit/delete/export operate through ownership checks.
- No plaintext `archon_memory.json` in the live path.

## Task 1.5 — Apply PII policy before persistence

**Files:**

- Create: `backend/app/security/content_pipeline.py`
- Modify: `backend/app/routes/chat.py`
- Modify: `backend/app/routes/stream.py`
- Test: `backend/tests/security/test_pii_before_storage.py`

**Contracts:** raw sensitive input never reaches conversation/memory/audit storage unless an explicit policy permits encrypted restricted storage.

## Task 1.6 — Wire resilience controls

**Files:**

- Create: `backend/app/middleware/rate_limit.py`
- Modify: `backend/app/main.py`
- Modify provider creation in `backend/app/agents/llm_factory.py`
- Test: `backend/tests/integration/test_live_resilience.py`

**Contracts:**

- Per-user and per-IP limits on auth/chat/task/MCP routes.
- Retry-after headers.
- Provider circuit breaker wraps real completion calls.
- Metrics and UI expose actual breaker state.

## Task 1.7 — Remove false sandbox claim and isolate execution

**Files:**

- Create: `backend/app/execution/protocols.py`
- Create: `backend/app/execution/docker_backend.py`
- Modify: `backend/app/tools/sandbox.py`
- Modify: `backend/app/tools/terminal.py`
- Test: `backend/tests/security/test_execution_isolation.py`

**Minimum safe interim:** remove terminal/code tools from the default registry until the backend is available.

**Isolation tests:** filesystem escape, network denial, env-secret absence, PID/memory/time limit, symlink escape, process cleanup.

**Sprint done:** dangerous actions fail closed, approval is owner-scoped, memory is private/encrypted, PII is handled before storage, live resilience is enforced, execution boundary is honest.

---

# Sprint 2 — Durable Run Ledger, replay, fork and compare

**Course concepts:** Day 8 Chat, Day 9 Conversation Management, Day 13 Tool Monitoring, Day 14 Monitoring, Day 26 Observability, Day 27 QA  
**Competitor patterns:** sessions, resume/fork, checkpoints, hooks/events

## Task 2.1 — Extend event persistence with ownership and stable schema

**Files:**

- Modify: `backend/app/services/db_store.py`
- Modify: `backend/app/observability/runtime_events.py`
- Create: `backend/app/runs/models.py`
- Test: `backend/tests/integration/test_run_event_persistence.py`

**Persist:** run/user/conversation/correlation/parent IDs, sequence, timestamp, kind, redacted payload, provider/model, schema version.

**Contracts:** ordered, append-only, owner-scoped, bounded retention, restart-safe.

## Task 2.2 — Add authenticated run APIs

**Files:**

- Create: `backend/app/routes/runs.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/security/test_run_ownership.py`

**Endpoints:**

- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/events`
- `POST /api/runs/{run_id}/fork`
- `GET /api/runs/compare?a=&b=`

**Rule:** replay endpoints are read-only. They never call models or tools.

## Task 2.3 — Restore full run state after reload

**Files:**

- Create: `frontend/src/lib/runs.ts`
- Create: `frontend/src/lib/components/RunTimeline.svelte`
- Create: `frontend/src/lib/components/RunSummary.svelte`
- Modify: `frontend/src/lib/components/Workbench.svelte`
- Modify: `frontend/src/lib/components/Inspector.svelte`
- Test: `frontend/src/lib/runs.test.ts`
- Test: `frontend/tests/run-replay.spec.ts`

**UI restores:** tools, approvals, evidence, context, tokens, cost, latency, iterations, evals, logs, stop reason.

## Task 2.4 — Add checkpoint and fork semantics

**Files:**

- Extend: `backend/app/memory/checkpoints.py`
- Create: `backend/app/runs/checkpoints.py`
- Modify: `frontend/src/lib/components/Inspector.svelte`
- Test: `backend/tests/integration/test_run_fork.py`

**Checkpoint records:** source run/event, conversation snapshot, policy profile, selected memory IDs, code/workspace reference where applicable.

**UI wording:** explicitly state what is and is not restored.

## Task 2.5 — Add run comparison

Compare:

- answer/evidence;
- model/provider/settings;
- tools and approvals;
- latency/cost/tokens;
- eval scores;
- stop reason;
- changed context/memory.

**Sprint done:** refreshing a run loses nothing; users can inspect, fork and compare without re-executing tools.

---

# Sprint 3 — One real grounded workflow and evaluation loop

**Course concepts:** Day 5 Documents, Day 11 Multimodal Classification, Day 12 Learning/Compliance, Day 20 Production Learning, Day 25 Cost, Day 27 QA  
**Advanced concepts:** RAG, agentic RAG, RAG evaluation, governance, dataset/versioning

## Task 3.1 — Persist document metadata and ownership

**Files:**

- Modify: `backend/app/services/db_store.py`
- Modify: `backend/app/routes/documents.py`
- Test: `backend/tests/integration/test_document_restart_persistence.py`

Remove module-level `_document_registry` from the live path.

## Task 3.2 — Make vector backend honest and compatible

**Files:**

- Modify: `backend/app/services/vector_store.py`
- Replace or rename: `backend/app/services/pgvector_store.py`
- Modify: `backend/app/services/rag_pipeline.py`
- Test: `backend/tests/integration/test_vector_backend_contract.py`

**Decision:**

- Implement actual PostgreSQL `VECTOR` + index; or
- Rename current store to `PostgresJsonVectorStore` and stop claiming pgvector.

Both backends must accept the same owner/document filtering contract.

## Task 3.3 — Verify a real embedding provider

**Files:**

- Create provider capability tests.
- Add explicit embedding configuration/readiness.
- Keep deterministic fake for CI.
- Add opt-in live smoke that records provider/model/dimensions without secrets.

## Task 3.4 — Integrate evidence verification into live research/RAG

**Files:**

- Reuse: `backend/app/research/workflow.py`
- Modify: chat/tool integration
- Extend run events with evidence/claim links
- Test: unsupported claim, duplicate source, stale source, empty evidence, partial support.

## Task 3.5 — Replace mock A/B and batch eval paths

**Files:**

- Modify: `backend/app/routes/red_team.py`
- Extend: `backend/app/eval/harness.py`
- Create: `backend/app/eval/datasets.py`
- Create versioned fixtures under `backend/tests/fixtures/evals/`

Eval real recorded runs; do not fabricate model responses.

## Task 3.6 — Build Evaluation run UI

**Files:**

- Refactor: `frontend/src/routes/eval/+page.svelte`
- Create components for config, progress, history, report and comparison.
- Test desktop/mobile/error/permission states.

**Sprint done:** upload survives restart, retrieval is owner-scoped, answers cite supporting chunks, unsupported claims fail, evaluation compares real runs.

---

# Sprint 4 — One bounded specialist workflow

**Course concepts:** Day 6 Communication Security, Day 15 Multi-Agent Security, Day 16 Orchestration, Day 17 Self-Healing, Day 18 Specialization, Day 21 Enterprise MAS  
**Competitor patterns:** bounded subagents, isolated context/toolsets, structured results

## Scope

Implement exactly one valuable workflow:

> Primary research agent delegates evidence verification to a constrained verifier child.

Do not build dynamic swarms.

## Task 4.1 — Define child-run contract

**Files:**

- Create: `backend/app/delegation/models.py`
- Create: `backend/app/delegation/service.py`
- Test: `backend/tests/unit/test_delegation_contract.py`

Define child input, allowed evidence, model, tools, policy, token/time budget and structured result.

## Task 4.2 — Isolate child context and permissions

Child receives only selected claims/evidence, not full parent history or secrets. Tool policy is explicit and defaults to deny.

## Task 4.3 — Enforce budget, timeout, cancellation and retries

Budget must be checked before calls. Retry cannot silently approve skipped validation.

## Task 4.4 — Persist parent-child run graph

Use `parent_run_id`; show request, response, status, cost and failure in the Run Ledger.

## Task 4.5 — Measure benefit

Create eval cases comparing:

- single-agent answer;
- answer plus verifier child.

Measure claim support, latency, cost, failures and unnecessary delegation.

**Sprint done:** one child adds measurable value with independent context/policy/budget and full traceability.

---

# Sprint 5 — Real governed MCP integration

**Course concepts:** Day 29 Enterprise Integration  
**Competitor patterns:** MCP server scopes, OAuth, inventory, health, per-tool permission

## Task 5.1 — Replace MCP stubs with client contracts

**Files:**

- Replace: `backend/app/routes/mcp.py`
- Extend: `backend/app/mcp/`
- Create: `backend/app/mcp/client.py`
- Test with an isolated deterministic MCP test server.

## Task 5.2 — Persist server configuration and ownership

Store scope, transport, URL/command reference, auth method, enabled state, health and last error. Never return secrets.

## Task 5.3 — Normalize MCP tools into existing typed tool definitions

Native and MCP tools must produce the same run events and policy decisions.

## Task 5.4 — Apply per-tool approval policy

Connecting a server does not grant all tools. Tool inventory is inspectable and individually enabled.

## Task 5.5 — Build Skills/MCP administration UI

Rename Settings to Skills & Integrations. Show source, version, permissions, schemas, health, context cost and enable/disable state.

**Sprint done:** a real MCP server connects, lists tools, executes one governed tool, logs evidence, rejects unauthorized access and survives restart.

---

# Sprint 6 — Evidence-first Workbench redesign

**Course concepts:** Day 8 Chat, Day 14 Monitoring, Day 26 Operations  
**Competitor patterns:** operational timeline, trust progression, progressive disclosure

## Task 6.1 — Fix global responsive shell

**Files:**

- Refactor: `frontend/src/lib/components/AppShell.svelte`
- Refactor: `frontend/src/lib/components/Workbench.svelte`
- Add: mobile shell Playwright tests.

Desktop: icon rail + optional drawers. Mobile: top bar + sheets. No persistent sidebars at 390 px.

## Task 6.2 — Standardize page shell and design tokens

Create shared page header, state banner, empty state, cards, tables and status semantics. Consolidate Tailwind/global CSS/inline styles.

## Task 6.3 — Make status trustworthy

Every status includes state, scope, source, timestamp and remediation. Never translate `403` to `Down`.

## Task 6.4 — Center navigation on operational objects

Recommended nav:

- Overview
- Runs
- Knowledge
- Evaluations
- Memory
- Skills & MCP
- Settings

## Task 6.5 — Add complete frontend coverage

Vitest reducers/API contracts and Playwright golden paths for login, permissions, run reload, approval, documents, eval, memory, mobile navigation and unauthorized states.

**Sprint done:** mobile and desktop are coherent, fake states are removed, run/eval workflow is primary, and major routes have browser coverage.

---

# Sprint 7 — Deployment, benchmark and interview artifact

**Course concepts:** Day 23 Kubernetes, Day 27 QA, Day 28 DR, Day 30 Production Deployment  
**Advanced concepts:** CI/CD, observability, governance, serving

## Task 7.1 — Prepare one deployment target

Choose one: Azure Container Apps or another explicit target. Do not maintain multiple unverified options.

## Task 7.2 — Deploy real dependencies

Verify application, database, event ledger, vector backend, provider, search, OTEL collector and readiness in the deployed environment.

## Task 7.3 — Run three portfolio scenarios

1. Unsafe file/shell action requiring approval.
2. Tool/provider failure with bounded recovery.
3. Grounded research/RAG with unsupported-claim detection.

## Task 7.4 — Publish benchmark evidence

Report task success, unsafe attempts, approval burden, evidence support, latency, tokens, cost, recovery and workspace contamination.

## Task 7.5 — Verify DR

Backup database, restore into clean environment, prove conversations/runs/documents/approvals, record RTO/RPO.

## Task 7.6 — Produce final artifacts

- Architecture decision record.
- Incident/postmortem.
- 3–5 minute demo.
- Public README with green CI and truthful capability table.
- Interview answer bank.

**Sprint done:** public deployment, reproducible benchmark, verified restore, concise demo and defensible resume claims.

---

# Recommended execution order and stopping rules

| Order | Sprint | Why now | Stop if |
|---:|---|---|---|
| 1 | Baseline | No new work should stack on red gates/false docs | Acceptance is red |
| 2 | Trust layer | Current security gaps make public demo unsafe | Cross-user/escape tests fail |
| 3 | Run Ledger | Core competitive differentiator | Reload loses evidence |
| 4 | Grounded workflow | Deepens course RAG/eval concepts | Sources are not claim-linked |
| 5 | One specialist | Proves MAS understanding without theater | No measurable benefit |
| 6 | MCP | Integrates one real external tool safely | Tool policy is not enforced |
| 7 | UX redesign | Build UI around stable domain objects | Backend state contracts still change |
| 8 | Deploy/prove | Converts implementation into employability evidence | Local golden scenarios are red |

# Features explicitly deferred

- Distributed multi-host agent networks.
- Online model training/fine-tuning.
- High-throughput inference serving.
- Dynamic swarms.
- Scheduled autonomous work.
- Full Kubernetes production operations if Azure Container Apps is selected.
- LSP/code-review IDE features unless Archon deliberately adds a coding-agent scenario.

These remain documented course concepts, not false completeness claims.

# First implementation slice

Start with **Sprint 0 only**:

1. Commit the two audit documents separately.
2. Fix Ruff/format/Svelte warning without behavior changes.
3. Run full acceptance.
4. Correct status documents.
5. Present commits and evidence to Luis.
6. Ask before push.

Do not begin policy, replay, RAG or UI redesign until the baseline is green.
