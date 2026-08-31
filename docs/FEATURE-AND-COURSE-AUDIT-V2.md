# Archon Feature and Course Concept Audit v2

**Date:** 2026-08-25  
**Audited revision:** `27952f4`  
**Purpose:** compare Archon feature-by-feature with Hermes Agent, OpenAI Codex, Claude Code, OpenCode, and the AIAMastery curriculum. This is a capability audit, not a production-readiness audit.

> **Historical snapshot — superseded:** These labels describe revision `27952f4` only. Current status lives in `docs/course/concept-catalog.yaml`, `docs/implementation/CAPABILITY-ACCEPTANCE.yaml`, and the generated Studio manifest. Former `Partial` labels are rendered below as `Historical gap` so they cannot be mistaken for current status.

## Why this v2 exists

The prior `FEATURE_MATRIX.md` is not a defensible audit:

- Its headline says `37/37`, but its competitor table contains **38 rows**.
- It omits OpenCode.
- It treats a route, class, unit test, stub, or configuration flag as full feature completion.
- It marks features as wired when they are not active in the default/live path.
- It compares unlike product categories without explaining scope.
- It collapses implementation depth, runtime evidence, and UI exposure into a single checkmark.

This audit uses six Archon states:

| State | Meaning |
|---|---|
| **Strong** | Meaningful implementation is wired into a live path, tested, and demonstrable |
| **Historical gap** | Useful implementation exists, but integration, safety, persistence, or UX is incomplete |
| **Scaffold** | Interface/route/class exists, but behavior is mock, stub, placeholder, or test-only |
| **Missing** | No meaningful implementation |
| **Configurable** | Code can activate it, but the audited demo/runtime was not configured to use it |
| **Do not copy** | Competitor capability is not useful for Archon's portfolio thesis right now |

Competitor cells mean **officially documented product capability**, not implementation equivalence.

Legend: `●` documented capability, `◐` limited/scope-specific, `—` not a central documented capability in the reviewed official sources.

---

# 1. Competitor feature audit

## 1.1 Runtime and provider layer

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Agent execution loop | ● | ● | ● | ● | **Strong** | Typed loop with explicit stop reasons and budgets |
| Native structured tool calls | ● | ● | ● | ● | **Historical gap** | Native for Anthropic/Foundry; OpenAI/Ollama degrade to text-only adapter |
| Streaming response/events | ● | ● | ● | ● | **Strong** | Live SSE with model/tool/progress events |
| Iteration/tool/time/token budgets | ● | ● | ● | ◐ | **Strong** for primary runtime | Main loop enforces budgets; specialist budget does not |
| Cancellation | ● | ● | ● | ● | **Historical gap** | Browser abort exists; durable server-side cancellation state is incomplete |
| Provider-neutral abstraction | ● | — | ◐ | ● | **Historical gap** | Protocol/factory exists, but provider capability parity is not real |
| Provider fallback | ◐ | — | — | ◐ | **Historical gap** | Fallback exists but loses typed tools and returns text errors |
| Structured output | ● | ● | ● | ● | **Historical gap** | `/json` instruction/prefill; no schema validation or guaranteed parse |
| Prompt caching | ● | ● | ● | ◐ | **Historical gap** | Anthropic cache-control emitted; no hit/savings verification |
| Reflexion/self-correction | ● | ◐ | ● | ◐ | **Strong/limited** | Tool errors return to model; not a general reflection/eval loop |

### Recommendation

Do not add providers. First implement a provider capability matrix and typed fallback that preserves tools, images, usage, structured output, and stop reasons.

