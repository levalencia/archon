# Archon Implementation Evidence

**Canonical mutable status source**

## Baseline

- **Public baseline before this live-demo candidate:** `82b9120` on `main`, after merged capstone PR #1 and managed-runtime PR #2.
- **Current acceptance scope:** deterministic full verification plus operator-authorized Foundry model/tool/multimodal and managed API/browser chat evidence.
- **Capability status source:** `docs/implementation/CAPABILITY-ACCEPTANCE.yaml`; this prose must not override its per-dimension limits.
- **Remote status:** `main` was green before this candidate; publish only after the candidate's PR CI is green and reviewed.
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

### S8.2 full local acceptance at `ec45585`

| Gate | Result |
|---|---|
| Capability manifest | 16 entries validated |
| Course documentation validator | Pass |
| Backend tests | 1,278 passed |
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

### S8.9 real-provider acceptance harness

The model, multimodal, and embedding acceptance scripts require both `--execute-live` and non-mock application configuration. Provider work executes in a killable child process with a hard wall-clock watchdog. Reports use strict per-kind schemas and explicit `dry_run`/`deterministic`/`live` provenance; they reject raw URLs, query material, credentials, inconsistent status/error fields, symlink traversal, blocking special files, and artifacts over 64 KiB. Writes are descriptor-relative, atomic, and owner-only (`0600`) beneath the system temporary directory.

Deterministic fake-provider coverage is **11 passed, 1 live test skipped**; focused provider/embedding/multimodal regression coverage is **147 passed, 1 skipped**. macOS full backend acceptance passed **1,382 tests with 2 expected skips**, followed by the final FIFO-focused gate (**11 passed, 1 skipped**) on both Linux and macOS. Default CLI dry-runs for all three scripts produced `skipped` reports without provider calls. Independent blocker review of `c04cd15` returned `APPROVED`.

Operator-authorized live acceptance was executed on 2026-08-28 using the configured Azure AI Foundry Anthropic adapter (`claude-opus-4-6`). Native tool calling passed with one tool call; provider-reported cache counters were transported successfully with zero read/write tokens, which is not a cache-hit or billing-savings claim. The one-pixel multimodal semantic probe passed. Native JSON Schema was skipped because that adapter does not advertise the capability. Embedding and ingest/query were not called because the configured embedding provider remains `mock`. The sanitized timestamps, elapsed durations, host, model revision, results, metrics, and limits are recorded in [live-provider-acceptance-summary.json](evidence/live-provider-acceptance-summary.json); prompts, responses, credentials, full URLs, and raw provider errors were not retained.

A second operator-authorized acceptance on 2026-08-29 exercised the managed seven-service application in explicit `live-foundry` mode. The protected provider env was owner-only, parsed without shell evaluation, and reduced to an LLM allowlist before Compose startup. The backend health identity reported `foundry` / `claude-opus-4-6`; startup chat, authenticated API chat, and browser SSE chat each produced a live response. The live Workbench showed the provider/model identity and no mock-mode banner. This was three bounded model requests using marker prompts; it proves managed transport and UI wiring, not broad answer quality, public deployment, or live embeddings.

S8.9 therefore closes as **Partial**, not fully live-evidenced: actual external model/tool/cache-metric and multimodal behavior was observed, while native JSON Schema and live embedding remain explicit gaps.

### S8.10 benchmark and documentation candidate

The S8.10 candidate adds the explicit [remaining deferred-gap register](REMAINING-DEFERRED-GAPS.md), aligns course navigation/catalog boundaries, expands the deterministic benchmark to twelve production-control-plane scenarios, and hardens the integrated verification script. For each intentional omission, the register states the architecture and evidence required before reconsidering status.

