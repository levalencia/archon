# Archon Interview Answer Bank

Use these as concise, evidence-backed answers. Do not memorize them word for word; adapt them to the question.

## 1. What is Archon?

Archon is a local Agent Reliability Workbench. Its core workflow is `Policy → Run → Approval → Tool → Evidence → Evaluation`. I built it to make agent behavior inspectable: exact tool-call decisions, durable run events, grounded claims, evaluations, recovery and operations evidence. It is a portfolio system, not a publicly deployed production service.

## 2. Why did you avoid LangChain/AutoGen/CrewAI?

I wanted the reliability boundaries to remain explicit: typed provider ports, immutable tool calls, policy inputs, approval bindings, event schemas and persistence contracts. A custom runtime is more work, but it made failure modes and tests visible. I would use a framework when its lifecycle and contracts match the product, not to hide core control flow.

## 3. How do you prevent approval bypass?

Sync and SSE use the same runtime factory and policy engine. An approval binds user, run, native tool-call ID, canonical tool name and canonical argument hash. The runtime reserves before publishing the approval-required event, consumes a decision once, and re-verifies the binding immediately before execution. Missing authorizer, mutation, expiry, duplicate use and ownership mismatch fail closed.

## 4. How do you secure tools?

Tools register validated schemas, risk classes, resources, permissions, timeout and approval metadata. Arguments validate before permission/resource hooks. Filesystem tools use descriptor-relative traversal and reject traversal, symlinks, hard links and unsafe targets. Optional code/shell execution is Docker-only with no host fallback, network, host mounts or capabilities, and with non-root/read-only/resource limits.

## 5. How is memory isolated and encrypted?

Persistent memory is scoped to authenticated owner plus project. Values are encrypted with AES-GCM using derived context and authenticated associated data. Startup requires one canonical valid master key and fails closed. PII/credential redaction occurs before supported persistence/log paths. The honest limitation is that online key rotation is not implemented.

## 6. What makes the Run Ledger different from logs?

It is an owner-scoped domain record, not free-form operational logging. Runs have ordered append-only allowlisted events, terminal metadata, provider/model, stop reason, usage and lineage. APIs support stored-only replay, fork checkpoints, parent-child views and comparison. Replay cannot invoke a model or tool. It is not exact executable resume because arbitrary workspace state is not restored.

## 7. How do you keep RAG grounded?

Documents and chunks persist by owner/project. Retrieval returns evidence IDs tied to content hashes. The model emits structured claims with evidence IDs. A deterministic verifier checks citation existence, substantive overlap, negation, numbers and partial claims. Unsupported claims are excluded from the answer and recorded. Retrieval is SQL JSON cosine in Python—no pgvector claim.

## 8. How do you evaluate without fabricating A/B results?

Evaluations operate on recorded run IDs and versioned datasets. They read stored answers/evidence and persist metrics/reports; they do not generate fake alternate responses. Legacy fabricated A/B endpoints return 410. The portfolio benchmark separately labels itself deterministic local control-plane evidence, not model-quality evaluation.

## 9. Why one verifier child instead of a swarm?

One constrained specialist made the benefit measurable. The child receives only selected claims and evidence, no parent history or tools. It has real input/output/time/retry budgets, strict output validation and durable parent-child lineage. Malformed, failed, timed-out or over-budget output cannot mark a claim supported. Dynamic swarms would add complexity without demonstrated value.

## 10. How is MCP governed?

Archon uses the official MCP 2.1.1 stdio SDK. Server profiles are injected from an allowlist; user-provided commands/env/secrets are not persisted. Discovery follows pagination and stores owner/project inventory with tools disabled by default. Enabled tools become typed runtime definitions and still require normal policy/approval. Profile, health, enabled state and schema are rechecked just before call to close stale-inventory races.

## 11. What resilience controls exist?

The verified target uses Redis-backed per-user/IP rate limiting and dependency readiness. Provider calls share an app-scoped circuit breaker. The benchmark proves threshold opening, fail-fast rejection, half-open recovery and secondary fallback with sanitized errors. That is deterministic control-plane proof; I do not claim real-provider recovery under production traffic.

## 12. What did deployment testing find that unit tests missed?

Three useful failures: a native Apple ARM `cryptography` SIGILL, OTEL readiness that checked object existence rather than active export, and a PostgreSQL advisory-lock key containing NUL. I reproduced each, fixed the boundary, added regression coverage, and reran real Compose/DR. That reinforced a lesson: manifests and unit tests are not deployment evidence.

## 13. Why is the backend amd64 on Apple Silicon?

