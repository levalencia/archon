# Remaining Deferred Gaps

**S8.10 candidate boundary:** documentation at repository candidate `440f08e`; this page does not record an S8.10 gate run or declare S8.10 complete.

Archon is an evidence-rich **local Agent Reliability Workbench**. The omissions below are deliberate product and evidence boundaries, not hidden implementation promises. `Deferred` means outside the current capstone scope with no delivery date. A nearby file, manifest, test double, or local observation does not change that status.

## How to use this register

For every gap, distinguish architecture artifacts from exercised capability. Status changes require the named architecture **and** revision-scoped evidence from the environment in which the claim will be made. The [implementation evidence matrix](IMPLEMENTATION-EVIDENCE.md) remains canonical for mutable capability status; the [course concept catalog](course/concept-catalog.yaml) maps these boundaries into the curriculum.

## Summary

| Deferred gap | Current adjacent capability | Missing claim |
|---|---|---|
| Distributed multi-node agent network | One signed, bounded, evidence-only verifier child; durable local jobs | Cross-node agent orchestration |
| GPU/high-throughput serving | Provider adapters and bounded local runtime | Model-serving capacity or GPU operation |
| Fine-tuning/training | RAG, skills, prompts, evaluations, reviewed revision candidates | Any model-weight training or promotion pipeline |
| Public/cloud/Kubernetes deployment | Hardened loopback Compose; historical K8s/Helm artifacts | A working public or cloud deployment |
| Public anonymous sharing | Immutable scanned exports and authenticated recipient-bound grants | Anonymous Internet disclosure |
| Autonomous unapproved production optimization | Drift reports and human-approved recommendation records | Automatic production mutation |
| Filesystem project instructions | Keyword-selected runtime skills with selected IDs in context provenance | Trusted project workspace, immutable instruction versions, scope ownership and precedence |
| Organization-approved RTO/RPO and cloud recovery | Checksummed local backup/restore drill with measured observations | Adopted objectives, off-site/PITR/cloud topology, repeated drills and accountable owner |

## 1. Distributed multi-node agent network

### Why it is out of scope

The capstone needs an inspectable delegation boundary, not a swarm. Archon deliberately limits active delegation to one evidence-only child with signed scope, bounded resources, no tools, and durable lineage. Multi-node coordination would introduce network partitions, duplicate delivery, version skew, peer identity, and distributed cancellation without improving the capstone's central policy-and-evidence demonstration.

### Architecture required

- a durable broker or queue with delivery, lease, retry, dead-letter, and backpressure semantics;
- service discovery and version/capability negotiation for remote workers;
- workload identity, mutually authenticated transport, key rotation, and tenant isolation;
- idempotency/effect receipts, distributed cancellation, heartbeats, and stale-worker fencing;
- cross-node tracing and lineage plus reconciliation after partitions;
- an explicit consistency model and operator procedures for partial failure.

### Evidence that would change the status

A status review would require multi-host tests with real network boundaries; injected loss, delay, duplication, partition, worker crash, and version skew; proof that authorization and tenant scope survive every hop; duplicate-side-effect and cancellation evidence; and sustained multi-node observation with redacted traces, recovery measurements, and an adopted operating runbook. In-process tasks or multiple containers on one host are insufficient.

### Why omission strengthens the capstone

It keeps authority narrow and failures reproducible. The learner can inspect every parent/child edge and prove the child cannot expand its scope instead of presenting a broad swarm whose correctness and security are unevidenced.

## 2. GPU and high-throughput model serving

### Why it is out of scope

Archon demonstrates a provider-neutral reliability control plane. It is not a model-serving data plane, and local benchmark timings are not capacity evidence. GPU kernels, batching, cache topology, and fleet economics are a separate specialization from policy, approvals, run evidence, and evaluation.

### Architecture required

- a serving engine with model loading, tensor/GPU placement, quantization policy, and memory isolation;
- token-aware admission control, continuous/dynamic batching, streaming backpressure, and fairness;
- queue limits, overload rejection, deadline propagation, cancellation, and tenant quotas;
- model/KV-cache lifecycle management and safe rollout/rollback;
- accelerator telemetry, autoscaling signals, capacity planning, and failure-domain design.

