# Archon GPT-5.6 Re-Audit

**Date:** 2026-08-25  
**Audited revision:** `27952f4` on local `main`  
**Remote state during audit:** local `main` was 54 commits ahead of `origin/main`  
**Scope:** original plan, backend, frontend, visual product design, tests/CI, and current official patterns from Hermes Agent, OpenAI Codex, Claude Code, and OpenCode.

## Executive verdict

Archon is a **strong agent-engineering portfolio prototype** with a genuinely valuable core: a typed, budgeted runtime; native Anthropic/Foundry tool calling; direct SSE event streaming; persistent authentication and conversation ownership; and broad deterministic backend coverage.

It is **not production-ready**, is not at credible `37/37 competitor parity`, and is not fully implemented/wired/tested. The newer implementation expanded topic coverage faster than it deepened the live product. Several headline capabilities are placeholders, mocks, configurable-but-inactive integrations, or unsafe approximations.

Recommended positioning:

> Archon is a local-first Agent Reliability Workbench prototype that makes model turns, tools, evidence, policy decisions, context, costs, and failures inspectable. Its strongest implemented core is the typed Anthropic/Foundry runtime and live SSE workbench; several RAG, memory, MCP, multi-agent, evaluation, and deployment capabilities remain experimental.

Do not market it as a production platform, secure sandbox, complete MCP implementation, encrypted multi-tenant memory system, or competitor-equivalent coding agent.

## Verification results

| Gate | Fresh result | Interpretation |
|---|---:|---|
| Backend tests | **466 passed, 0 skipped** | Real improvement from the earlier 371-test baseline |
| Backend coverage | **81.84%** | Strong aggregate coverage; critical integrations remain thinner |
| Ruff lint | **Failed: 50 errors** | Acceptance gate is not green |
| Ruff formatting | **16 files need formatting** | Current HEAD is not release-clean |
| Bandit | 0 medium/high findings | Useful static-security evidence; not runtime security proof |
| Strict Mypy | **395 errors** in the full app | Typed runtime does not imply typed backend |
| Svelte check | 0 errors, 1 warning | Frontend compiles; one dead CSS selector |
| Frontend unit tests | **4 tests** across 2 files | Far too shallow for the expanded UI |
| Playwright | **2 scenarios** | Chat desktop/mobile only; secondary routes and new shell are untested |
| Frontend build | Pass | Production bundle builds |
| NPM production audit | 0 vulnerabilities | Positive dependency evidence |
| Docker build and `/healthz` | Pass | Container starts with default `mock-model/mock` configuration |
| Remote CI | Last 10 runs failed; new work not pushed | No remote evidence for the current 54 local commits |

The `466 tests` claim is correct. The claims `all gates green`, `zero dead code`, `37/37 parity`, and `every feature implemented → wired → tested → verified in UI` are not.

## What is genuinely strong

1. **Typed, budgeted agent runtime**
   - Explicit stop reasons, iteration/tool/token/time budgets, canonical duplicate-tool blocking, bounded result context, and final synthesis.
   - `backend/app/runtime/engine.py`

2. **Native Anthropic and Foundry tool normalization**
   - Real tool schemas and `tool_use` conversion rather than JSON extracted from prose.
   - `backend/app/runtime/anthropic.py`

3. **Direct SSE event flow**
   - Per-request event sink; no shared-method monkey patching in the live stream path.
   - `backend/app/routes/stream.py`

4. **Persistent identity and conversation ownership**
   - Scrypt passwords, JWT/API-key support, hashed API keys, persistent users and conversations, owner-scoped conversation access.

5. **Useful runtime evidence**
   - Tools, iterations, stop reason, usage, latency, cost estimate, source list, and logs are visible during a live run.

6. **Broad deterministic backend suite**
   - 466 tests and 81.84% aggregate coverage are meaningful, even though some newer tests prove only scaffolding.

7. **Solid visual foundation**
   - Coherent dark palette, readable typography, consistent icon family, responsive intent, and a professional technical aesthetic.

## Critical backend findings

### P0 — Approval bypass and cross-user approval

Dangerous tools are marked `requires_approval`, but synchronous `/api/chat` constructs `AgentRuntime` without an approval hook. Those tools can execute without HITL on that route. SSE adds approval, but pending decisions are module globals keyed only by tool-call ID; `/approve/{id}` authenticates a user without verifying ownership.

Evidence:

- Approval-required registrations: `backend/app/routes/chat.py:124-198`
- Sync runtime without hook: `backend/app/routes/chat.py:315-331`
- Runtime checks only when a hook exists: `backend/app/runtime/engine.py:167-174`
- Global SSE approval state: `backend/app/routes/stream.py:31-35,120-131`
- Owner-unaware approval endpoint: `backend/app/routes/stream.py:279-290`

