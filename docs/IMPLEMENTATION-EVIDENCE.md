# Archon Implementation Evidence

**Canonical status source**

- **Current verified local baseline:** `475cf07` on local `main` (2026-08-26)
- **Baseline repository state:** clean after acceptance; local `main` was 119 commits ahead of `origin/main`
- **Historical capability audit snapshot:** `27952f4` on local `main` (2026-08-25)
- **Remote status:** the current baseline has not been pushed or rerun in remote CI; the last known remote runs failed

This is the sole canonical mutable source for implementation status and release-gate metrics. Other summaries must link here rather than maintain competing scorecards. The capability matrix and detailed findings come primarily from the historical audit snapshot; rows changed by the integrated Sprint 1 and Sprint 2 work are refreshed below. See [Feature and Course Concept Audit v2](FEATURE-AND-COURSE-AUDIT-V2.md) and the [GPT-5.6 Re-Audit](ARCHON-GPT56-REAUDIT-2026-08-25.md).

## How to read the matrix

A capability is evaluated on six independent evidence dimensions:

- **Exists:** meaningful code or an artifact is present. A stub, mock, manifest, or configuration flag is identified in Notes.
- **Wired:** a product/API path invokes it. `Partial` includes separate, optional, unsafe, or non-default paths.
- **Tested:** automated tests exercise relevant behavior. This does not imply live integration or production readiness.
- **Observed:** the audit directly exercised the behavior, rather than inferring it from code or tests.
- **UI:** a user can see or operate it in the current product. `Partial` includes misleading, transient, admin-only, or incomplete surfaces.
- **Deployed:** verified in a non-local environment. A local process, Docker image, manifest, or successful build is not a deployment.

Legend: **Yes** = supported by evidence; **Partial** = limited or qualified evidence; **No** = absent or contradicted; **N/A** = not applicable. None of these columns alone means production-ready.

## Current verified local quality-gate evidence

These results were freshly observed on local `main` at `475cf07`. They establish a green **local integrated Sprint 1 and Sprint 2 acceptance baseline**, not remote CI success, deployment, production readiness, or evidence from a real-provider environment. Acceptance used the local mock provider. It covered durable approvals; mandatory encrypted owner/project-scoped memory; persistence and log redaction; per-user/IP rate limiting and shared circuit-breaker state; optional, fail-closed Docker-only execution with a real local containment smoke; and the durable owner-scoped run ledger with replay, fork, and compare UI.

| Gate | Fresh result | Status |
|---|---|---|
| Ruff check | No violations | Pass |
| Ruff format check | 199 files already formatted | Pass |
| Bandit scan | 0 medium, 0 high; `-ll` gate passed | Pass; static scan only |
| Backend tests | 896 passed | Pass |
| Backend coverage | 85.73% | Measured; aggregate coverage is not integration proof |
| Svelte check | 0 errors, 0 warnings | Pass |
| Frontend unit tests | 6 Vitest tests across 3 files | Pass; narrow coverage |
| Frontend production build | Build completed | Pass |
| Browser tests | 9 Playwright scenarios | Pass locally |
| Docker smoke | Sandbox containment and backend `/healthz` smokes passed | Pass locally with mock provider; not a deployment |
| Repository diff check | Clean | Pass |
| Remote CI | Not rerun; last known remote runs failed | **No green remote evidence** |

**Local release-gate verdict:** Integrated Sprint 1 and Sprint 2 acceptance passed at `475cf07`. The branch was clean after the run. No push or remote CI rerun occurred.

## Historical audit snapshot

Except for rows explicitly refreshed for integrated Sprint 1 and Sprint 2, the capability matrix below remains the audit judgment recorded at `27952f4`, when Ruff reported 50 lint errors, Ruff format reported 16 files requiring formatting, strict Mypy reported 395 errors, and Svelte check reported one warning. Later local gate improvements do not by themselves prove that a product capability became more complete, better wired, deployed, or production-ready.

## Capability evidence matrix

