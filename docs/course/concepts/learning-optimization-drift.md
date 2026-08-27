# Learning, optimization, and drift

> **Implementation status:** `not-implemented`
> **Status boundary:** Archon can evaluate versioned recorded-run datasets, but it has no feedback-to-training loop, drift detector, champion/challenger promotion gate, or automatic optimization system.
> **Reviewed revision:** `6e3e13f`
> **Used by module:** [Module 09-evaluation-harness](../modules/09-evaluation-harness/README.md)
> **Catalog ID:** `learning-optimization-drift`

## Beginner explanation

Learning optimization uses measured outcomes to change prompts, models, retrieval, or policies. Drift is a change in inputs or performance over time. Running an evaluation once is measurement, not learning; changing production behavior requires versioning, review, and rollback.

## Problem and mental model

Treat the boundary as a contract with explicit inputs, outputs, state, failure behavior, and evidence. The important question is not whether a similarly named class or file exists, but whether the behavior is wired into a real path and whether a test or observation proves it.

## Architecture and components

```mermaid
flowchart LR
    Runs --> Dataset[Versioned evaluation data]
    Dataset --> Metrics
    Metrics -. absent .-> Drift[Drift detector]
    Metrics -. absent .-> Optimizer
    Optimizer -. absent .-> Gate[Human/policy promotion gate]
    Gate -. absent .-> Deployment
```

## Startup and request sequence

```mermaid
sequenceDiagram
    Operator->>Metrics: compare time windows/candidates
    Metrics->>Drift: detect significant change
    Drift->>Gate: evidence + proposed change
    Gate-->>Deployment: approve/reject/rollback
    Note over Operator,Deployment: Expected architecture; not Archon code
```

## Archon implementation and source walkthrough

This is an expected architecture, not a source walkthrough. Adjacent recorded evaluation is not an optimizer or drift monitor; no implementation exists for this concept. The diagram and sequence define the boundary a future design would need; they do not imply scheduled work.

### Source symbols

| Source symbol | Role and boundary |
|---|---|
| None | No Archon implementation is claimed for this concept. |

### Tests

| Test | Contract proved and limit |
|---|---|
| None | No implementation test is claimed; adjacent tests do not establish this concept. |

### Evidence boundary

There is no runtime evidence for this concept. Use the repository and current [implementation evidence](../../IMPLEMENTATION-EVIDENCE.md) to confirm the negative boundary; do not infer implementation from adjacent features.

## Try it: bounded study exercise

Code-reading exercise: search the repository for the missing components named in the gap. Confirm that adjacent features do not satisfy them. No service should be started and no data should be changed.

**Done criteria:** identify the trust boundary, one proved behavior, and one unproved behavior without changing repository state.

## Risks, failures, and trade-offs

| Topic | Assessment |
|---|---|
| Principal risk | Automatic optimization can reward proxies, amplify bias, contaminate evaluation data, or regress safety. |
| Current gap/failure | Adjacent recorded evaluation is not an optimizer or drift monitor; no implementation exists for this concept. |
| Trade-off | Manual evidence review is slower but safer; automation becomes worthwhile only with stable datasets and rollback. |
| Evidence hygiene | Do not log secrets or hidden chain-of-thought; record revision, environment, command, and only redacted outcomes. |

## Lab vs production

The status remains **not-implemented** at `6e3e13f`. Archon can evaluate versioned recorded-run datasets, but it has no feedback-to-training loop, drift detector, champion/challenger promotion gate, or automatic optimization system. Unit tests, manifests, or local observations do not prove external-provider parity, sustained load, public deployment, legal compliance, or a production SLO.

## Interview answer

> Learning optimization uses measured outcomes to change prompts, models, retrieval, or policies. Drift is a change in inputs or performance over time. Running an evaluation once is measurement, not learning; changing production behavior requires versioning, review, and rollback. In Archon the honest status is **not-implemented**: Archon can evaluate versioned recorded-run datasets, but it has no feedback-to-training loop, drift detector, champion/challenger promotion gate, or automatic optimization system.

## Self-check

1. What problem does this concept solve, and what nearby concept is it not?
2. Trace the diagram’s trust boundary and failure path.
3. Which mapped symbol/test proves current behavior, or why are the lists empty?
4. What exact gap prevents a stronger status?
5. Which risk would you test first before production use?

<details>
<summary>Answer guide</summary>

A good answer names the contract in the beginner explanation, follows the sequence, cites the exact table entry (or the explicit absence), repeats the status boundary, and chooses a risk from the table rather than claiming unrecorded behavior.

</details>

## Related concepts and modules

- **Module:** [Module 09-evaluation-harness](../modules/09-evaluation-harness/README.md)
- **Course-day map:** [AIAMastery Days 1–30 coverage](../course-concept-coverage.md)
- **Evidence:** [Implementation Evidence](../../IMPLEMENTATION-EVIDENCE.md)
- **Historical context only:** [Feature and Course Audit v2](../../FEATURE-AND-COURSE-AUDIT-V2.md)