The reviewed Linux benchmark at `8e21302` passed **120/120 scenario iterations** with zero failures and a clean workspace. Its Linux sandbox scenario executed the production runner child with seccomp and observed socket creation, protected control-file deletion, control-directory writes, and chmod attempts blocked. The benchmark also observed one real disclosure redaction from seeded legacy-sensitive data and a persisted drift report with a `-1.0` pass-rate delta bound to an approval-gated candidate. The checked-in benchmark artifact is the sanitized report from that run. macOS cross-platform acceptance passed **15 focused tests** and **24/24 benchmark iterations**; it explicitly records that seccomp was not executed on Darwin while still proving the Unix-socket client has no host fallback.

The integrated macOS gate passed after adding locked frontend dependency preparation: **11 provider-harness tests passed with 1 expected live skip**, **16 capability entries validated**, **1,408 backend tests passed with 2 expected skips at 87.30% coverage**, Svelte reported **0 errors and 0 warnings**, **48 Vitest tests passed**, the production frontend build passed, **26 Playwright tests passed**, Docker sandbox containment passed, the backend image became healthy, the deterministic benchmark passed, and the workspace stayed clean. The Visual Learning Studio slice contributed a deterministic 66-concept graph, four generated-data contract tests plus one alias/fallback contract, four browser flows, and the `/learn/map` route. This proves local reproducibility and visual-learning wiring, not production deployment or learning efficacy.

The final local deployment smoke then passed with a split-platform configuration on Apple Silicon: application containers remain reproducible `linux/amd64`, while the sandbox runner uses the daemon-native architecture so nested seccomp is not attempted under QEMU. The runner keeps Moby's vendored outer default-deny profile and installs an additional child filter; `seccomp=unconfined` is prohibited. The smoke verified gateway, PostgreSQL, Redis, mock embeddings, authentication, metrics, Alembic revision `20260828_14`, and a newly exported OTEL trace batch at collector `verbosity: basic`. Individual span names remain covered by instrumentation tests rather than claimed from basic collector logs. The final DR smoke also passed: checksum-verified backup/restore preserved the run, five run events, one document/vector chunk, and one terminal approval with **RPO 0 records** and measured **RTO 24.787 seconds**. The sanitized DR artifact is committed at [local-dr-report.json](evidence/local-dr-report.json).

S8.10 local acceptance is complete for the declared local-only target. This does **not** upgrade distributed scale, anonymous-sharing, autonomous optimization, or public deployment evidence. Every `Deployed` value remains **No**. S8.9 is closed as `Partial`: model tool/cache-metric and multimodal paths have live evidence, while native JSON Schema and embeddings remain non-live gaps.

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

### Effective context and online memory-key rotation

Sync and SSE runs persist a metadata-only context manifest after the run and current user message are durable. The manifest identifies selected and summarized conversation rows, memory fact IDs, skill IDs, token estimates, compaction reason/version, and owner/project/run-scoped HMAC fingerprints for image inputs. It does not store prompts, message content, memory content, skill content, image payloads, summaries, or hidden reasoning. Authenticated owners can inspect the manifest through `GET /api/runs/{run_id}/context`.

Encrypted memory supports versioned keyrings, row-version decryption, active-version writes, bounded transactional re-encryption, interruption-safe resume, owner/project-scoped status and rotation APIs, startup validation, a durable global active-generation fence for updated writers, and a responsive rotation-status panel. Migration `20260827_11` forward-migrates databases already stamped at revision 10. Retirement additionally requires the explicit pre-fence writer drain documented in `docs/operations/memory-key-rotation.md`; external KMS integration and automatic expiry are not claimed.

### Bounded final-answer reflection

Reflection is disabled by default and runs only on an unstructured final-answer draft. The critic and optional single revision receive no tools. Reflection inherits the run deadline/token budget and adds rubric-versioned input/output/time/revision/priced-cost limits. The hard timeout returns without waiting for cancellation-delaying provider cleanup; zero/unknown usage receives conservative estimates; oversized responses fail safe; monetary failures preserve the draft and established budget stop semantics.

Persisted events contain closed metadata, bounded issue codes, validated `request:L#` / `draft:L#` locations, usage/cost and owner/project/run-scoped HMAC fingerprints. Draft, critique, revision, prompt text and hidden reasoning are excluded. Focused adversarial acceptance passed 35 tests at Mac revision `eb5a448`, and independent blocker review returned `APPROVED`.

