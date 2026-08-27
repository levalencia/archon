# Archon Implementation Evidence

**Canonical mutable status source**

## Baseline

- **Current accepted candidate:** `2f77877` on local `feature/s8-capstone-completion` (2026-08-27 Europe/Brussels).
- **S8.1 provider-contract acceptance:** full local verification passed; provider/model live acceptance remains a separate S8.9 gate.
- **Previous integrated S7.5 baseline:** `60a8d6a` on local `feature/s7-local`.
- **Remote status:** the S8 branch is local and unpushed; historical GitHub Actions [run #33042478912](https://github.com/levalencia/archon/actions/runs/33042478912) passed at `9696ad8`.
- **Deployment status:** production-like **local** target observed; no non-local/public deployment. Every `Deployed` value remains **No**.

This document separates code presence, wiring, tests, direct observation, UI, and deployment. Local tests, mocks, Docker smokes, and manifests are not public-production evidence.

The executable [capability acceptance manifest](implementation/CAPABILITY-ACCEPTANCE.yaml)
provides the validated, machine-readable baseline for capstone gap status and evidence pointers.

## Evidence dimensions

- **Exists:** meaningful code/artifact exists.
- **Wired:** a live product/API path invokes it.
- **Tested:** automated tests exercise the relevant contract.
- **Observed:** behavior was directly exercised in the local evidence run.
- **UI:** a current product surface exposes it.
- **Deployed:** verified outside the local machine.

Legend: **Yes**, **Partial**, **No**, **N/A**.

## Quality gates

### S8.1 full local acceptance at `2f77877`

| Gate | Result |
|---|---|
| Capability manifest | 16 entries validated |
| Course documentation validator | Pass |
| Backend tests | 1,220 passed |
| Coverage | 86.88% aggregate |
| Ruff check / format | Pass |
| Bandit `-ll` | Pass; no medium/high findings |
| Svelte check | 0 errors, 0 warnings |
| Vitest | 17 passed |
| Frontend build | Pass |
| Playwright | 21 passed |
| Docker sandbox containment | Pass |
| Backend image health | Pass |

The provider-contract slice adds typed capability negotiation, fail-before-call enforcement, local structured-output validation, capability-preserving fallback, provider-reported cache accounting, per-response fallback pricing, and conservative OpenAI/Ollama opt-ins. These are local deterministic and container acceptance results, not real-provider or public-deployment evidence.

### Previous S7.5 full acceptance at `60a8d6a`

### Additional S7 evidence after that acceptance

| Evidence | Result |
|---|---|
| Local Compose smoke | Backend/frontend/gateway/PostgreSQL/Redis/OTEL healthy; auth, migration 08, metrics, and exported `agent.run` span verified |
| DR focused tests | 18 passed before S7.2 commit |
| DR real run | Backup 0.343 s; RTO 21.586 s; RPO 0 records at snapshot; exact evidence restored |
| Benchmark focused tests | 6 passed, including direct CLI subprocess |
| Benchmark strict Mypy | Pass for `scripts/portfolio_benchmark.py` |
| Benchmark real run | 30/30 deterministic scenario iterations, 420 synthetic tokens, external cost $0, workspace unchanged |
| npm audit | Production dependencies: 0; all dependencies: 7 low dev/tooling, 0 moderate/high/critical |

Evidence files:

- [`local-dr-report.json`](evidence/local-dr-report.json)
- [`local-portfolio-benchmark.json`](evidence/local-portfolio-benchmark.json)

## Capability matrix

| Capability | Exists | Wired | Tested | Observed | UI | Deployed | Evidence and limits |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|
| Typed budgeted runtime | Yes | Yes | Yes | Yes | Yes | No | Native tool calls, explicit stop reasons, iteration/tool/token/time budgets on sync and SSE paths. |
| Provider capability negotiation | Yes | Yes | Yes | Yes | N/A | No | Conjunctive requirements, fail-before-call, typed fallback, and conservative OpenAI/Ollama opt-ins. No real-provider parity run. |
| Validated structured output | Yes | Yes | Yes | Yes | N/A | No | Immutable response contracts and local strict parse/schema validation before terminal emission or persistence. Native provider schema acceptance remains unobserved live. |
| Prompt-cache accounting | Yes | Yes | Yes | Yes | Partial | No | Provider-reported counters, per-response actual-provider pricing, events, tracing and SSE are locally tested. No real cache-hit or invoice comparison. |
| Policy matching | Yes | Yes | Yes | Yes | Partial | No | Deterministic allow/ask/deny rules; unknown side effects fail closed. Decisions visible in run evidence. |
| Durable approvals | Yes | Yes | Yes | Yes | Yes | No | Exact user/run/tool-call/name/argument-hash binding, expiry, cancellation, atomic one-shot decisions. |
| Tool registry contracts | Yes | Yes | Yes | Yes | Yes | No | Validated schemas, risk/resource metadata, permissions, bounded execution and sanitized errors. |
| Filesystem containment | Yes | Yes | Yes | Yes | Partial | No | Descriptor-relative traversal rejects escape, symlink, hard-link and unsafe targets. |
| Code/shell isolation | Yes | Partial | Yes | Yes | Yes | No | Optional Docker-only path; no network/mounts/capabilities, read-only, non-root, resource limits, no host fallback. Disabled in verified local target. |
| Authentication/ownership | Yes | Yes | Yes | Yes | Yes | No | Conversations, runs, approvals, memory, documents, evals and MCP use owner/project scope where applicable. |
| Encrypted persistent memory | Yes | Yes | Yes | Yes | Partial | No | AES-GCM with derived owner/project context and fail-closed startup key. No online key rotation. |
| PII/secret redaction | Yes | Yes | Yes | Yes | Partial | No | Redaction precedes supported persistence/log paths; tests cover nested credential-like data. Not a production data audit. |
| Rate limiting | Yes | Yes | Yes | Yes | Partial | No | Per-user/IP controls with Redis-backed verified target; readiness checks Redis. |
| Circuit breaker/fallback | Yes | Yes | Yes | Yes | Partial | No | App-scoped breaker; deterministic benchmark proves open/fail-fast/half-open/recovery plus secondary fallback. External-provider recovery not observed. |
| Durable Run Ledger | Yes | Yes | Yes | Yes | Yes | No | Ordered owner-scoped events, terminal metadata, retention, reload, replay, fork, compare and child lineage. |
| Executable resume | Partial | No | Yes | No | Partial | No | Replay is intentionally stored-only. Fork does not restore arbitrary external workspace state. |
| Durable document ingestion | Yes | Yes | Yes | Yes | Yes | No | PostgreSQL metadata/chunks survive restart and verified backup/restore. PostgreSQL advisory-lock path directly observed. |
| Vector retrieval | Yes | Yes | Yes | Yes | Yes | No | JSON embeddings and cosine in Python (`sql-json-cosine`). **Not pgvector** and not a high-scale indexed claim. |
| Grounded claims/citations | Yes | Yes | Yes | Yes | Yes | No | Unsupported, unknown, missing, negated, numeric and partial claims fail conservatively. |
| External embedding provider | Partial | Partial | Yes | No | Partial | No | Hardened endpoint path exists; final acceptance used deterministic mock embeddings. |
| Recorded-run evaluations | Yes | Yes | Yes | Yes | Yes | No | Versioned datasets evaluate persisted runs; legacy fabricated A/B endpoints return 410. |
| Bounded verifier child | Yes | Yes | Yes | Yes | Yes | No | Evidence-only context, no tools, real token/time/retry budgets, durable parent-child runs and benefit fixture. One specialist, not a swarm. |
| MCP stdio integration | Yes | Yes | Yes | Yes | Yes | No | Official MCP 2.1.1 client/server tests, cursor pagination, allowlisted profiles, durable inventory, per-tool policy/approval and Skills & Integrations UI. No production OAuth/HTTP transport claim. |
| Evidence-first Workbench | Yes | Yes | Yes | Yes | Yes | No | Full-width responsive shell, contextual inspector, inline evidence, mobile/tablet focus containment, route coverage. |
| OpenTelemetry | Yes | Yes | Yes | Yes | Partial | No | Real SDK/exporter in local image; readiness reports active state; collector logs proved `agent.run`. No hosted trace backend. |
| Local container target | Yes | Yes | Yes | Yes | N/A | No | Digest-pinned, loopback-only gateway, non-root/read-only app containers, internal PostgreSQL/Redis/OTEL. Local evidence is not deployment. |
| Backup/restore | Yes | Yes | Yes | Yes | No | No | SHA-256 verified custom dump, clean-target guard, full restore and exact record/hash checks with measured RTO/RPO. |
| Portfolio benchmark | Yes | Yes | Yes | Yes | No | No | Deterministic local control-plane benchmark; not model quality, load, cost, or production latency evidence. |
| Public/cloud deployment | Partial | No | No | No | No | No | Historical manifests exist but were not selected or verified. User explicitly chose local-only. No Azure resources were created. |
| Remote CI | Yes | Yes | Yes | Yes | No | No | GitHub Actions backend, frontend and backend-image jobs passed in run `33042478912` at `9696ad8`. CI evidence is not deployment. |

## Directly observed local scenarios

### Local deployment

The verified target built and started digest-pinned app/dependency images, migrated PostgreSQL to revision 08, required Redis readiness, routed traffic through the loopback gateway, authenticated a user, exposed metrics, and exported an `agent.run` span to the collector. Apple ARM hit a known native `cryptography` SIGILL; the backend target is explicitly `linux/amd64` and the successful run used that boundary.

### Disaster recovery

The DR run created synthetic user, conversation, run/events, document/chunk and approved terminal approval data. It produced a checksummed custom PostgreSQL dump, removed the source volume, restored into a fresh Compose project, started the application, authenticated with the restored account, and compared exact IDs/counts/hashes. The final development-machine observation was backup 0.343 s, RTO 21.586 s, and zero changed records at the backup boundary.

### Portfolio benchmark

Ten iterations each exercised:

1. a write-class tool blocked without an authorizer and executed exactly once with exact-bound approval;
2. circuit opening, fail-fast rejection, half-open recovery and fallback to a secondary adapter;
3. a real `GroundedDocumentWorkflow` retaining one supported claim and excluding an unsupported overclaim while persisting terminal run evidence.

The benchmark is deterministic and offline. Its timings and synthetic token counts are not production performance claims.

## Defensible summary

Archon is an evidence-rich **local Agent Reliability Workbench**. Its strongest claims are policy/approval enforcement, durable run evidence, privacy boundaries, isolated optional execution, grounded evaluation, one constrained verifier child, governed MCP stdio integration, responsive inspection UI, and reproducible local operations/DR.

It is **not** a publicly deployed production platform. Real external-provider behavior, indexed vector serving, production traffic, SLOs, multi-host scaling, and cloud operations remain unverified or deliberately deferred.

## Claim policy

1. Record revision, environment and command.
2. Keep Exists/Wired/Tested/Observed/UI/Deployed independent.
3. Label mocks, fixtures and local smokes.
4. Never translate local Docker evidence into `Deployed: Yes`.
5. Do not claim pgvector, model quality, production readiness, parity, or green remote CI without direct evidence.