The native ARM image repeatedly exited 132 while importing `cryptography` before Uvicorn logging. The existing repository had the same known compatibility issue. For the verified local target I encoded `linux/amd64` explicitly rather than hiding it. It costs emulation performance, but makes the target reproducible until the ARM dependency issue is resolved.

## 14. How did you prove OpenTelemetry works?

I added the actual SDK and OTLP gRPC exporter as production dependencies, exposed active exporter state, failed readiness when configured telemetry is inactive, and flushed on shutdown. The local smoke creates a real agent run and waits for the exact `agent.run` span and service name in collector output. A running collector alone is not counted as proof.

## 15. Describe the DR design.

Backup uses a PostgreSQL custom-format dump with no owner/ACL, mode 0600, SHA-256 sidecar and metadata including UTC snapshot and Alembic revision. Restore verifies checksum and refuses a non-empty target unless destructive override is explicit. The DR smoke destroys source volumes, restores into a fresh project, starts the app and verifies restored auth, conversation, run/events, document/chunk and terminal approval by API and SQL hashes.

## 16. What were the measured DR results?

On one development Mac run with cached images: backup 0.343 seconds, restore-to-ready RTO 21.586 seconds, and zero changed records at the snapshot boundary. Those are reproducibility observations, not production SLOs. There is no PITR, remote backup store or multi-region failover evidence.

## 17. What does the benchmark prove?

Across 10 iterations per scenario, 30/30 passed. It proves a write-class call does not execute without authorization and executes once with exact approval; the breaker/fallback lifecycle works; and GroundedDocumentWorkflow excludes an unsupported overclaim while persisting terminal evidence. Tokens are scripted and external cost is zero. It does not measure model quality, throughput or production latency.

## 18. How do you prevent secrets in evidence?

Event payloads use allowlists and hashes instead of raw arguments/results where possible. Persistence redaction recursively handles credential-like fields and database URLs. MCP profiles avoid stored commands/env/secrets. Deployment/DR scripts generate temporary credentials, use mode-0600 files, never print values and clean by default. Evidence reports contain synthetic IDs/aggregates, not credentials.

## 19. Why local Compose instead of Azure/Kubernetes?

The goal was one verified target. Luis explicitly chose local-only and no cloud resource creation. Compose let me prove real PostgreSQL, Redis, OTEL, migrations, gateway, frontend/backend, DR and cleanup without cloud cost. Azure/Kubernetes artifacts without an executed deployment would be theater. The tradeoff is no public URL, managed secrets, autoscaling or cloud SLO evidence.

## 20. What would you do before production?

Choose and authorize one public target; use managed secrets/database/Redis; verify real model/search/embedding providers; add remote encrypted backups and PITR; define SLOs/alerts/load tests; resolve broad Mypy debt and dev dependency findings; run remote CI; add TLS/DNS/WAF and image scanning/signing; test rollback and key rotation; perform threat modeling and tenant isolation review under production traffic assumptions.

## 21. What are you most proud of?

The project became more truthful as it became more capable. I removed false pgvector, MCP stub, host sandbox, fake A/B and deployment claims; then replaced important ones with executable evidence. The strongest artifact is not a screenshot—it is the chain from policy decision through durable run evidence to evaluation and recovery proof.

## 22. What remains incomplete?

No public deployment or green remote CI rerun, no final external-provider acceptance, no indexed vector service, no online memory-key rotation, no production SLO/load evidence, and broad historical Mypy debt outside scoped ratchets. Legacy experimental multi-agent code exists but is not the product claim.

## STAR story: PostgreSQL DR failure

- **Situation:** Static tests and local app tests were green, but the first full DR seed failed during document ingestion.
- **Task:** Determine whether the DR harness or production data path was wrong without weakening assertions.
- **Action:** Added safe stage markers, retained one debug stack, inspected backend logs, found PostgreSQL rejecting a NUL advisory-lock key, replaced delimiter concatenation with canonical JSON tuple serialization, added a collision/NUL regression, and reran from clean volumes.
- **Result:** Full backup/destroy/restore passed with exact records/hashes, RTO 21.586 s and RPO 0 at snapshot.

## STAR story: truthful observability

- **Situation:** Compose included an OTEL collector and readiness said telemetry was configured.
- **Task:** Prove traces actually left the backend.
- **Action:** Found SDK/export dependencies missing and readiness based on object presence. Added pinned dependencies, active-state readiness, shutdown flush, and a smoke that creates a run and verifies `agent.run` in collector output.
- **Result:** Observability changed from configuration evidence to runtime evidence, while remaining explicitly local-only.
