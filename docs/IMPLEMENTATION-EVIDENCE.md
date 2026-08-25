# Archon Implementation Evidence

**Canonical status source**

- **Last audited:** 2026-08-25
- **Audited revision:** `27952f4` on local `main`
- **Repository state:** local `main` was 54 commits ahead of `origin/main`; the audited work had not been pushed

This is the sole canonical matrix for current implementation and release claims. Other summaries must link here rather than maintain competing scorecards. The detailed findings remain in [Feature and Course Concept Audit v2](FEATURE-AND-COURSE-AUDIT-V2.md) and the [GPT-5.6 Re-Audit](ARCHON-GPT56-REAUDIT-2026-08-25.md).

## How to read the matrix

A capability is evaluated on six independent evidence dimensions:

- **Exists:** meaningful code or an artifact is present. A stub, mock, manifest, or configuration flag is identified in Notes.
- **Wired:** a product/API path invokes it. `Partial` includes separate, optional, unsafe, or non-default paths.
- **Tested:** automated tests exercise relevant behavior. This does not imply live integration or production readiness.
- **Observed:** the audit directly exercised the behavior, rather than inferring it from code or tests.
- **UI:** a user can see or operate it in the current product. `Partial` includes misleading, transient, admin-only, or incomplete surfaces.
- **Deployed:** verified in a non-local environment. A local process, Docker image, manifest, or successful build is not a deployment.

Legend: **Yes** = supported by evidence; **Partial** = limited or qualified evidence; **No** = absent or contradicted; **N/A** = not applicable. None of these columns alone means production-ready.

## Fresh quality-gate evidence

These are results from the audited revision, not claims that the current documentation branch has made the gates green.

| Gate | Fresh result | Status |
|---|---|---|
| Backend tests | 466 passed, 0 skipped | Pass |
| Backend coverage | 81.84% | Measured; aggregate coverage is not integration proof |
| Ruff lint | 50 errors | **Fail** |
| Ruff format check | 16 files require formatting | **Fail** |
| Bandit | 0 medium/high findings | Pass; static scan only |
| Strict Mypy | 395 errors across the full app | **Fail** |
| Svelte check | 0 errors, 1 warning | Pass with warning |
| Frontend unit tests | 4 Vitest tests across 2 files | Pass; shallow coverage |
| Browser tests | 2 Playwright scenarios | Pass; chat desktop/mobile only |
| Frontend production build | Build completed | Pass |
| NPM production audit | 0 vulnerabilities | Pass |
| Docker smoke | Image built; `/healthz` passed with `mock-model/mock` | Pass locally; not a deployment |
| Remote CI | Last 10 runs failed; audited local work was not pushed | **No green remote evidence** |

**Release-gate verdict:** not green at the audited revision. The 466-test result is valid, but “all gates green” is not.

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
| Complete run resume/replay | Partial | No | Partial | No | No | No | Messages reload, but tools, evidence, usage, cost, policy, evals, and stop reason disappear. |
| Durable owner-scoped run ledger | Partial | Partial | Partial | No | No | No | Events can be persisted, but there is no owner-scoped trajectory API/UI or read-only replay. |
| Context compaction and inspection | Yes | Partial | Partial | Partial | Partial | No | Useful plumbing exists; effective-context provenance and some displayed metrics are incomplete or hardcoded. |
| Persistent memory | Yes | Yes | Yes | Yes | Partial | No | Live memory is global plaintext and cross-user; the encrypted store is not the actual live persistence path. |
| API authorization and ownership | Yes | Partial | Yes | Yes | Partial | No | Conversations/artifacts are stronger; memory, tasks, MCP, and approvals have ownership gaps. |
| Approval policy and human approval | Yes | Partial | Yes | Yes | Partial | No | SSE has a transient modal, but sync chat can bypass approval and decisions are not owner-scoped receipts. |
| File read/write tools | Yes | Yes | Yes | Partial | Yes | No | Useful workspace checks exist, but host execution paths can bypass the intended boundary. |
| Python/code execution | Yes | Yes | Yes | Partial | Yes | No | Approval-gated host subprocess prototype, **not a secure sandbox**. |
| Terminal/shell execution | Yes | Yes | Yes | Partial | Yes | No | Host shell with a blocklist, **not isolated execution**. |
| PII controls before persistence | Partial | No | Partial | No | No | No | A detector exists, but sync and SSE routes persist raw messages first. |
| Rate limiting and provider circuit breaking | Yes | No | Yes | No | Partial | No | Classes/tests and admin display exist; they do not protect the live provider path. |
| Web search and source display | Yes | Yes | Yes | Yes | Yes | No | Brave-backed search and source rendering were observed; claim-level verification is not consistent. |
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
| Local container packaging | Yes | Yes | Yes | Yes | N/A | No | Docker build and local `/healthz` smoke passed with mock configuration. |
| Kubernetes/Helm/cloud deployment | Yes | No | No | No | No | No | Manifests are artifacts only; no cluster, public environment, or deployment smoke was verified. |

## Defensible summary

Archon is a strong **agent-engineering portfolio prototype**, not a production platform or competitor-equivalent coding agent. Its best-supported capabilities are the typed budgeted runtime, native Anthropic/Foundry tool path, live SSE evidence, authenticated conversations, tool contracts, and broad backend tests. RAG durability, memory isolation, execution sandboxing, MCP, multi-agent security, evaluations, run replay, trustworthy operations UI, and deployment remain partial, scaffolded, unsafe, or unverified.

The old `37/37` claim described a 38-row inventory with mixed implementation depth; it was not parity. Likewise, source presence and unit tests do not establish that a capability is wired, observed in the product, visible in the UI, or deployed.

## Claim policy

When updating this document:

1. Record the exact revision and environment.
2. Preserve all six evidence dimensions; do not collapse them into one completion checkmark.
3. Link test, runtime, UI, or deployment evidence in Notes or a detailed audit.
4. Treat mocks, stubs, flags, manifests, and local Docker smoke as such.
5. Do not claim production readiness, parity, zero dead code, or green gates without a fresh audit that directly proves the claim.
