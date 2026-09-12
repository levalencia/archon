# Cogentrex Implementation Evidence

> **Audience:** Maintainers and auditors reviewing technical proof.
> **Purpose:** Detailed evidence ledger for implementation, wiring, tests, direct observation, UI, and deployment. Start with the [Evidence Guide](EVIDENCE.md) for a human-readable overview.
> **Status:** Active technical ledger. Per-capability status remains authoritative in the acceptance manifest.

**Canonical technical evidence source**

## Current baseline

- **Capability status:** `docs/implementation/CAPABILITY-ACCEPTANCE.yaml` is authoritative for per-dimension status.
- **CI:** GitHub Actions is authoritative for the current branch and exact revision results.
- **Runtime:** tool, token, time, and monetary limits are enforced by deterministic code paths.
- **Deployment:** the verified target is local only. No public or cloud deployment is claimed.

This ledger separates code presence, wiring, tests, direct observation, UI, and deployment. Historical acceptance records remain below for traceability; they do not override the current capability manifest.

### Historical candidate baseline (superseded)

The following records the pre-merge candidate status at `feature/skills-project-instructions-mcp` for historical traceability. Code evidence was anchored at `9eaf49e`; exact-head `verify.sh` PASS at `26e36737` with backend 1,537 passed / 4 skipped, Svelte 0/0, Vitest 53, Playwright 33. These numbers are superseded by the merged main CI results above.

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

## Skills + Project Instructions (merged to main)

The merged main implements migrations `20260901_15` through `20260902_22`, 41
ORM tables, ten owned bundled skills, immutable skill revisions and exact
owner/project/revision bindings, approved project-instruction snapshots,
metadata-first capability discovery, and one request-context preparation path
shared by sync and SSE. Effective-context persistence records exact instruction
and skill revisions plus capability IDs/schema hashes in the Run Ledger without
persisting raw instruction or skill bodies there.

The optional GodMode catalog adapter is metadata-only and disabled by default;
it does not install, trust, or inject remote content. Governed MCP supports both
allowlisted stdio and bounded Streamable HTTP profiles. Discovery is not
authorization: project enablement, disabled/deny filtering, schema-hash checks, and execution-time
revalidation remain separate.

Focused evidence covers the existing skill parser/catalog/persistence/security,
instruction loader/precedence/snapshot, capability selector/governance,
scoped-API, MCP transport, and migration tests listed in
[`docs/evidence/skills-project-instructions-implementation.md`](evidence/skills-project-instructions-implementation.md).

Two direct observations were recorded for the pre-merge candidate and remain valid historical evidence:

- **Foundry acceptance — PASS:** `claude-opus-4-6`, no mock fallback, with one
  selected skill revision, one approved instruction revision, and nine
  capability provenance references in the run context.
- **Disposable PostgreSQL acceptance — PASS:** upgrade to head
  `20260901_21`, five active integrity triggers, two composite owner foreign
  keys, `mcp_servers.enabled` defaulting to false, downgrade to revision 14,
  and re-upgrade to 21.

- **Exact-head integrated gate — PASS (historical at `26e36737`):** backend **1537 passed / 4 skipped**,
  Svelte **0/0**, Vitest **53**, build PASS, Playwright **33**, Bandit,
  sandbox, backend-container health, benchmark, and clean-tree checks.
  Superseded by CI run `33858051794` at merged `1f71f0e`.

These observations do not establish public deployment, broad skill-selection
quality, arbitrary repository trust, or external production readiness.

## Quality gates

### S8.2 full local acceptance at `ec45585`

| Gate | Result |
|---|---|
| Capability manifest | Current required entries validated |
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

Operator-authorized live acceptance was first executed on 2026-08-28 using the configured Azure AI Foundry Anthropic adapter (`claude-opus-4-6`). Native tool calling passed and provider-reported cache counters were transported; the counters were zero, which is not a cache-hit or billing-savings claim. The one-pixel multimodal semantic probe passed. At that revision native JSON Schema was unsupported and embeddings were not yet configured.