### Evidence that would change the status

Required evidence includes identified hardware and model revisions; reproducible load profiles; request and token throughput; p50/p95/p99 time-to-first-token and inter-token latency; queue depth, rejection, cancellation, memory pressure, and failure recovery; multi-tenant fairness; quality parity after quantization; and sustained soak/cost results against adopted SLOs. An HPA manifest, API concurrency test, or external-provider latency does not qualify.

### Why omission strengthens the capstone

It prevents control-plane evidence from being mislabeled as inference infrastructure. The project can make strong, testable reliability claims while remaining portable across providers and development machines.

## 3. Fine-tuning and training

### Why it is out of scope

RAG, prompts, skills, evaluation, and revision recommendations adapt runtime behavior without changing model weights. A training pipeline would require data governance and model lifecycle controls beyond the capstone and would distract from the inspectable, reversible mechanisms already demonstrated.

### Architecture required

- consent, license, provenance, retention, deletion, PII, and poisoning controls for datasets;
- immutable dataset/version lineage and train/validation/test separation;
- reproducible trainer jobs, accelerator scheduling, checkpoints, experiment tracking, and supply-chain records;
- a model/adapter registry with evaluation, safety, cost, compatibility, and human promotion gates;
- staged deployment, canary comparison, monitoring, rollback, and data/model incident response.

### Evidence that would change the status

The status would require a reproducible training run from an approved versioned dataset to a checksummed model artifact; privacy/license review; contamination and safety tests; held-out quality and regression results; cost/resource accounting; registry lineage; explicit promotion; canary observation; and rollback rehearsal. A prompt edit, retrieved context, evaluation delta, provider-hosted model name, or recorded optimization candidate is not training evidence.

### Why omission strengthens the capstone

The current adaptation paths are easier to inspect, cite, revoke, and compare. Not claiming weight changes keeps the evidence chain understandable and avoids pretending that a tiny or synthetic dataset establishes general model improvement.

## 4. Public, cloud, or Kubernetes deployment

### Why it is out of scope

The selected and observed target is loopback-only local Compose. Historical Kubernetes and Helm files are design artifacts with placeholders; they are not a selected, hardened, or observed deployment. Public operation would add a materially different threat model, availability boundary, cost profile, and on-call obligation.

### Architecture required

- immutable signed images and provenance, a managed registry, and environment-specific configuration;
- a real cloud network/cluster, TLS/DNS ingress, WAF/rate controls, workload identity, and external secret management;
- migration jobs and compatibility policy for rolling versions;
- managed PostgreSQL/Redis, encrypted backups, restore/failover, and capacity controls;
- hosted telemetry, alerting, SLOs, incident response, vulnerability/patch workflow, and deployment rollback;
- Kubernetes render/schema/policy checks if Kubernetes is selected.

### Evidence that would change the status

Required evidence includes a named non-local environment and immutable revision/image digest; clean manifest rendering/policy checks; successful migration and rollout; authenticated TLS traffic through a public endpoint; owner isolation and security probes; secret-rotation behavior; load and failure testing; hosted telemetry/alerts; backup/restore and rollback drills; and resource teardown/cost records. YAML, local containers, CI, screenshots, or DNS alone do not establish deployment.

### Why omission strengthens the capstone

The local target is reproducible, inexpensive, and safe to exercise destructively. Keeping `Deployed: No` makes the claim ladder credible and lets reviewers reproduce the strongest controls without trusting an inaccessible cloud environment.

## 5. Public anonymous sharing

### Why it is out of scope

Archon implements immutable disclosure-scanned exports and expiring/revocable grants bound to an authenticated recipient and closed purpose. It intentionally exposes no anonymous share URL. Anonymous Internet access removes the recipient identity boundary and greatly increases leakage, scraping, abuse, indexing, and revocation risk.

### Architecture required