## 1.2 Sessions, context, instructions, and memory

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Persistent session history | ● | ● | ● | ● | **Strong** | Conversation messages survive restart |
| Resume a session | ● | ● | ● | ● | **Historical gap** | Messages reload; run evidence does not |
| Fork/branch from prior state | — | ● | ● | ◐ undo/redo | **Missing** | No run fork semantics |
| Context compaction | ● | ● | ● | ● | **Historical gap** | Code exists; coverage and effective live behavior need stronger proof |
| Project instructions | ● skills/memory | ● `AGENTS.md` | ● `CLAUDE.md` | ● `AGENTS.md` | **Historical gap** | Skills are injected; precedence/effective-context view is incomplete |
| Durable user/project memory | ● | ◐ | ● auto-memory | ◐ instructions | **Historical gap/unsafe** | Global plaintext memory is cross-user and lacks provenance |
| Memory provenance/scope/expiry | ◐ | ◐ | ◐ | ◐ | **Missing** | No owner/source/expiry contract for persistent facts |
| Inspect effective context | ● usage/search | ◐ | ● | ◐ | **Historical gap** | Live token estimate exists, but hardcoded Memory UI and incomplete provenance |
| Checkpoint conversation state | ◐ session history | ● fork/history | ● checkpoint/rewind | ● undo/redo | **Scaffold** | Checkpoint manager exists; UI/API response shape is broken and not run-integrated |
| Deterministic read-only replay | — | — | — | — | **Missing** | Messages reload, trajectory disappears |

### Recommendation

Archon's unique opportunity is stronger than competitors: expose exact instructions, memory, evidence, compaction summary, token contribution, and provenance for every turn.

## 1.3 Permissions, approvals, and isolation

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| `allow / ask / deny` policy | ● | ● | ● | ● | **Historical gap** | `requires_approval` boolean, not a full policy engine |
| Pattern/path-specific rules | ● | ● | ● | ● | **Missing** | Workspace read boundary exists, but no general pattern policy |
| Approval scopes: once/session/persistent | ● | ● | ● | ● | **Missing** | Single yes/no decision only |
| Human approval UI | ● | ● | ● | ● | **Historical gap/unsafe** | SSE UI exists; sync path bypasses and ownership is missing |
| Approval audit receipt | ● | ● | ● hooks | ◐ | **Missing** | Decision is transient and not owner-scoped/persisted |
| OS/container sandbox | ◐ Docker | ● | ◐ | — | **False claim** | Host subprocess execution is called sandboxed but is not isolated |
| Worktree/disposable workspace | — | ● | ◐ | — | **Missing** | No per-run filesystem isolation |
| Filesystem scope | ● | ● | ● | ● | **Historical gap** | `read_file` boundary is useful; shell/Python can bypass it |
| Network scope | ● policy | ● sandbox | ● permissions/hooks | ● permissions | **Missing** | No per-run network policy |
| PII controls | — | — | — | — | **Historical gap** | Detector exists, but raw user input is persisted first |
| API auth/ownership | ◐ gateway | ◐ account/workspace | ◐ enterprise | ◐ server | **Historical gap/strong core** | Conversations/artifacts strong; memory/tasks/MCP/approvals have gaps |
| Rate limiting | ◐ gateway | ◐ cloud | ◐ service | ◐ server | **Scaffold** | Class/tests exist; not in live middleware/routes |

### Recommendation

This is the highest-value gap for employment: model Archon after explicit competitor trust ladders, but make policy decisions more observable than competitors.

## 1.4 Tools, skills, MCP, and execution

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Tool registry/contracts | ● | ● | ● | ● | **Strong** | Typed definitions, schemas, execution records |
| Skills/reusable procedures | ● | ● | ● | ● | **Historical gap/strong** | Search/injection/admin exist; provenance/version/permissions are weak |
| Real MCP client/server integration | ● | ● | ● | ● | **Scaffold** | JSON-RPC route exists; tools are explicit stubs and public |
| MCP OAuth/scoped configuration | ● | ● | ● | ● | **Missing** | No real server lifecycle, OAuth, inventory, or per-tool permission |
| Web search | ● | ● | ● | ● | **Strong** | Brave-backed live search observed |
| Claim-level citations/evidence | ◐ | ◐ | ◐ | ◐ | **Historical gap** | Source list exists; live answer verification is not consistently claim-level |
| File read/write | ● | ● | ● | ● | **Historical gap** | Useful boundaries for read/write; approval model is unsafe |
| Terminal/shell | ● | ● | ● | ● | **Historical gap/unsafe** | Real host shell with blocklist, not isolation |
| Python/code execution | ● | ● | ● | ● | **Historical gap/unsafe** | Host Python subprocess, no enforced memory/network/filesystem sandbox |
| Streaming tool progress | ● | ● | ● | ● | **Strong** | SSE tool progress and sources exist |
| Multimodal input | ● | ● | ● | ● | **Historical gap** | Plumbing/tests exist; live E2E provider proof is weak |
| Background jobs | ● cron | ● cloud tasks | ● background agents | ● sessions/tasks | **Scaffold** | Public placeholder task queue; no durable agent work |
| Scheduled automations | ● | ● | ◐ | ◐ | **Missing / defer** | Do not add until isolation, idempotency, approvals, and replay are trustworthy |