### P0 — Code and terminal execution are not sandboxes

`execute_sandboxed` runs host Python from a temp file with the server environment. `max_memory_mb` is unused. There is no process/container isolation, network boundary, seccomp, namespace, capability drop, or filesystem boundary. The terminal uses `create_subprocess_shell` with the process environment and a bypassable pattern blocklist.

Call these **approval-gated host execution tools**, not secure sandboxes.

### P0 — Persistent memory is global plaintext across users

`PersistentMemory` writes one `archon_memory.json` file and injects it into every user's context. The observed file existed with mode `0644`. The memory tool has no user scope or provenance. The encrypted store is merely attached to the singleton; live add/remove/replace/list continue using plaintext `_entries`.

Evidence:

- Plaintext store/singleton: `backend/app/memory/persistent.py:19-46,188-209`
- Global prompt injection: `backend/app/runtime/context.py:41-45`
- User-unaware tool: `backend/app/tools/memory_tools.py:14-47`
- Misleading wiring test: `backend/tests/unit/test_wiring_gaps.py:28-39`

### P0 — PII is stored before redaction

Both sync and SSE routes store `body.message` directly. `PIIDetector` exists but is not applied in these persistence calls.

- `backend/app/routes/chat.py:333-334`
- `backend/app/routes/stream.py:209-210`

### P1 — MCP and task APIs are public scaffolding

Observed without authentication:

```text
GET  /api/mcp/tools        200
POST /api/mcp/request      200
GET  /api/tasks            200
POST /api/tasks/submit     200
GET  /metrics              200
```

MCP tools explicitly return `stub — not yet implemented`. Background submission ignores the requested command and sleeps for 0.1 seconds. The task queue is process-local, shared, owner-unaware, and non-durable.

### P1 — Durable RAG is broken and not pgvector

- Default embedding provider is mock and vector store is in-memory.
- `PgVectorStore` stores embeddings as JSON text and computes cosine in Python; it does not use PostgreSQL `VECTOR` or HNSW.
- The route passes `document_ids`, which the PostgreSQL store does not accept.
- Ownership metadata is a process-local `_document_registry` dict and disappears after restart.

This is an educational RAG implementation, not durable production RAG.

### P1 — Rate limiter and circuit breakers are not on the live request path

The implementations and tests exist, but repository-wide live wiring is absent. Circuit breakers are displayed by an admin registry rather than wrapping live LLM adapters. Rate limiter references are test/demo-only.

### P1 — Multi-agent is sequential prompt orchestration, not secure agentic RAG

The route calls Planner, Retriever, Validator, and Synthesizer, but:

- Retriever does not call RAG/search.
- Validator output is not parsed or enforced as a veto.
- The route does not enable `channel_secret`, specialist tokens, or HMAC.
- Per-agent budget is recorded after calls; `can_spend()` is not enforced.
- The same LLM performs four serial prompt calls.
- Results are not integrated into the primary run timeline, persistence, ownership, or eval pipeline.

### P1 — Evaluation and A/B testing are façade-level

- Auto-evals are keyword/PII heuristics.
- Faithfulness reads `tc.get("output")`, while runtime tool records use `result`; evidence context can be empty.
- Scores are emitted after `done`, stored by the frontend, and hidden from the UI.
- Batch harness uses a mock echo agent.
- A/B testing fabricates mock responses rather than invoking selected models.
- `CostTracker()` is recreated per request, so user/day/conversation aggregation is not durable.

### P2 — Provider neutrality is partial

Native typed tools are real for Anthropic/Foundry. OpenAI and Ollama expose legacy `chat()` and are adapted through `TextOnlyProvider`, which drops tool definitions, images, structured output, and native usage. Fallback also uses the legacy text interface, so tools disappear during failover.

## Frontend architecture and product findings

### What works

- Real authenticated chat and SSE response flow.
- Conversation URLs and message persistence.
- Source/tool/skill/reasoning rendering during a live run.
- DOMPurify-based Markdown sanitation.
- Desktop components have a coherent visual vocabulary.
- A real calculator run was observed: 2 iterations, 1 tool, 8.9 s, 6,850 tokens, and a displayed cost.

### P0 — Mobile shell is broken

The new global `AppShell` sidebar remains visible on a 390 px viewport. The Workbench also owns a conversation sidebar and an inspector, producing a compressed four-surface layout. Existing Playwright mobile coverage tests only the inner conversation drawer; it does not assert the global shell.

Recommended structure:

- Desktop: 56–64 px global icon rail, optional conversation drawer, primary response, collapsible inspector.
- Mobile: top bar, bottom composer, nav sheet, conversations sheet, inspector bottom sheet. No persistent sidebars.

### P0 — Operational state is misleading

