# Generic self-reflection

> **Implementation status:** `not-implemented`
> **Status boundary:** Archon feeds tool errors back into its bounded ReAct loop and can run post-run evaluation or a verifier child, but it has no general reflection memory, critique/revision contract, or measured reflection policy.
> **Reviewed revision:** `6e3e13f`
> **Used by module:** [Module 03-react-loop](../modules/03-react-loop/README.md)
> **Catalog ID:** `generic-self-reflection`

## Beginner explanation

Generic self-reflection asks an agent to critique its own reasoning or result and revise it under a defined contract. Retrying after a tool error is local error recovery; a separate verifier is delegation; scoring after completion is evaluation. None alone proves a general reflection system.

## Problem and mental model

Treat the boundary as a contract with explicit inputs, outputs, state, failure behavior, and evidence. The important question is not whether a similarly named class or file exists, but whether the behavior is wired into a real path and whether a test or observation proves it.

## Architecture and components

```mermaid
flowchart LR
    Draft -.-> Critic[Reflection pass]
    Critic -.-> Decision{Revise?}
    Decision -.-> Revision
    Revision -.-> Eval[Measured outcome]
    ReflectionMemory[Bounded reflection memory] -.-> Critic
    Note[Expected architecture only] -.-> Critic
```

## Startup and request sequence

```mermaid
sequenceDiagram
    Runtime->>Critic: draft + allowed evidence + rubric
    Critic-->>Runtime: structured critique
    alt revision justified and budget remains
      Runtime->>Runtime: produce one bounded revision
    else stop
      Runtime-->>Caller: original result + evidence
    end
    Note over Runtime,Critic: Not implemented
```

## Archon implementation and source walkthrough

This is an expected architecture, not a source walkthrough. The misleadingly named reflexion test proves tool-error feedback/retry only; no generic critique/revision lifecycle exists. The diagram and sequence define the boundary a future design would need; they do not imply scheduled work.

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
| Principal risk | Unbounded reflection increases cost and latency and can amplify confident errors without independent evidence. |
| Current gap/failure | The misleadingly named reflexion test proves tool-error feedback/retry only; no generic critique/revision lifecycle exists. |
| Trade-off | Targeted verifier/evaluation steps are measurable; generic reflection is broader but harder to bound and validate. |
| Evidence hygiene | Do not log secrets or hidden chain-of-thought; record revision, environment, command, and only redacted outcomes. |

## Lab vs production

The status remains **not-implemented** at `6e3e13f`. Archon feeds tool errors back into its bounded ReAct loop and can run post-run evaluation or a verifier child, but it has no general reflection memory, critique/revision contract, or measured reflection policy. Unit tests, manifests, or local observations do not prove external-provider parity, sustained load, public deployment, legal compliance, or a production SLO.

## Interview answer

> Generic self-reflection asks an agent to critique its own reasoning or result and revise it under a defined contract. Retrying after a tool error is local error recovery; a separate verifier is delegation; scoring after completion is evaluation. None alone proves a general reflection system. In Archon the honest status is **not-implemented**: Archon feeds tool errors back into its bounded ReAct loop and can run post-run evaluation or a verifier child, but it has no general reflection memory, critique/revision contract, or measured reflection policy.

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

- **Module:** [Module 03-react-loop](../modules/03-react-loop/README.md)
- **Course-day map:** [AIAMastery Days 1–30 coverage](../course-concept-coverage.md)
- **Evidence:** [Implementation Evidence](../../IMPLEMENTATION-EVIDENCE.md)
- **Historical context only:** [Feature and Course Audit v2](../../FEATURE-AND-COURSE-AUDIT-V2.md)