## 1.5 Delegation, multi-agent, and orchestration

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Specialist/subagent delegation | ● | ● | ● | ● | **Historical gap** | Four specialist classes and route exist |
| Independent child context | ● | ● | ● | ● | **Missing** | Specialists are serial calls in one request context |
| Child-specific tools/policy/model | ● | ● | ● | ● | **Scaffold** | Classes support some fields; live route does not activate security contracts |
| Bounded concurrency | ● | ● | ● | ◐ | **Missing** | Pipeline is sequential |
| Parent-child trace graph | ◐ | ◐ | ◐ | ◐ | **Missing** | No durable delegation DAG in Workbench |
| Structured child result contract | ● | ● | ● | ● | **Historical gap** | Dict result exists, but no validated schema integrated with primary runtime |
| Worktree isolation per child | — | ● | ◐ | — | **Missing** | No workspace lineage/diff |
| Retry/fallback per specialist | ● | ● | ● | ◐ | **Historical gap** | Retry exists; fallback can silently approve skipped validation |
| Per-agent token/cost budgets | ● | ● | ● | ◐ | **Scaffold** | Tokens recorded after calls; budget check is not enforced |
| Real agentic RAG delegation | — | — | — | — | **Scaffold** | Retriever is another LLM prompt, not RAG/search |

### Recommendation

Do not add dynamic spawning yet. First make one specialist run measurable: independent context, explicit input/output schema, bounded tools, budget, evidence, and comparative eval.

## 1.6 Run evidence, observability, evaluation, and recovery

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Live ordered event timeline | ◐ | ● hooks/events | ● hooks | ● plugins/events | **Strong live / weak durable** | Excellent during run; disappears on reload |
| Durable owner-scoped run ledger | ◐ sessions | ● history | ● sessions/checkpoints | ● sessions | **Historical gap** | Runtime events persisted, but no owner-scoped API/UI trajectory |
| Logs/metrics/correlation IDs | ● | ● | ● | ● | **Strong/historical gap** | Runtime logs and metrics exist; some dashboards are fake or admin-inaccessible |
| OTEL export | — | ◐ | ◐ | ◐ | **Configurable** | Code/tests exist; audited demo has exporter disabled |
| Cost/usage | ● usage | ● usage | ● usage | ● usage | **Historical gap** | Per-response estimate; tracker is recreated per request |
| Quality eval scenarios | — | ● workflows | ◐ hooks/tests | ◐ | **Scaffold/historical gap** | Deterministic research cases exist; UI batch harness uses a mock agent |
| Safety/approval evals | ◐ | ● | ● | ◐ | **Historical gap** | Security probes exist; no integrated scenario comparison |
| A/B model comparison | — | ◐ | ◐ | ◐ | **Scaffold** | Endpoint fabricates responses |
| Checkpoint restore | ◐ | ● worktree/history | ● rewind | ● undo/redo | **Scaffold** | Not connected to run/filesystem/tool side effects |
| Fork and compare runs | — | ● | ● | ◐ | **Missing** | High-value differentiator to build |
| Export/share redacted run | ◐ | ● reports | ◐ share | ● share | **Missing** | Useful later, after secret redaction and access control |
| Verification evidence channels | ◐ | ● tests/diffs | ● hooks/LSP/tests | ● LSP/tools | **Historical gap** | Backend tests exist; Workbench does not unify test/lint/policy/eval evidence |

## 1.7 UX and product surface