- Dashboard maps `403`/missing fields to `Down`, `0m`, and zero services.
- Demo user can see admin-only navigation but cannot use it.
- Inspector always says LLM provider and vector database are `Healthy` without a live health result.
- Memory page presents hardcoded `1840 / 4096` context usage and architectural tiers as operational state.
- Login says `100% local · Ollama · Zero cloud dependencies`, while the active chat says Foundry/Claude.

Every system state should distinguish `not configured`, `loading`, `healthy`, `degraded`, `down`, `unknown`, `stale`, and `permission denied`, with source and timestamp.

### P1 — Run evidence disappears after reload

Reloading `/chat/{id}` restores user/assistant messages but loses reasoning, tools, latency, tokens, cost, iterations, sources, evals, and stop reason. The Inspector resets to zero while retaining decorative health labels.

Archon's central differentiator requires durable owner-scoped run-event APIs and read-only trajectory replay. Do not call transcript resubmission deterministic replay.

### P1 — Secondary pages are broad but shallow

- Dashboard is sparse and inaccessible to the demo user.
- Documents lacks durable indexing state and post-restart metadata.
- Evaluation exposes two hardcoded action cards without run configuration/history/comparison.
- Memory shows fictitious metrics and a broken/blank checkpoints state.
- Settings is actually a Skills screen.

### P1 — Frontend test coverage is far below product surface

Only four unit tests and two Playwright scenarios exist. There are no frontend tests for login, Dashboard, Documents, Eval, Memory, Settings, approvals, citations, route permissions, run reload, or the global mobile shell.

### P2 — Component/design-system debt

- `Workbench.svelte` remains roughly 510 lines.
- Secondary pages are 200–434-line components.
- `app.css` is roughly 1,369 lines while pages also use Tailwind utilities and inline styles.
- Two sidebar systems overlap.
- Page widths, headings, card density, and semantic colors vary.
- The page title is empty in the browser.

## Visual redesign direction

The current aesthetic is a usable base, not the main problem. The largest UX issue is **trustworthiness of state**.

### Recommended information architecture

1. **Overview** — attention queue, health with source/freshness, recent regressions.
2. **Runs** — durable run list, timeline, tools, policy, evidence, context, cost, tests.
3. **Knowledge** — documents, indexing states, retrieval inspection.
4. **Evaluations** — configure run, progress, report, compare, rerun.
5. **Memory** — scoped entries, provenance, effective context, retention/delete.
6. **Skills / MCP** — sources, versions, permissions, enabled tools, health.
7. **Settings** — providers, environments, policy presets, security.

### Golden UX flow

> Select a scenario → execute a supervised run → approve/deny a sensitive action → inspect evidence/context/policy → observe a failure → fork from checkpoint → rerun → compare eval and cost.

That one complete flow is a stronger hiring artifact than five shallow dashboards.

## Competitor lessons

### Hermes Agent

Adopt:

- Separate durable user/project memory, session history, compaction summary, and retrieved evidence.
- Staged durable modifications with diff review.
- Once/session/deny approval scopes and fail-closed behavior.
- Restricted child context/toolsets with structured return contracts.

Do not copy:

- Shared persistent-container state as an isolation claim.
- Tool count or messaging-channel count as a portfolio metric.

Official references:

- https://hermes-agent.nousresearch.com/docs/user-guide/security
- https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation
- https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp

### OpenAI Codex

Adopt:

- Separate sandbox mode from approval policy.
- Per-run worktrees/disposable workspaces and visible base commit/final diff.
- Resume versus fork semantics.
- Parallel bounded children with isolated workspaces.

Official references:

- https://developers.openai.com/codex/agent-approvals-security
- https://developers.openai.com/codex/concepts/sandboxing
- https://developers.openai.com/codex/app/worktrees
- https://developers.openai.com/codex/subagents
- https://developers.openai.com/codex/mcp

### Claude Code

Adopt:

- Named trust presets backed by explicit permission rules.
- Deterministic lifecycle hooks before/after tools.
- Scoped subagents with independent context/tool/model/permission policy.
- Checkpoint semantics that state exactly what can and cannot be restored.

Official references:

- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/sub-agents
- https://code.claude.com/docs/en/checkpointing
- https://code.claude.com/docs/en/mcp

### OpenCode

Adopt:

- Pattern-based `allow / ask / deny` permissions.
- Provider capability checks instead of pretending every provider is equivalent.
- Explicit project instruction precedence and provenance.
- LSP diagnostics as one evidence channel alongside lint/tests/runtime evals.

Official references:

- https://opencode.ai/docs/permissions/
- https://opencode.ai/docs/agents/
- https://opencode.ai/docs/rules/
- https://opencode.ai/docs/mcp-servers/
- https://opencode.ai/docs/lsp/