A superseding operator-authorized hardening acceptance on 2026-08-31 deployed Azure Foundry `text-embedding-3-small` in the development account and exercised the current branch through the managed seven-service stack. Structured output passed through Foundry JSON prompting plus strict local Draft 2020-12 validation; native provider-side JSON Schema remains explicitly unclaimed. Live embedding produced 1,536 finite non-zero coordinates and the repository ingest/query harness passed.

The end-to-end document path then passed `upload → embedding → persisted retrieval → Foundry grounded answer → bounded verifier`: one claim was supported, zero were unsupported, the child verifier completed with zero rejections, and the explicit faithfulness score was `1.0` using `live_bounded_verifier`. The same managed smoke proved durable budget and effect-ledger first-writer behavior against PostgreSQL with exactly one winner each. The evidence is sanitized in `docs/evidence/live-rag-hardening.json` and contains no prompts, provider text, endpoints, or credentials.

The seven hardening concepts therefore close as implemented within their stated local-development boundaries: durable budgets, context-window enforcement, deadlines/cancellation, validated structured output/cache accounting, live embeddings, bounded faithfulness verification, and durable at-most-once effects. Cache savings, native Foundry JSON Schema, provider invoice parity, broad semantic benchmarks, public deployment, and universal exactly-once semantics remain explicitly outside those claims.

Post-review deadline/context hardening replaced the former four-bytes-per-token average with a fail-closed bound over every known provider-visible field: roles/content, image references, `tool_call_id`, tool-call JSON, tool definitions, response format and response-contract schema. Every UTF-8 byte is counted as one token plus framing; provider-bound images are revalidated and reserve 22,000 tokens each. `AgentRuntime`, grounded RAG, and the verifier wrap run creation, event persistence, approval preparation, provider/tool waits, and normal finalization in one absolute deadline. Terminal persistence uses one shielded first-terminal-wins task with separate bounded cleanup; failure to complete is logged as indeterminate rather than starting a competing terminal sequence or claiming durable success.

### S8.10 benchmark and documentation candidate

The S8.10 candidate adds the explicit [remaining deferred-gap register](REMAINING-DEFERRED-GAPS.md), aligns course navigation/catalog boundaries, expands the deterministic benchmark to twelve production-control-plane scenarios, and hardens the integrated verification script. For each intentional omission, the register states the architecture and evidence required before reconsidering status.

The reviewed Linux benchmark at `8e21302` passed **120/120 scenario iterations** with zero failures and a clean workspace. Its Linux sandbox scenario executed the production runner child with seccomp and observed socket creation, protected control-file deletion, control-directory writes, and chmod attempts blocked. The benchmark also observed one real disclosure redaction from seeded legacy-sensitive data and a persisted drift report with a `-1.0` pass-rate delta bound to an approval-gated candidate. The checked-in benchmark artifact is the sanitized report from that run. macOS cross-platform acceptance passed **15 focused tests** and **24/24 benchmark iterations**; it explicitly records that seccomp was not executed on Darwin while still proving the Unix-socket client has no host fallback.

#### Rejected predecessor: force-map acceptance

The following result records the first visual-map implementation for historical traceability; it is not the current learning interface.

The integrated macOS gate passed after adding locked frontend dependency preparation: **11 provider-harness tests passed with 1 expected live skip**, **16 capability entries validated**, **1,408 backend tests passed with 2 expected skips at 87.30% coverage**, Svelte reported **0 errors and 0 warnings**, **48 Vitest tests passed**, the production frontend build passed, **26 Playwright tests passed**, Docker sandbox containment passed, the backend image became healthy, the deterministic benchmark passed, and the workspace stayed clean. The Visual Learning Studio slice contributed a deterministic 66-concept graph, four generated-data contract tests plus one alias/fallback contract, four browser flows, and the `/learn/map` route. This proves local reproducibility and visual-learning wiring, not production deployment or learning efficacy.

#### Superseding multi-view acceptance