| Feature | Hermes | Codex | Claude Code | OpenCode | Archon | Evidence-based verdict |
|---|:---:|:---:|:---:|:---:|---|---|
| Multi-session navigation | ● | ● | ● | ● | **Strong/historical gap** | Conversations exist; run identity is missing |
| Permission inbox/dialog | ● | ● | ● | ● | **Historical gap** | Modal exists only for current SSE run |
| Diff/artifact review | ● staged skills | ● | ● | ● | **Historical gap** | Artifact preview exists; no generalized diff/review workflow |
| Run comparison | — | ◐ | ◐ | ◐ | **Missing** | Essential for evaluation-oriented positioning |
| Mobile/messaging UX | ● | ◐ | ◐ remote | ◐ web | **Broken mobile web** | Global AppShell sidebar compresses chat |
| Health/readiness UX | ◐ | ◐ | ◐ | ◐ | **Misleading** | `403` appears as `Down`; hardcoded Healthy states |
| Context/memory inspector | ● usage/search | ◐ | ● context | ◐ | **Historical gap/fake** | Hardcoded Memory page and incomplete live context provenance |
| Evaluation dashboard | — | ◐ | — | — | **Scaffold** | Two action cards, no real run configuration/history/comparison |
| Keyboard-first operation | ● TUI | ● | ● | ● | **Missing / optional** | Not necessary unless Archon becomes a coding-agent UI |
| Accessibility and responsive tests | ◐ | ● product | ● product | ● product | **Historical gap** | Basic semantics; no broad a11y/visual regression coverage |

---

# 2. Competitor gap summary

## Archon is already competitive in

1. Typed budgeted runtime.
2. Native Anthropic/Foundry tool calls.
3. Live SSE tool/reasoning/source visibility.
4. Persistent authenticated conversations.
5. Broad backend test suite.
6. Built-in research/RAG/eval concepts in one portfolio repository.
7. A Workbench UI rather than terminal-only UX.

## Competitor-derived capabilities worth adding

### Priority A — Core differentiators

1. Durable owner-scoped event ledger and trajectory API.
2. Resume, read-only replay, fork, and compare semantics.
3. Policy engine with `allow / ask / deny`, matching rules, and once/run/session scopes.
4. Approval receipts with owner, policy, risk, scope, decision, and expiry.
5. Real isolated execution: disposable container/worktree, filesystem/network policy, base commit, final diff.
6. Inspectable context construction with instruction/memory/evidence provenance.
7. A real MCP client with server/tool inventory, health, OAuth, and per-tool policy.
8. One bounded child agent with independent context, tools, budget, cancellation, and structured result.
9. Evaluation scenarios that compare runs by success, safety, approvals, cost, latency, and evidence.

### Priority B — Valuable after the core

1. Checkpoint code/conversation separately.
2. Redacted run export/share.
3. Provider capability negotiation and typed fallback.
4. LSP/test/lint evidence integration if Archon adds a coding-agent workflow.
5. Session/run queue with pause/cancel/resume.

### Do not copy now

1. More generic chat tabs.
2. More providers.
3. Large MCP/tool catalogs.
4. Scheduled autonomy.
5. Dynamic multi-agent swarms.
6. Terminal-first UI aesthetics.
7. Raw hidden chain-of-thought.
8. Feature-count parity scores.

---

# 3. AIAMastery 30-Day concept audit

Status columns:

- **Code:** meaningful implementation exists.
- **Live:** the default/product request path genuinely uses the concept.
- **Tests:** tests prove behavior, not merely imports/attributes.
- **UI:** the behavior is visible or operable in Archon.