## What Archon should not build next

- Another framework integration.
- More providers before typed tool parity is real.
- More dashboard pages.
- More MCP tools while MCP remains a public stub.
- More specialist agents without isolation, budgets, provenance, and measurable benefit.
- Scheduled autonomy before approvals, idempotency, isolation, and rollback are trustworthy.
- Raw chain-of-thought as the main observability story.
- A larger feature-parity score.

## Prioritized employability roadmap

### Phase 0 — Restore truth and release hygiene

1. Fix 50 Ruff errors and 16 formatting failures.
2. Make current local CI fully green, then push and obtain a green GitHub run.
3. Replace `EXECUTIVE_SUMMARY.md`, `FEATURE_MATRIX.md`, README, and stale status matrix with one evidence table.
4. Ban claims based only on source-file presence or unit tests.

**Done:** clean tree; local acceptance pass; remote CI pass; exact test/coverage numbers; no contradictory docs.

### Phase 1 — Close critical security boundaries

1. Unify sync/SSE behind one runtime factory and fail closed when approval is unavailable.
2. Persist owner-scoped approvals and verify approver/run/tool ownership.
3. Remove or isolate host terminal/code execution in a disposable container/worktree.
4. Scope memory by user/project; add provenance; encrypt the actual persistence path; use `0600`.
5. Redact/classify PII before storage.
6. Authenticate and owner-scope MCP/tasks; wire rate limiting to live routes.

**Done:** cross-user attack tests; approval timeout/restart tests; sandbox escape tests; PII-at-rest test; owner-scoped memory tests.

### Phase 2 — Deliver the differentiating golden path

1. Persist immutable owner-scoped run events.
2. Add run list and trajectory API.
3. Restore tools, usage, policy, context, evidence, eval, cost, and stop reason after reload.
4. Support read-only replay and fork-from-checkpoint; do not re-execute tools during replay.
5. Show exact context provenance and token contribution.

**Done:** restart/reload/deep-link tests; cross-user run denial; deterministic event ordering; before/after run comparison.

### Phase 3 — Make one real grounded workflow

1. Replace pseudo-pgvector with either real pgvector or explicitly named durable JSON-vector storage.
2. Persist document metadata and ownership.
3. Use real embeddings in a reproducible environment.
4. Integrate citation verification with live research/RAG.
5. Replace mock A/B/eval endpoints with real recorded runs and versioned fixtures.

**Done:** document survives restart; cited answer identifies supporting chunks; unsupported claim fails eval; baseline comparison is reproducible.

### Phase 4 — Redesign the product around evidence

1. Fix the global mobile shell first.
2. Consolidate global navigation, conversation history, and inspector.
3. Remove fake health states and hardcoded memory metrics.
4. Make Evaluations the primary proof surface.
5. Add route/role-aware navigation and permission-denied states.
6. Add frontend tests for every major route and golden flow.

**Done:** desktop/mobile screenshots; keyboard/a11y checks; visual-regression tests; no overflow; populated/error/stale/unauthorized states.

### Phase 5 — Prove deployment and portfolio value

1. Deploy one real environment.
2. Verify Foundry, Brave, database, event persistence, OTEL, and health/readiness there.
3. Publish three eval scenarios: tool failure recovery, unsafe-action approval, grounded research.
4. Record a 3–5 minute demo.
5. Write one architecture decision and one incident/postmortem.

**Done:** public URL, green CI, deployment smoke, benchmark report, concise demo, truthful README.

## Suggested interview story

Lead with:

- why text-parsed ReAct and monkey-patched streaming were replaced;
- how native tools are normalized across Anthropic/Foundry;
- how budgets, duplicate blocking, stop reasons, and final synthesis prevent empty failures;
- how owner-scoped persistence/auth was added;
- what the fresh audit found and how evidence-driven status prevented feature-count theater.

Do not lead with 59 endpoints, 466 tests, 37/37 parity, or 26/30 course days.

## Final assessment

| Dimension | Assessment |
|---|---|
| Typed runtime core | Strong |
| Anthropic/Foundry live path | Strong |
| Conversation auth/ownership | Good |
| Test quantity/aggregate coverage | Strong |
| Integrated release hygiene | Weak at current HEAD |
| Multi-tenant memory/security | Critical gaps |
| Sandbox/approvals | Critical gaps |
| Durable RAG | Prototype |
| MCP/tasks/multi-agent | Scaffolding/demo |
| Evaluation depth | Prototype |
| Frontend visual foundation | Good base |
| Frontend product coherence/mobile | Needs redesign |
| Deployment evidence | Missing |
| Current portfolio credibility | Promising if claims are corrected |

The correct next move is **not another feature sprint**. It is to restore a green, truthful baseline and complete one evidence-rich reliability workflow end to end.
