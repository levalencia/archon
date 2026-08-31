# Skills and project instructions

> **Implementation status:** `deferred`
> **Status boundary:** Keyword-selected skills are injected into sync and streaming chat, and selected skill IDs appear in effective-context provenance. Filesystem project instructions, immutable content versions, scope ownership, and a precedence resolver are deferred until Archon has an authorized project-workspace model.
> **Reviewed revision:** current hardening branch
> **Used by module:** [Module 06-context-and-memory](../modules/06-context-and-memory/README.md)
> **Catalog ID:** `skills-project-instructions`

## Beginner explanation

Instructions tell an agent how to behave; a skill is a reusable packet of task guidance selected when relevant. A production system must state which instruction wins when system, organization, project, skill, and user directions conflict. Merely concatenating matching text is not an instruction governance model.

## Problem and mental model

Treat the boundary as a contract with explicit inputs, outputs, state, failure behavior, and evidence. The important question is not whether a similarly named class or file exists, but whether the behavior is wired into a real path and whether a test or observation proves it.

## Architecture and components

```mermaid
flowchart LR
    Project[Project instructions: absent] -.-> Resolver
    Skills[SkillRegistry] --> Resolver[Context assembly]
    User[User message] --> Resolver
    Resolver --> Model
    Resolver --> Provenance[Effective-context manifest with selected skill IDs]
```

## Startup and request sequence

```mermaid
sequenceDiagram
    Caller->>Registry: search(user message)
    Registry-->>Context: top-k skill text
    Context->>Model: system + selected skills + history + user
    Context-->>Caller: metadata-only selected skill IDs
    Note over Context,Model: Project-file precedence remains deferred
```

## Archon implementation and source walkthrough

The mapped symbols implement keyword skill selection in sync/SSE and record selected skill IDs in the effective-context manifest. Remote loading and mutable global registry remain bounded by existing URL/content checks. A filesystem project-instruction convention, immutable content revision, owner/project binding, and explicit precedence resolver are deferred until a trusted workspace model exists.

### Source symbols

| Source symbol | Role and boundary |
|---|---|
| [`backend/app/skills/registry.py:SkillRegistry.search`](../../../backend/app/skills/registry.py) | Ranks registered skills by keyword matches. |
| [`backend/app/routes/chat.py:chat`](../../../backend/app/routes/chat.py) | Adds relevant skill content to the synchronous request path. |
| [`backend/app/routes/stream.py:chat_stream_real`](../../../backend/app/routes/stream.py) | Searches skills and adds their content to streaming context. |
| [`backend/app/runtime/context_provenance.py:EffectiveContextManifest`](../../../backend/app/runtime/context_provenance.py) | Records selected skill IDs without persisting skill content. |

### Tests

| Test | Contract proved and limit |
|---|---|
| [`backend/tests/unit/test_skills_security.py::TestSkillRegistry`](../../../backend/tests/unit/test_skills_security.py) | Proves registry/search and remote-loading boundaries. |
| [`backend/tests/unit/test_context_provenance.py`](../../../backend/tests/unit/test_context_provenance.py) | Proves metadata-only selected skill IDs in effective-context evidence. |

### Evidence boundary

Current implementation dimensions are centralized in [Implementation Evidence](../../IMPLEMENTATION-EVIDENCE.md). Source/tests below are repository evidence; they are not public-deployment or production-certification evidence.

## Try it: bounded study exercise

From the repository root, inspect the mapped source and test, then run the named focused test with the project test environment if available. Confirm both the passing contract and this gap: Remote loading and mutable global registry lack a complete trust, ownership, version, and precedence contract.

**Done criteria:** identify the trust boundary, one proved behavior, and one unproved behavior without changing repository state.

## Risks, failures, and trade-offs

| Topic | Assessment |
|---|---|
| Principal risk | Untrusted or stale instructions can override intended behavior or leak across scopes. |
| Current gap/failure | Remote loading and mutable global registry lack a complete trust, ownership, version, and precedence contract. |
| Trade-off | Automatic selection is convenient; explicit pinned project instructions are more reproducible. |
| Evidence hygiene | Do not log secrets or hidden chain-of-thought; record revision, environment, command, and only redacted outcomes. |

## Lab vs production

The status is **deferred** for project-file instructions. Skill selection/injection and selected skill IDs are wired, but Archon has no trusted filesystem workspace to which AGENTS-style files could safely bind. Versioned content, owner/project scope, and precedence resolution resume only when that workspace model is authorized; this is not silently counted as implemented.

## Interview answer

> Instructions tell an agent how to behave; a skill is a reusable packet of task guidance selected when relevant. Archon wires keyword-selected skills into sync/SSE context and records selected skill IDs. Filesystem project instructions are explicitly **deferred** because the server product has no trusted project-workspace model yet; versioned content, ownership, and precedence must be designed together rather than implied by concatenation.

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

- **Module:** [Module 06-context-and-memory](../modules/06-context-and-memory/README.md)
- **Course-day map:** [AIAMastery Days 1–30 coverage](../course-concept-coverage.md)
- **Evidence:** [Implementation Evidence](../../IMPLEMENTATION-EVIDENCE.md)
- **Historical context only:** [Feature and Course Audit v2](../../FEATURE-AND-COURSE-AUDIT-V2.md)