| Day | Course concept | Code | Live | Tests | UI | Honest verdict / gap |
|---:|---|:---:|:---:|:---:|:---:|---|
| 1 | Enterprise agent architecture | ✅ | ✅ | ✅ | ✅ | **Strong.** Typed runtime, DI, lifecycle, explicit contracts |
| 2 | Secure memory and context | ⚠️ | ⚠️ | ⚠️ | ⚠️ | **Historical gap/unsafe.** Global plaintext cross-user memory; fake inspector metrics; no provenance |
| 3 | Secure tool integration | ✅ | ⚠️ | ✅ | ⚠️ | **Historical gap.** Typed registry is good; sync approval bypass and host execution invalidate secure claim |
| 4 | Resilient web agent | ✅ | ⚠️ | ✅ isolated | ⚠️ | Circuit/rate classes exist; not protecting live provider path |
| 5 | Secure document processing | ✅ | ⚠️ | ✅ mock/unit | ✅ partial | Upload/chunk/query UI exists; metadata volatile, default embeddings mock, PII/storage gaps |
| 6 | Agent communication security | ✅ | ❌ | ✅ unit | ❌ | HMAC/token classes exist; live multi-agent route does not activate them |
| 7 | Security assessment/red teaming | ✅ | ⚠️ | ✅ | ⚠️ | Probes/routes exist; normal demo user cannot use admin flow cleanly |
| 8 | Enterprise chat architecture | ✅ | ✅ | ✅ | ✅ | **Strong.** Authenticated chat, SSE, conversations, tools |
| 9 | Conversation management | ✅ | ✅ messages | ✅ | ✅ partial | Messages persist; complete run trajectory does not survive reload |
| 10 | Secure code analysis/execution | ✅ | ✅ | ✅ unit | ✅ approval modal | **Unsafe approximation.** Host Python/shell is not a sandbox |
| 11 | Multimodal security/classification | ⚠️ | ⚠️ | ⚠️ plumbing | ⚠️ | Image plumbing exists; no persuasive real provider E2E/security workflow |
| 12 | Learning and compliance | ✅ | ❌/⚠️ | ✅ isolated | ⚠️ | Compliance not in chat path; eval/A-B harness relies on heuristics/mocks |
| 13 | Tool orchestration and monitoring | ✅ | ✅ | ✅ | ✅ | **Mostly strong.** Multiple tools/events; task tool itself is placeholder |
| 14 | Multimodal chat and monitoring | ⚠️ | ⚠️ | ⚠️ | ⚠️ | Monitoring strong live; multimodal proof weak |
| 15 | Multi-agent security | ✅ classes | ❌ | ✅ unit | ❌ | Scoped tokens/HMAC not activated by route |
| 16 | Production orchestration | ✅ | ⚠️ separate route | ✅ mock/unit | ❌ primary flow | Four serial LLM calls; no real retrieval/veto/budget enforcement |
| 17 | Self-healing and fallback | ✅ | ⚠️ | ✅ | ⚠️ | Fallback loses native tools; circuit breaker not live; no recovery UI |
| 18 | Agent specialization | ✅ | ⚠️ | ✅ mock/unit | ❌ | Four specialist classes, but no independent contexts/policies/models |
| 19 | Distributed agent networks | ❌ | ❌ | ❌ | ❌ | **Missing/out of scope.** Do not fake it; bounded local delegation is enough for portfolio |
| 20 | Production learning/optimization | ⚠️ | ❌ | ⚠️ | ❌ | Evals exist; no feedback/optimization loop, dataset versioning, or promotion gate |
| 21 | Enterprise multi-agent integration | ⚠️ | ⚠️ separate API | ⚠️ | ❌ | Pipeline demo, not enterprise integration |
| 22 | API gateway and security | ✅ | ⚠️ | ✅ | ⚠️ | Auth/CSRF/headers strong; MCP/tasks/metrics boundaries inconsistent; rate limiting absent |
| 23 | Kubernetes deployment | ✅ manifests | ❌ | ❌ | ❌ | Artifact only; no cluster or deployment smoke |
| 24 | Security and compliance framework | ✅ | ⚠️ | ✅ | ⚠️ | PII/audit/guardrail code exists; raw messages persisted and compliance not enforced globally |
| 25 | Cost optimization | ✅ | ⚠️ | ✅ unit | ✅ per response | Cost estimate exists; tracker resets per request; no durable budget/optimization evidence |
| 26 | Observability and operations | ✅ | ⚠️ configurable | ✅ | ⚠️ | Logs/events/metrics useful; OTEL disabled in audited demo; replay absent; fake health UI |
| 27 | Testing and QA | ✅ | ⚠️ | ✅ 466 | ⚠️ | Strong backend quantity/coverage; Ruff red, CI red, only 4 frontend unit + 2 E2E |
| 28 | Disaster recovery | ⚠️ docs/manifests | ❌ | ❌ | ❌ | No proven backup/restore/RTO/RPO exercise |
| 29 | Enterprise/legacy integration | ⚠️ | ⚠️ | ✅ stubs/adapters | ⚠️ | Provider adapters exist; MCP is public stub; no real legacy integration contract |
| 30 | Production deployment | ✅ Docker/Helm | ❌ cloud | ✅ mock Docker smoke | ❌ public demo | Container starts with mock provider; no verified cloud environment |