| Capability | Exists | Wired | Tested | Observed | UI | Deployed | Evidence and limits |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| Typed, budgeted agent runtime | Yes | Yes | Yes | Yes | Yes | No | Default chat/SSE runtime has explicit stop reasons and iteration, tool, token, and time budgets. |
| Native structured tool calls | Yes | Partial | Yes | Yes | Yes | No | Native Anthropic/Foundry normalization is strong; OpenAI/Ollama use a text-only adapter. |
| Live SSE run events | Yes | Yes | Yes | Yes | Yes | No | Model, tool, progress, source, and terminal events are visible during a run. |
| Provider fallback and portability | Yes | Partial | Yes | No | Partial | No | Abstractions exist, but fallback drops typed tools and provider capabilities are not equivalent. |
| Tool registry and typed contracts | Yes | Yes | Yes | Yes | Yes | No | Strong core; individual tool safety and depth vary. |
| Skills and instruction injection | Yes | Yes | Yes | Partial | Partial | No | Search/injection exist; provenance, precedence, versioning, and permissions remain incomplete. |
| Persistent authentication and conversations | Yes | Yes | Yes | Yes | Yes | No | Users and messages persist; conversation ownership is a strong path. |
| Complete run resume/replay | Partial | Yes | Yes | Yes | Yes | No | The owner-scoped UI provides durable read-only trajectory replay, fork-from-event, and side-by-side run comparison. This is not exact executable resume: replay intentionally omits raw prompts/tool payloads and fork checkpoints record `workspace_restoration: none`. |
| Durable owner-scoped run ledger | Yes | Yes | Yes | Yes | Yes | No | Sync and SSE runs persist ordered, allow-listed/redacted events and terminal metadata behind owner-scoped APIs; local tests and browser acceptance exercised replay, fork lineage, and compare. Retention prunes whole terminal runs rather than partial trajectories. |
| Context compaction and inspection | Yes | Partial | Partial | Partial | Partial | No | Useful plumbing exists; effective-context provenance and some displayed metrics are incomplete or hardcoded. |
| Persistent memory | Yes | Yes | Yes | Yes | Partial | No | The live durable path encrypts facts at rest and scopes reads/writes to authenticated owner plus project. Startup requires one canonical valid master key when persistence is enabled and fails closed on missing, conflicting, or invalid key material. UI coverage remains limited. |
| API authorization and ownership | Yes | Partial | Yes | Yes | Partial | No | Conversations, artifacts, durable approvals, memory, and run-ledger APIs enforce owner scope; memory adds project scope. Other areas, including tasks and MCP, retain historical ownership gaps. |
| Policy domain and deterministic matching | Yes | Yes | Yes | Yes | No | No | The shared runtime factory applies deterministic policy matching on both sync and SSE chat routes. `Observed` means those local integration event paths were exercised with a mock model; it is not real-provider or deployment evidence. |
| Tool policy metadata and classification | Yes | Yes | Yes | Yes | No | No | The live tool registry carries validated risk/resource metadata and builds fail-closed policy requests for registered calls. Local sync/SSE integration exercised this bridge through the shared runtime; `Observed` remains local mock-model evidence, not deployed proof. |
| Runtime policy enforcement | Yes | Yes | Yes | Yes | No | No | Sync and SSE routes instantiate the shared policy-aware runtime. Local integration tests observed safe execution, sync fail-closed behavior, and SSE policy/approval/denial events; allow-listed policy events now enter the durable run ledger. This remains local mock-provider evidence, not deployed proof. |
| Filesystem workspace containment | Yes | Yes | Yes | No | No | No | Live read, write, and list tools enforce workspace-relative descriptor-based traversal and reject traversal, symlink, hard-link, and unsafe target cases. Acceptance established automated coverage, not a user-visible decision trace or deployment. |
| Approval policy and human approval | Yes | Yes | Yes | Yes | Partial | No | Live approvals use durable owner/run/tool-call-bound requests and atomic terminal decisions with persisted expiry/cancellation receipts; approved decisions are single-use and sync still fails closed without an authorizer. The UI supports the live decision flow, but this remains local evidence rather than deployed proof. |
| File read/write tools | Yes | Yes | Yes | Partial | Yes | No | Host-side file tools use workspace-relative descriptor traversal and reject traversal, links, and unsafe targets. They are not containerized, and acceptance did not add a user-visible containment trace. |
| Python/code execution | Yes | Yes | Yes | Yes | Yes | No | When explicitly enabled, execution is Docker-only with an immutable image reference, no network or host mounts, read-only root, dropped capabilities, resource/output/time limits, and cleanup. A real local containment smoke passed; when disabled or preflight fails, the tool is unavailable with no host fallback. |
| Terminal/shell execution | Yes | Yes | Yes | Yes | Yes | No | The same optional Docker-only boundary is used for shell execution; there is no host-shell fallback. Local containment was observed, but local Docker smoke is not deployment or proof against every container-runtime escape. |
| PII controls before persistence | Yes | Yes | Yes | Yes | No | No | Sync/SSE persistence and run metadata redact configured PII before storage, and operational logging redacts PII, credential fields, compound credential keys, and database URLs. Acceptance used tests/local observation, not a production data audit. |
| Rate limiting and provider circuit breaking | Yes | Yes | Yes | Yes | Partial | No | Live routes enforce per-user and per-IP limits, and provider calls share circuit-breaker state rather than creating request-local breakers. Local tests used the mock provider; no production traffic or external-provider recovery was observed. |
| Web search and source display | Yes | Yes | Yes | Yes | Yes | No | Brave-backed search and source rendering were observed. The refreshed SSE path projects only validated title/URL fields from successful search results and excludes snippets/full content; claim-level verification is still not consistent. |
| Document ingestion and RAG | Yes | Partial | Yes | Yes | Partial | No | Educational path defaults to mock embeddings/in-memory vectors; metadata is volatile. |
| Durable vector storage / pgvector | Partial | Partial | Partial | No | No | No | PostgreSQL path stores JSON vectors and computes similarity in Python; route compatibility is broken. |
| Multimodal input | Yes | Partial | Partial | No | Partial | No | Plumbing exists, but persuasive real-provider end-to-end evidence is absent. |
| Sequential specialist pipeline | Yes | Partial | Yes | Partial | No | No | Four serial prompts exist on a separate route; no independent child context, enforced budget, or trace graph. |
| Secure multi-agent coordination | Partial | No | Yes | No | No | No | HMAC/token classes have unit tests but are not activated by the live route. |
| MCP integration | Partial | Partial | Yes | Yes | No | No | Public MCP-shaped JSON-RPC routes return explicit stubs; no real server lifecycle/OAuth/tool governance. |
| Background tasks | Partial | Partial | Yes | Yes | Partial | No | In-process placeholder queue ignores requested work and is non-durable and owner-unaware. |
| Cost and usage reporting | Yes | Yes | Yes | Yes | Yes | No | Per-response estimate is visible; tracker resets per request, so durable budgets/aggregation are absent. |
| OpenTelemetry export | Yes | Partial | Yes | No | No | No | Configurable exporter code exists; it was disabled in the audited runtime. |
| Evaluation harness | Partial | Partial | Yes | Partial | Partial | No | Heuristic/mock evaluation exists; the batch harness does not evaluate real recorded runs. |
| A/B model comparison | Partial | Partial | Yes | Partial | Partial | No | Current endpoint fabricates mock responses rather than invoking selected models. |
| Desktop Workbench | Yes | Yes | Partial | Yes | Yes | No | Strong visual base and live run inspection; frontend coverage is narrow. |
| Mobile product shell | Yes | Yes | Partial | Yes | Partial | No | Inner chat scenario passes, but the global sidebar compresses the 390 px layout. |
| Operational health/status UI | Yes | Partial | Partial | Yes | Partial | No | Some states are hardcoded or map permission failures to “Down”; they are not trustworthy operational evidence. |
| Local container packaging | Yes | Yes | Yes | Yes | N/A | No | The backend image and separate immutable sandbox image were built; local backend `/healthz` and real sandbox containment smokes passed with mock-provider configuration. This is not a deployment. |
| Kubernetes/Helm/cloud deployment | Yes | No | No | No | No | No | Manifests are artifacts only; no cluster, public environment, or deployment smoke was verified. |

## Defensible summary

Archon is a strong **agent-engineering portfolio prototype**, not a production platform or competitor-equivalent coding agent. Its best-supported capabilities now include the typed budgeted runtime, live policy enforcement and durable approvals, encrypted owner/project-scoped memory, persistence/log redaction, live rate limiting with a shared breaker, optional fail-closed Docker execution, and an owner-scoped run ledger with replay/fork/compare UI. Those claims are backed by local acceptance, predominantly with a mock provider. RAG durability, MCP, multi-agent security, evaluations, trustworthy operations UI, real-provider behavior, remote CI, deployment, and production readiness remain partial or unverified.

The old `37/37` claim described a 38-row inventory with mixed implementation depth; it was not parity. Likewise, source presence and unit tests do not establish that a capability is wired, observed in the product, visible in the UI, or deployed.

## Claim policy

When updating this document:

1. Record the exact revision and environment.
2. Preserve all six evidence dimensions; do not collapse them into one completion checkmark.
3. Link test, runtime, UI, or deployment evidence in Notes or a detailed audit.
4. Treat mocks, stubs, flags, manifests, and local Docker smoke as such.
5. Do not claim production readiness, parity, zero dead code, or green gates without a fresh audit that directly proves the claim.