The previously accepted Visual Learning Studio replaced that force-directed overview after direct learner feedback. At that acceptance point, `/learn` used fixed Roadmap, Stories, Architecture, Evidence, Present, Listen, and Study views; every runtime relationship was directional and visibly labeled, and the legacy `/learn/map` route redirected to Stories. The deterministic v2 manifest covered **66 concepts, 16 modules, 5 stories, 5 architecture layers, and 5 NotebookLM notebook recipes**. The source-pack builder emitted only allowlisted, tracked public sources outside the repository, recorded SHA-256 provenance, rejected dirty worktrees/symlinks/credential-like content, and never uploaded to Google. The superseding integrated gate passed **1,415 backend tests with 2 expected skips at 87.23% coverage**, Svelte **0 errors and 0 warnings**, **48 Vitest**, the production frontend build, **30 Playwright**, Docker containment/image checks, the deterministic benchmark, and clean-tree verification. Those checks proved deterministic generation, runtime wiring, responsive behavior, and source-pack safety; they did not claim that NotebookLM artifacts had already been generated or that learning efficacy had been independently measured.

The final local deployment smoke then passed with a split-platform configuration on Apple Silicon: application containers remain reproducible `linux/amd64`, while the sandbox runner uses the daemon-native architecture so nested seccomp is not attempted under QEMU. The runner keeps Moby's vendored outer default-deny profile and installs an additional child filter; `seccomp=unconfined` is prohibited. The smoke verified gateway, PostgreSQL, Redis, mock embeddings, authentication, metrics, Alembic revision `20260828_14`, and a newly exported OTEL trace batch at collector `verbosity: basic`. Individual span names remain covered by instrumentation tests rather than claimed from basic collector logs. The final DR smoke also passed: checksum-verified backup/restore preserved the run, five run events, one document/vector chunk, and one terminal approval with **RPO 0 records** and measured **RTO 24.787 seconds**. The sanitized DR artifact is committed at [local-dr-report.json](evidence/local-dr-report.json).

#### Hermes-native English learning-media candidate

The current feature branch adds a provider-neutral Visual Learning Studio v3 manifest and an external read-only learning-media catalog. The review-ready `request-lifecycle` pilot contains a deterministic 14-slide standalone HTML deck, two connected process diagrams, a purpose-designed evidence infographic, a progressive radial mind map, 20 flashcards, 10 scenario questions, a study guide, real English Edge TTS audio, and a 72-second English HyperFrames explainer with H.264 video and AAC audio. Every slide includes a 90-word-or-longer newcomer teaching script, key term, misconception, transition, and commit-pinned GitHub source link. Svelte Flow provides directed edges, pan/zoom, keyboard-focusable nodes and edges, selectable explanations, and a linear fallback. Backend routes validate catalog checksums, hide filesystem paths, issue short-lived HMAC capability URLs, and support HTTP byte ranges. The Svelte UI renders dedicated Present, Listen, and Study experiences with transcripts, provenance, limitations, real source hyperlinks, and interactive study controls.

The branch passed 742 backend unit tests in an environment isolated from the repository's live-provider `.env`, 67 Vitest tests, 12 focused Visual Learning Studio Playwright tests, Ruff, Svelte check with zero warnings, and the production frontend build. The retained seven-service live-Foundry stack was rebuilt without replacing PostgreSQL or Redis; `local-stack.sh status`, `/healthz`, and `/readyz` all passed. Authenticated runtime checks observed five English packs with ten `review-ready` artifacts each, structured deck/audio/video content, signed byte-range media delivery, invalid-range rejection, tampered-token rejection, and `Referrer-Policy: no-referrer`. Browser checks exercised pack switching and Present, Listen, and Study across all five packs; the four added packs expose 20 flashcards, 10 scenario questions, five audio chapters, and 112-second seekable videos with accessible transcripts.

The media status remains `review-ready` until Luis reviews its learning quality; it is not yet `published`. All five declared packs now exist in the local external catalog. The work does not claim public deployment, learning efficacy, premium voice quality, or human educational acceptance. The health-test fixture sets its mock embedding contract explicitly, so the canonical `make test` gate remains isolated from the developer's live-provider `.env` and passes without changing provider configuration.