## 30-Day score by evidence depth

| Depth | Days | Count |
|---|---|---:|
| **Strong live implementation** | 1, 8, 13 | **3** |
| **Meaningful but partial live implementation** | 2, 3, 4, 5, 7, 9, 10, 11, 14, 17, 22, 24, 25, 26, 27, 29 | **16** |
| **Scaffold/demo/isolated concept** | 6, 12, 15, 16, 18, 20, 21, 23, 28, 30 | **10** |
| **Missing/deferred** | 19 | **1** |

This is not `26/30 complete`. A defensible statement is:

> Archon contains code or an artifact for 29 of 30 course days, but only 3 days are currently demonstrated as deep, end-to-end product capabilities. Sixteen are meaningful partial implementations and ten are scaffolds or deployment artifacts.

That is still a strong learning portfolio; it is simply a different claim.

---

# 4. Advanced Architectures concept audit

| Concept group | Code | Live | Tests | Honest status |
|---|:---:|:---:|:---:|---|
| Provider protocols and adapters | ✅ | ✅ | ✅ | **Strong for Anthropic/Foundry; partial across all providers** |
| Context/state management | ✅ | ✅ | ✅ | **Historical gap:** messages strong; memory provenance/compaction evidence incomplete |
| Tool schemas and execution loop | ✅ | ✅ | ✅ | **Strong core** |
| RAG chunk/embed/retrieve | ✅ | ⚠️ | ✅ mock/unit | **Historical gap:** default mock/in-memory; pseudo-pgvector path incompatible |
| RAG evaluation | ✅ | ⚠️ offline | ✅ | **Historical gap:** deterministic research fixtures useful; live claim verification incomplete |
| ReAct planning/budgets | ✅ | ✅ | ✅ | **Strong typed runtime** |
| Reflexion/error recovery | ✅ | ✅ | ✅ | **Historical gap/strong:** tool-error feedback, not full learning/reflection |
| Agentic RAG | ✅ classes | ❌ genuine retrieval | ✅ mock/unit | **Scaffold:** retriever is another LLM prompt |
| Multi-agent orchestration | ✅ | ⚠️ separate route | ✅ mock/unit | **Prototype:** serial calls, no isolation/security/budget enforcement |
| Coordination economics | ✅ tracker classes | ❌ | ⚠️ | **Scaffold:** no durable per-agent cost/benefit evaluation |
| Subagent architecture | ✅ specialist classes | ❌ independent child | ⚠️ | **Scaffold:** no child context/toolset/workspace lifecycle |
| Observability | ✅ | ⚠️ | ✅ | **Historical gap:** live SSE/logs strong; OTEL/replay not proven in demo |
| Guardrails/governance | ✅ | ⚠️ | ✅ | **Historical gap:** not consistently before persistence/tool execution |
| Evaluation and A/B | ✅ | ⚠️ mocks | ✅ | **Scaffold/partial:** UI harness does not evaluate real runs |
| MLOps/CI/CD | ✅ files | ❌ deployed | ⚠️ local | **Historical gap artifact:** local Docker; remote CI red; no deployment |
| High-throughput serving | ❌ | ❌ | ❌ | **Missing/defer** |
| Drift/data versioning | ❌ | ❌ | ❌ | **Missing; add only if tied to real eval datasets** |
| Fine-tuning/vertical adaptation | ❌ | ❌ | ❌ | **Missing/defer** |
| Disaster recovery | ⚠️ docs | ❌ | ❌ | **Artifact only** |

---

# 5. What is actually missing from Archon

## Missing because competitors demonstrate it well

1. Explicit policy hierarchy and effective permission view.
2. Approval lifetimes and persisted receipts.
3. Real execution isolation with visible boundaries.
4. Durable run timeline after reload.
5. Fork/compare/checkpoint semantics.
6. Context and memory provenance.
7. Real MCP client lifecycle and per-tool policy.
8. Independent bounded subagent execution.
9. Run-centric eval comparison.
10. Redacted share/export.
11. Provider capability negotiation.
12. Role-aware UI and trustworthy operational states.