`reflection-benefit-v1.json` is explicitly a `recorded_synthetic_fixture`: its report says `runtime_executed=false` and `generalizes=false`. Its deterministic score delta tests the fixture loader/scorer only; it is not evidence that a live model improves under reflection.

### Secure run export, sharing, and mandatory compliance

Authenticated owners can create immutable, versioned run-evidence bundles containing disclosure-scanned run/event metadata, context lineage, citation/evaluation summaries, per-section checksums, a row-bound manifest checksum, and explicit omissions. Downloads and share redemption repeat integrity and disclosure scans. Structured secret values are replaced idempotently, so valid redacted bundles remain downloadable while raw structured secrets fail disclosure.

Share grants store only a domain-separated HMAC token digest and bind an authenticated recipient, closed purpose, expiry, owner, and export. The token is returned once. Redemption linearizes against revocation/expiry inside one transaction and performs a final active-grant check before disclosure. The local target deliberately exposes no anonymous/public share URL or external token-delivery claim.

Mandatory compliance executes before sync/SSE user persistence, grounded document ingestion, final-answer structured validation/persistence, model-progress persistence, and effect-ledger reservation/handler dispatch. Compliance remains a deterministic local rule boundary rather than a production legal-policy service. Migration `20260828_12` is forward/reversible over revision 11. Integrated Mac acceptance at candidate `ba62c0f` passed 1,335 backend tests, Svelte check with zero diagnostics, 20 Vitest tests, a production build, and 21 Playwright browser tests; independent blocker review returned `APPROVED`.

### Signed delegation and durable background jobs

The active verifier child requires a parent-issued, versioned HMAC envelope bound to owner/project, parent/child run IDs, the actual bounded claim and evidence text, declared hashes, budget, schema, timestamp, and one-time nonce. Verification is constant-time for signatures; successful nonces are durably consumed, stale receipts are pruned only after their freshness window, and missing, replayed, stale, foreign-scope, budget-modified, or content-modified envelopes fail before provider execution.

Background work uses migration `20260828_13`, atomic SQL claims, monotonic lease generations independent of retry counters, heartbeats, expiry recovery, bounded exponential retries, dead-letter, cancellation, manual retry, concurrent idempotency, owner/project-scoped APIs, readiness, and an owner-scoped dashboard inspector. Production job kinds are closed to effect-free `echo` and database-idempotent `run_export`; payloads reject PII/secrets and result metadata is disclosure-redacted.

Semantics are deliberately **at-least-once**, not exactly-once. In-process Python cannot forcibly terminate a coroutine that suppresses cancellation, so non-idempotent external-effect handlers are prohibited; harder process termination is delegated to the S8.7 sandbox boundary. No live PostgreSQL contention or multi-host worker claim is made. Integrated Mac backend candidate `98dbae5` passed 1,354 backend tests. Follow-up UI candidate `112d00a` passed Svelte check with zero diagnostics, 30 Vitest tests, a production build, and 21 Playwright tests. Independent backend, documentation, and final UI race blocker re-reviews returned `APPROVED`.

### Isolated sandbox runner and validated multimodal path

When optional execution is enabled, the backend preflights and uses only `SandboxRunnerClient` over a private Unix socket. The dedicated runner container is non-root, networkless, read-only, capability-free, no-new-privileges, PID/memory/CPU/tmpfs bounded, and receives neither the Docker socket nor a project mount. Child-only seccomp blocks network/control-socket access, process inspection/signals, process-group escape, and control-path mutation. Requests use strict bounded frames and one active slot; timeout, output cap, server cancellation, peer disconnect, and normal completion all terminate the process group. Final JSON encoding is measured and truncated below the protocol frame limit, and Compose `init` reaps orphaned descendants.