S8.10 local acceptance is complete for the declared local-only target. This does **not** upgrade distributed scale, anonymous-sharing, autonomous optimization, or public deployment evidence. Every `Deployed` value remains **No**. The superseding 2026-08-31 hardening acceptance closes live embeddings, grounded-RAG verification, structured-output transport, monetary budgets, and PostgreSQL effect contention within the managed development target; native Foundry JSON Schema and cache savings remain explicitly unclaimed.

### Previous S7.5 full acceptance at `60a8d6a`

### Additional S7 evidence after that acceptance

| Evidence | Result |
|---|---|
| Local Compose/runtime acceptance | Managed stack ready with PostgreSQL/Redis preserved; Collector fan-out selected `debug`, Jaeger, and Logfire; one real calculator run produced a five-span agent trace observed by exact ID in Jaeger |
| DR focused tests | 18 passed before S7.2 commit |
| DR real run | Backup 0.69 s; observed restore-to-ready 24.787 s; zero selected-record differences at snapshot; exact evidence restored |
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
| Provider capability negotiation | Yes | Yes | Yes | Yes | N/A | No | Conjunctive requirements, fail-before-call, typed fallback, and conservative provider opt-ins. Foundry is live-observed; identical cross-provider behavior is not claimed. |
| Validated structured output | Yes | Yes | Yes | Yes | N/A | No | Foundry JSON prompting passed live and terminal output is bounded, duplicate-key checked, Draft 2020-12 validated and decoded locally before trust. Native provider schema is not claimed. |
| Prompt-cache accounting | Yes | Yes | Yes | Yes | Yes | No | Provider counters, per-response pricing, events, tracing and SSE are wired and live-exercised. The repeated-prefix probe reported zero cache tokens, so no savings claim is made. |
| Policy matching | Yes | Yes | Yes | Yes | Yes | No | Deterministic allow/ask/deny rules; unknown side effects fail closed. Decisions are visible in run evidence rather than a dedicated policy editor. |
| Durable approvals | Yes | Yes | Yes | Yes | Yes | No | Exact user/run/tool-call/name/argument-hash binding, expiry, cancellation, atomic one-shot decisions. |
| Tool registry contracts | Yes | Yes | Yes | Yes | Yes | No | Validated schemas, risk/resource metadata, permissions, bounded execution and sanitized errors. |
| Filesystem containment | Yes | Yes | Yes | Yes | N/A | No | Descriptor-relative traversal rejects escape, symlink, hard-link and unsafe targets; this backend boundary has no dedicated UI requirement. |
| Code/shell isolation | Yes | Yes | Yes | Yes | Yes | No | Optional Docker-only path is fully wired when enabled: no network/mounts/capabilities, read-only, non-root, resource limits, and no host fallback. It is intentionally disabled in the retained default target. |
| Authentication/ownership | Yes | Yes | Yes | Yes | Yes | No | Conversations, runs, approvals, memory, documents, evals and MCP use owner/project scope where applicable. |
| Encrypted persistent memory | Yes | Yes | Yes | Yes | Yes | No | AES-GCM with derived owner/project context, fail-closed startup key, online rotation, and a rotation-status UI. External KMS remains unclaimed. |
| PII/secret redaction | Yes | Yes | Yes | Yes | N/A | No | Redaction precedes supported persistence/log paths; tests cover nested credential-like data. It is a backend boundary, not a dedicated UI or production data-audit claim. |
| Rate limiting | Yes | Yes | Yes | Yes | N/A | No | Per-user/IP controls with Redis-backed verified target; readiness checks Redis. No dedicated UI is required. |
| Circuit breaker/fallback | Yes | Yes | Yes | Yes | N/A | No | App-scoped breaker and typed capability-aware fallback are tested; the managed target intentionally configures Foundry only and no live cross-provider failover is claimed. |
| Durable Run Ledger | Yes | Yes | Yes | Yes | Yes | No | Ordered owner-scoped events, terminal metadata, retention, reload, replay, fork, compare and child lineage. |
| Executable resume | No | No | Yes | No | No | No | Replay/fork checkpoints intentionally restore safe stored conversation state only; arbitrary executable workspace restoration is outside the current server-product contract. |
| Durable document ingestion | Yes | Yes | Yes | Yes | Yes | No | PostgreSQL metadata/chunks survive restart and verified backup/restore. PostgreSQL advisory-lock path directly observed. |
| Vector retrieval | Yes | Yes | Yes | Yes | Yes | No | JSON embeddings and cosine in Python (`sql-json-cosine`). **Not pgvector** and not a high-scale indexed claim. |
| Grounded claims/citations | Yes | Yes | Yes | Yes | Yes | No | Unsupported, unknown, missing, negated, numeric and partial claims fail conservatively. |
| External embedding provider | Yes | Yes | Yes | Yes | Yes | No | Azure Foundry `text-embedding-3-small` produced validated 1,536-dimensional vectors and passed persisted ingest/query plus full grounded-RAG acceptance in the development target. No broad quality or production SLA claim. |
| Recorded-run evaluations | Yes | Yes | Yes | Yes | Yes | No | Versioned datasets evaluate persisted runs; legacy fabricated A/B endpoints return 410. |
| Bounded verifier child | Yes | Yes | Yes | Yes | Yes | No | Evidence-only context, no tools, real token/time/retry budgets, durable parent-child runs and benefit fixture. One specialist, not a swarm. |
| Hybrid agent orchestration pilot | Yes | Yes | Yes | Yes | Yes | No | Feature-flagged Auto/Single/Team routing is wired through sync and SSE. A versioned 100-case paired Foundry benchmark produced 200 HTTP-200 responses and 400 durable parent/child run rows; 95 pairs were valid for blind quality comparison. Single scored 9.6000/10 and Team 9.5895/10 (Team-minus-Single -0.0105, bootstrap 95% CI [-0.2526, 0.2211], 12 Team wins / 72 ties / 11 Single wins). Across all 100 executed pairs, including invalid runs, Team cost 78.18% more and was 3.5687x slower. Security threat modeling alone met the directional Team-positive gate. `hybrid-router-v2` therefore keeps Single as default and routes only multi-signal security-risk analysis to Team. No new specialist is justified. See `docs/evidence/single-vs-team-benchmark-v1-summary.json`. No atomic parent-wide reservation, parallel fan-out, public deployment or production-SLO claim is made. |
| Governed MCP stdio + HTTP | Yes | Yes | Yes | Yes | Yes | No | Allowlisted stdio and bounded Streamable HTTP profiles, durable inventory, protected credential references, project enablement, per-tool policy/approval, schema-hash/TOCTOU checks, and UI. No generic OAuth platform or public gateway claim. |
| Skills, project instructions, and capability discovery | Yes | Yes | Yes | Yes | Partial | No | Ten bundled skills, immutable exact project bindings, approved instruction snapshots, shared sync/SSE preparation, metadata-first discovery, and exact Run Ledger provenance. One Foundry run observed 1 skill, 1 instruction and 9 capability refs. GodMode is optional metadata-only; UI code exists but this evidence packet does not claim a completed browser acceptance; no deployment or broad selection-quality claim. |
| Evidence-first Workbench | Yes | Yes | Yes | Yes | Yes | No | Full-width responsive shell, contextual inspector, safe inline Team lifecycle evidence with latest-parent replay, mobile/tablet focus containment, route coverage. |
| OpenTelemetry | Yes | Yes | Yes | Yes | Yes | No | Cogentrex owns a standard OpenTelemetry provider and emits one OTLP stream to the local Collector; an allowlisted selector generates fan-out for `debug`, Jaeger, Logfire, Azure Monitor, Tempo and generic OTLP without Python changes. Real Collector 0.118 configuration validation passed for every destination. Live run `b875ce4a-0760-42e5-9011-14815ff7b005` was observed in loopback-only Jaeger trace `7cd598cc71ef958a2ad2738405903cca` with `invoke_agent Cogentrex`, two `chat claude-opus-4-6` spans and `execute_tool calculator`; the same Collector pipeline included Logfire and reported no Logfire export error. A prior live run was visually accepted in Logfire Agents/Tools. The new opt-in Summary/Messages attributes are present in Jaeger, but their new Logfire UI rendering remains pending visual acceptance. Content capture defaults off; when enabled it exports only redacted, bounded user/assistant text and excludes system prompts, chain-of-thought, RAG content and tool payloads. Azure Monitor, Tempo and generic OTLP are configuration-validated, not live-observed. |
| Local container target | Yes | Yes | Yes | Yes | N/A | No | Digest-pinned, loopback-only gateway, non-root/read-only app containers, internal PostgreSQL/Redis/OTEL. Local evidence is not deployment. |
| Backup/restore | Yes | Yes | Yes | Yes | No | No | SHA-256 verified custom dump, clean-target guard, full restore and exact record/hash checks with an observed restore-to-ready measurement and selected-record snapshot comparison. |
| Portfolio benchmark | Yes | Yes | Yes | Yes | No | No | Deterministic local control-plane benchmark; not model quality, load, cost, or production latency evidence. |
| Public/cloud deployment | No | No | No | No | No | No | Historical manifests are non-authoritative artifacts; public deployment is explicitly deferred and no live public endpoint is claimed. |
| Remote CI | Yes | Yes | Yes | Yes | No | No | GitHub Actions backend, frontend and backend-image jobs passed in run `33858051794` at merged main `1f71f0e`. CI evidence is not deployment. |