## Missing because the course concepts are only superficial

1. User-scoped encrypted memory path.
2. Live rate limiter and provider circuit breaker.
3. Real document persistence and vector backend.
4. PII controls before persistence.
5. Enforced multi-agent security.
6. Real learning/optimization loop.
7. Durable cost budgets.
8. Real OTEL demonstration.
9. Verified DR exercise.
10. Cloud deployment and CI/CD proof.

## Present but should be renamed honestly

| Current claim | Honest name |
|---|---|
| Secure sandbox | Approval-gated host subprocess prototype |
| pgvector store | PostgreSQL JSON-vector store with Python similarity |
| Encrypted persistent memory | Detached encrypted-memory prototype; live memory remains plaintext |
| Production multi-agent | Sequential specialist pipeline prototype |
| MCP integration | MCP-shaped JSON-RPC stub API |
| Background tasks | In-process placeholder task queue |
| A/B testing | Mock response comparison scaffold |
| Eval harness | Deterministic mock/heuristic evaluator scaffold |
| Durable replay | Live event stream plus event persistence without trajectory API/UI |
| 37/37 parity | 38-row feature inventory with mixed implementation depth |

---

# 6. Feature roadmap driven by competitors and course gaps

## Track A — Runtime trust and safety

1. Shared sync/SSE runtime factory.
2. Fail-closed approvals.
3. Owner-scoped approval records.
4. `allow / ask / deny` policies with pattern matching and scope.
5. Container/worktree execution boundary.
6. PII before persistence.
7. User/project memory provenance and real encryption.
8. Live rate limiting and circuit breaker.

## Track B — Workbench differentiator

1. Durable run ledger.
2. Trajectory API.
3. Reload with tools/evidence/context/evals/cost/policy intact.
4. Read-only replay.
5. Fork from checkpoint.
6. Compare runs.
7. Export redacted evidence report.

## Track C — One grounded workflow

1. Persistent document model and ownership.
2. Real vector backend or honest rename.
3. Real embeddings.
4. Retrieved-chunk inspection.
5. Claim-level citations.
6. Real eval cases against recorded runs.
7. Versioned datasets and regression gate.

## Track D — One real bounded subagent

1. Child-specific context.
2. Child-specific tools/policy/model.
3. Explicit input/output schema.
4. Budget and timeout enforcement.
5. Cancellation.
6. Parent-child trace.
7. Measurable comparison against single-agent baseline.

## Track E — Product and portfolio proof

1. Redesign mobile shell.
2. Make Runs and Evaluations primary.
3. Remove fake health/memory states.
4. Add route/role-aware navigation.
5. Expand frontend tests.
6. Deploy real environment.
7. Publish three reliability scenarios and demo.

---

# 7. Recommended positioning for employment

Do not claim that Archon beats or matches Hermes, Codex, Claude Code, and OpenCode feature for feature.

Use this instead:

> Archon consolidates the most important reliability patterns from modern agent harnesses into a visual learning workbench: typed model/tool contracts, bounded execution, live evidence, approvals, context inspection, grounded evaluation, and provider portability. The project deliberately exposes which capabilities are production-wired versus experimental course prototypes.

The strongest future differentiator is not another tool or agent. It is an **evidence-first reliability workflow** that competitors expose only partially:

> run → policy → approval → tool → evidence → evaluation → checkpoint → fork → compare.

---

# 8. Source basis

## Official competitor sources

- Hermes security, memory, delegation, MCP, tools: https://hermes-agent.nousresearch.com/docs/
- Codex sandboxing, approvals, worktrees, subagents, MCP: https://developers.openai.com/codex/
- Claude Code permissions, hooks, subagents, checkpoints, MCP: https://code.claude.com/docs/en/
- OpenCode permissions, agents, rules, MCP, LSP: https://opencode.ai/docs/

## Course sources

- Private AIAMastery Day 1–30 repositories under `ai-agent-mastery-p/day1` through `day30`.
- Archon `docs/PLAN.md` course mapping.
- Archon source and tests at revision `27952f4`.

No paid lesson text is reproduced here; this document contains only a derived concept/status index.