The authenticated sync and SSE image paths reject malformed/oversized Data URIs, strict-base64 failures, byte/MIME mismatches, oversized dimensions/pixel counts before pixel load, and oversized sanitized output before conversation persistence or provider execution. Accepted pixels are re-encoded to remove metadata and used transiently without global attachment accumulation. Deterministic E2E tests prove sanitized images reach the capturing runtime and OpenAI, Anthropic, and Ollama request builders; no external vision-provider observation is claimed.

Linux acceptance executed 1,360 backend tests before the final focused lifecycle regressions, followed by 25 focused sandbox/multimodal/deployment tests and a real Docker Compose smoke covering executable seccomp preflight, runtime flags, backend-to-runner execution, stdin backpressure deadlines, network/control-socket denial, shared-volume write denial, detached-child cleanup, timeout, output truncation, and JSON-escape framing. The smoke removed containers, networks, and volumes. Mac candidate `ffeada9` passed 1,366 tests with one expected Linux-only seccomp skip, 35 Vitest tests, Svelte check with zero diagnostics, a production build, and 21 Playwright tests. Independent final blocker re-review at `be28e7f` returned `APPROVED`. The result is local container isolation, not VM-grade hostile multi-tenant certification, live-provider evidence, public deployment, or a production SLO.

### Governed drift reports and reviewed optimization candidates

Archon now compares owner/project-scoped, immutable evaluation cohorts using deterministic descriptive summaries for pass rate, score distribution, latency, token/cost, abstention, citation coverage, unsupported claims, and safety failures. Minimum sample checks and fixed warning thresholds are operational rules only; no p-value or statistical-significance claim is made.

Recorded evaluation identities derive model/provider from the completed source-run ledger and an internal evaluator config revision; the public API cannot override them. Migration 14 backfills historical cohorts with deterministic legacy identity when source rows exist and explicit `legacy-*-unresolved` markers otherwise. Unresolved cohorts are rejected from drift comparison.

Optimization candidates are bounded to prompt, policy, retrieval, or config revision records. Metadata uses per-type allowlists and deterministic PII/credential rejection. Exact human approval binds owner, project, candidate ID/version, target revision, purpose, and before/after evaluations. Promotion records the approved declared revision only: it does not modify runtime configuration, prompts, retrieval, providers, or model weights. Reject/approve closes alternate pending receipts; rollback remains a separate auditable transition.

Migration-level integrity includes composite scope foreign keys and SQLite/PostgreSQL append-only/state-machine triggers. PostgreSQL real acceptance passed upgrade to head, downgrade to revision 13, and re-upgrade with four active S8.8 triggers. macOS acceptance passed 1,371 backend tests with one expected Linux-only seccomp skip. The final UI gate passed 44 Vitest tests, Svelte check with zero diagnostics, production build, and 21 Playwright tests after fixing an accessible-label collision. Independent blocker re-review of `cb76b1e` returned `APPROVED` for stale busy-state handling and atomic approval reservation.

Limits: no autonomous optimization, no runtime mutation, no model training, no scheduler that generates candidates unattended, no live-provider quality claim, and no public deployment claim.

## Defensible summary

Archon is an evidence-rich **local Agent Reliability Workbench**. Its strongest claims are policy/approval enforcement, durable run evidence, privacy boundaries, isolated optional execution, grounded evaluation, one constrained verifier child, governed MCP stdio integration, responsive inspection UI, and reproducible local operations/DR.

It is **not** a publicly deployed production platform. Real external-provider behavior, indexed vector serving, production traffic, SLOs, multi-host scaling, and cloud operations remain unverified or deliberately deferred.

The architecture and evidence thresholds for the six intentional capstone omissions are maintained in [Remaining Deferred Gaps](REMAINING-DEFERRED-GAPS.md).

## Claim policy

1. Record revision, environment and command.
2. Keep Exists/Wired/Tested/Observed/UI/Deployed independent.
3. Label mocks, fixtures and local smokes.
4. Never translate local Docker evidence into `Deployed: Yes`.
5. Do not claim pgvector, model quality, production readiness, parity, or green remote CI without direct evidence.