## Directly observed local scenarios

### Local deployment

The retained target reports ready through the loopback gateway with digest-pinned dependencies, PostgreSQL, Redis, backend, frontend, sandbox and Collector. The optional loopback-only Jaeger profile was added without recreating PostgreSQL or Redis. Live run `b875ce4a-0760-42e5-9011-14815ff7b005` produced trace `7cd598cc71ef958a2ad2738405903cca`, containing `invoke_agent Cogentrex`, two model spans and `execute_tool calculator`. Collector fan-out simultaneously selected Logfire and emitted no Logfire export error; newest Logfire Summary/Messages UI rendering remains pending visual acceptance. Apple ARM previously hit a native `cryptography` SIGILL; the backend target remains explicitly `linux/amd64`.

### Disaster recovery

The DR run created synthetic user, conversation, run/events, document/chunk and approved terminal approval data. It produced a checksummed custom PostgreSQL dump, removed the source volume, restored into a fresh Compose project, started the application, authenticated with the restored account, and compared exact IDs/counts/hashes. The final development-machine observation was backup 0.69 s, restore-to-ready 24.787 s, and zero selected-record differences at the backup boundary.

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

The feature-flagged hybrid orchestration path reuses that signed-envelope boundary for two general-purpose read-only children. `Single` preserves the canonical runtime; `Team` creates a fixed researcher plus a server-templated dynamic analyst, each as a real child `AgentRuntime` and durable child run. `hybrid-router-v2` keeps Auto on Single unless the request contains at least two independent security-risk signals, the only category that met the preregistered directional Team-positive gate. Per-child runtime budgets override parent defaults, one aggregate deadline bounds the sequential team phase, cancellation records a terminal child event, and findings enter parent synthesis as explicitly delimited untrusted user data under a trusted system guard. The parent guard now explicitly forbids simulated tool calls and internal-planning narration. Parent events retain only safe allowlisted metadata. Focused tests cover sync/SSE wiring, two provider-backed child executions with the deterministic mock adapter, timeout cancellation, one fixed plus one dynamic profile, parent-child lineage, persisted events, reload reconstruction, router-v2 behavior, and feature-flag rollback.