- a separately threat-modeled public edge and opaque, high-entropy capability URLs or another explicit anonymous authorization model;
- export-specific disclosure policy, owner preview/consent, minimization, and default expiry;
- atomic revocation, download/view limits, replay and enumeration resistance, and cache/CDN invalidation;
- public rate limiting, abuse detection, bot controls, takedown, audit, legal/privacy review, and incident response;
- a presentation format that excludes internal authorization, hidden reasoning, secrets, and unsafe active content.

### Evidence that would change the status

Status change requires adversarial tests for guessing, enumeration, replay, race-at-expiry/revocation, cache retention, active content, disclosure bypass, and cross-tenant access; external public-edge observation; abuse/rate-limit and audit evidence; owner consent and takedown flows; and a documented privacy/legal decision. Authenticated recipient redemption and a locally returned token do not qualify.

### Why omission strengthens the capstone

Recipient-bound authentication makes disclosure attributable and revocable while preserving the export integrity lesson. The capstone demonstrates safe sharing controls without turning a portfolio feature into an unaudited public data-hosting service.

## 6. Autonomous unapproved production optimization

### Why it is out of scope

Archon records descriptive drift reports and bounded prompt/policy/retrieval/config recommendations. Exact human approval is required, and “promotion” records evidence only; it does not mutate runtime configuration. An unattended optimizer would combine noisy measurements with production authority and could amplify regressions, cost, bias, or security failures.

### Architecture required

- representative online/offline metrics with identity, data-quality, delayed-outcome, and uncertainty handling;
- a constrained optimizer with an explicit action space, budget, safety invariants, and conflict controls;
- signed configuration/model artifacts and a separate deployment controller;
- shadow/canary rollout, holdouts, automatic rollback, kill switch, blast-radius limits, and change windows;
- tamper-resistant audit, independent policy approval, alerting, and accountable operator ownership.

### Evidence that would change the status

Required evidence includes pre-registered success and safety criteria; representative datasets/traffic; repeated shadow and canary trials; proof of hard action/budget limits; adversarial metric-gaming and poisoned-feedback tests; automatic rollback and kill-switch drills; complete audit lineage; and explicit governance authorizing unattended changes. A drift warning, approved candidate, promotion record, scheduler, or improved synthetic fixture does not qualify.

### Why omission strengthens the capstone

Human approval and non-mutating promotion make the safety boundary obvious: the system recommends and records, while accountable operators change production. This directly reinforces the capstone thesis that model- or metric-generated text never grants mutable authority.

## 7. Filesystem project instructions

### Why it is out of scope

Archon is currently a multi-user server application without an authorized project-workspace filesystem boundary. Treating arbitrary repository files as instructions would add path ownership, trust, injection, precedence, revision, and disclosure risks. Runtime skills remain implemented and their selected IDs are visible in effective-context provenance.

### Architecture and evidence required

A status review requires an owner/project-bound workspace model; allowlisted instruction filenames; descriptor-relative path containment; immutable content hashes and revisions; deterministic precedence across system, organization, project, skill, and user instructions; conflict/failure behavior; context-provenance exposure; cross-user isolation tests; and sync/SSE acceptance. Merely reading `AGENTS.md` from the process working directory is insufficient.

## 8. Organization-approved RTO/RPO and cloud recovery

### Why it is out of scope

The local DR drill measures one checksummed dump/restore path, but observations are not business objectives. Public/cloud deployment remains deferred, so there is no selected production topology, failure domain, data-loss window, or accountable service owner against which an RTO/RPO promise could be adopted.

### Architecture and evidence required

A status review requires Luis or a service owner to adopt scoped objectives; select a production database/backup/PITR topology; define outage start and recovery completion; run repeated representative-volume drills including post-snapshot writes, key recovery, regional/provider failure, alerting and rollback; and retain signed drill history demonstrating compliance distributions rather than one local number.

## Candidate acceptance boundary

This S8.10 documentation candidate establishes an explicit map of intentional omissions and the evidence thresholds for reconsidering them. It does **not**:

- claim that an integrated S8.10 benchmark or final gate has run;
- convert local tests, fixtures, manifests, or historical evidence into live/provider/deployment evidence;
- assign a delivery date to any deferred item;
- change any `Deployed` value from **No**.
