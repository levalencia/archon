# Archon Evidence Guide

> **Audience:** Reviewers who want to understand what Archon proves without reading the full audit ledger.
> **Purpose:** Explain the evidence model and route readers to the supporting records.
> **Status:** Active summary. Exact capability status remains in the canonical sources linked below.

## Short version

Archon has deterministic tests, local runtime observations, and selected live-provider evidence. It has not been publicly deployed and makes no production-traffic or service-level claims.

The project treats these as different levels of proof. Code, tests, local execution, provider execution, and public deployment are never presented as equivalent.

## How capability claims work

Each capability is evaluated independently:

| Dimension | Question |
|---|---|
| Exists | Is there meaningful implementation? |
| Wired | Does a real application path use it? |
| Tested | Do automated tests exercise its contract? |
| Observed | Was it exercised in a local runtime? |
| UI | Can a user inspect or operate it? |
| Deployed | Was it verified outside the local machine? |

A capability can pass one dimension and fail another. For example, a tested integration is not automatically deployed.

## What the evidence covers

### Agent control plane

The evidence covers the typed runtime, execution budgets, policy decisions, approvals, tool contracts, run events, and bounded delegation. Tests verify failure behavior as well as successful paths.

### Data and grounding

The evidence covers owner-scoped persistence, encrypted memory, document ingestion, retrieval, citations, evaluation, and bounded verification. The technical ledger explains the retrieval implementation and its scaling limits.

### Integrations and isolation

The evidence covers governed MCP connections and the isolated sandbox path. Discovery, authorization, and execution remain separate controls.

### Operations

The evidence covers the managed local stack, health checks, telemetry, backup and restore, and deterministic reliability checks. These are local-development results, not public deployment evidence.

### Visual learning

The evidence covers generated learning packs, catalog validation, authenticated delivery, and the Present, Listen, and Study interfaces. Technical validation does not establish learning effectiveness or human acceptance.

## Evidence levels

Use the detailed records according to the question you are asking:

- **Current capability status:** [Capability Acceptance](implementation/CAPABILITY-ACCEPTANCE.yaml)
- **Technical evidence ledger:** [Implementation Evidence](IMPLEMENTATION-EVIDENCE.md)
- **Architecture and trust boundaries:** [Architecture Diagrams](ARCHITECTURE-DIAGRAMS.md)
- **Deferred scope:** [Remaining Deferred Gaps](REMAINING-DEFERRED-GAPS.md)
- **Recorded evidence artifacts:** [`docs/evidence/`](evidence/)

## What Archon does not claim

Archon does not claim:

- a public or cloud deployment;
- production traffic, service-level objectives, or on-call operation;
- a distributed multi-node agent network;
- GPU or high-throughput model serving;
- model training or fine-tuning;
- anonymous public sharing;
- autonomous, unapproved production optimization;
- independent learning-efficacy or security certification.

These boundaries are intentional. Closing one requires implementation, wiring, tests, direct observation, documentation, and deployment evidence where applicable.