The versioned `benchmarks/hybrid-orchestration/v1/` evaluation executed 100 paired Single/Team cases against local Foundry `claude-opus-4-6`. All 200 parent requests returned HTTP 200, while durable reconciliation found 398 completed, one failed, and one cancelled run among 400 parent/child rows. Five pairs were excluded from answer-quality comparison: two Single tool-contract violations, two degraded Team runs, and one Single parent that returned HTTP 200 but ended durably as `failed/provider_error`. Across 95 valid pairs, blind scoring found Single 9.6000/10 and Team 9.5895/10; Team-minus-Single was -0.0105 with bootstrap 95% CI [-0.2526, 0.2211], 12 Team wins, 72 ties, 11 Single wins, and two-sided sign-test p=1.0. Across all 100 executed pairs, including invalid runs that still consumed resources, Team used 24.64% more tokens, cost 78.18% more, and was 3.5687 times slower. Durable accounting reconciled 542 model charges for USD 22.461065000; two indeterminate charges are conservatively represented by their full USD 0.817118750 reservations. No category met the preregistered failure-cluster threshold for another specialist. This is local live-provider evidence, not an unbounded swarm, public deployment, or production claim.

An additional unisolated `pytest` run exercised 1,632 collected tests and initially returned 1,617 passed, 7 skipped, and 8 failed. Two failures were stale six-pack Visual Learning expectations and passed after updating the manifest tests and generated Studio. The other six are not pilot regressions: four load retained Foundry embedding values from the local environment instead of test defaults, and two portfolio-benchmark tests deliberately require a clean Git worktree while this feature branch is dirty. They remain disclosed rather than relabeled as passes.

The retained seven-service local stack was hot-swapped with the candidate backend and frontend while preserving the existing PostgreSQL and Redis container identities. `local-stack.sh status` then returned `STATUS=ready`; gateway `/healthz` and `/readyz` returned HTTP 200, and health reported `hybrid_orchestration=enabled`. Authenticated browser QA at `http://cogentrex` observed the Auto/Single/Team selector and Agents tab, all six learning packs, the hybrid Present diagram, Study mind map and flashcards, an audio element at ready state 4, and the 112-second video at ready state 4. That browser pass established the local control surface and media path; the later 100-case benchmark above supplies the separate live multi-agent quality and cost evidence.

Background work uses migration `20260828_13`, atomic SQL claims, monotonic lease generations independent of retry counters, heartbeats, expiry recovery, bounded exponential retries, dead-letter, cancellation, manual retry, concurrent idempotency, owner/project-scoped APIs, readiness, and an owner-scoped dashboard inspector. Production job kinds are closed to effect-free `echo` and database-idempotent `run_export`; payloads reject PII/secrets and result metadata is disclosure-redacted.

Semantics are deliberately **at-least-once**, not exactly-once. In-process Python cannot forcibly terminate a coroutine that suppresses cancellation, so non-idempotent external-effect handlers are prohibited; harder process termination is delegated to the S8.7 sandbox boundary. No live PostgreSQL contention or multi-host worker claim is made. Integrated Mac backend candidate `98dbae5` passed 1,354 backend tests. Follow-up UI candidate `112d00a` passed Svelte check with zero diagnostics, 30 Vitest tests, a production build, and 21 Playwright tests. Independent backend, documentation, and final UI race blocker re-reviews returned `APPROVED`.

### Isolated sandbox runner and validated multimodal path

When optional execution is enabled, the backend preflights and uses only `SandboxRunnerClient` over a private Unix socket. The dedicated runner container is non-root, networkless, read-only, capability-free, no-new-privileges, PID/memory/CPU/tmpfs bounded, and receives neither the Docker socket nor a project mount. Child-only seccomp blocks network/control-socket access, process inspection/signals, process-group escape, and control-path mutation. Requests use strict bounded frames and one active slot; timeout, output cap, server cancellation, peer disconnect, and normal completion all terminate the process group. Final JSON encoding is measured and truncated below the protocol frame limit, and Compose `init` reaps orphaned descendants.

The authenticated sync and SSE image paths reject malformed/oversized Data URIs, strict-base64 failures, byte/MIME mismatches, oversized dimensions/pixel counts before pixel load, and oversized sanitized output before conversation persistence or provider execution. Accepted pixels are re-encoded to remove metadata and used transiently without global attachment accumulation. Deterministic E2E tests prove sanitized images reach the capturing runtime and OpenAI, Anthropic, and Ollama request builders; no external vision-provider observation is claimed.

Linux acceptance executed 1,360 backend tests before the final focused lifecycle regressions, followed by 25 focused sandbox/multimodal/deployment tests and a real Docker Compose smoke covering executable seccomp preflight, runtime flags, backend-to-runner execution, stdin backpressure deadlines, network/control-socket denial, shared-volume write denial, detached-child cleanup, timeout, output truncation, and JSON-escape framing. The smoke removed containers, networks, and volumes. Mac candidate `ffeada9` passed 1,366 tests with one expected Linux-only seccomp skip, 35 Vitest tests, Svelte check with zero diagnostics, a production build, and 21 Playwright tests. Independent final blocker re-review at `be28e7f` returned `APPROVED`. The result is local container isolation, not VM-grade hostile multi-tenant certification, live-provider evidence, public deployment, or a production SLO.

### Governed drift reports and reviewed optimization candidates

Cogentrex now compares owner/project-scoped, immutable evaluation cohorts using deterministic descriptive summaries for pass rate, score distribution, latency, token/cost, abstention, citation coverage, unsupported claims, and safety failures. Minimum sample checks and fixed warning thresholds are operational rules only; no p-value or statistical-significance claim is made.

Recorded evaluation identities derive model/provider from the completed source-run ledger and an internal evaluator config revision; the public API cannot override them. Migration 14 backfills historical cohorts with deterministic legacy identity when source rows exist and explicit `legacy-*-unresolved` markers otherwise. Unresolved cohorts are rejected from drift comparison.

Optimization candidates are bounded to prompt, policy, retrieval, or config revision records. Metadata uses per-type allowlists and deterministic PII/credential rejection. Exact human approval binds owner, project, candidate ID/version, target revision, purpose, and before/after evaluations. Promotion records the approved declared revision only: it does not modify runtime configuration, prompts, retrieval, providers, or model weights. Reject/approve closes alternate pending receipts; rollback remains a separate auditable transition.

Migration-level integrity includes composite scope foreign keys and SQLite/PostgreSQL append-only/state-machine triggers. PostgreSQL real acceptance passed upgrade to head, downgrade to revision 13, and re-upgrade with four active S8.8 triggers. macOS acceptance passed 1,371 backend tests with one expected Linux-only seccomp skip. The final UI gate passed 44 Vitest tests, Svelte check with zero diagnostics, production build, and 21 Playwright tests after fixing an accessible-label collision. Independent blocker re-review of `cb76b1e` returned `APPROVED` for stale busy-state handling and atomic approval reservation.

Limits: no autonomous optimization, no runtime mutation, no model training, no scheduler that generates candidates unattended, no live-provider quality claim, and no public deployment claim.

## Defensible summary

Cogentrex is an evidence-rich **local Agent Reliability Workbench**. Its strongest claims are policy/approval enforcement, durable run evidence, privacy boundaries, isolated optional execution, grounded evaluation, one constrained verifier child, governed MCP stdio integration, responsive inspection UI, and reproducible local operations/DR.

It is **not** a publicly deployed production platform. Real external-provider behavior, indexed vector serving, production traffic, SLOs, multi-host scaling, and cloud operations remain unverified or deliberately deferred.

The architecture and evidence thresholds for the six intentional capstone omissions are maintained in [Remaining Deferred Gaps](REMAINING-DEFERRED-GAPS.md).

## Claim policy

1. Record revision, environment and command.
2. Keep Exists/Wired/Tested/Observed/UI/Deployed independent.
3. Label mocks, fixtures and local smokes.
4. Never translate local Docker evidence into `Deployed: Yes`.
5. Do not claim pgvector, model quality, production readiness, parity, or green remote CI without direct evidence.
