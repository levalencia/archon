# Capstone rubric

Score each dimension independently from **1 (insufficient)** to **4 (strong)**. Passing requires **3 or 4 in every dimension**; do not average away a missing evidence or honesty requirement.

| Dimension | 1 — Insufficient | 2 — Developing | 3 — Competent | 4 — Strong |
|---|---|---|---|---|
| **Conceptual understanding** | Uses key terms incorrectly or cannot trace the lifecycle. | Defines terms but conflates nearby mechanisms or misses boundaries. | Correctly explains the lifecycle and distinguishes ReAct, grounding, verification, evaluation, and resilience controls. | Explains interactions and failure states clearly to both beginners and engineers, using canonical concepts. |
| **Code traceability** | Claims have no repository anchors or cite only directories/files vaguely. | Names files but not exact symbols/tests, or links do not support the claim. | Each major claim maps to an exact source symbol and behavior-focused test. | Traces startup and request flow across contracts, implementations, persistence, and transports; bookmarks are verified at the revision. |
| **Executable evidence** | No actual run/inspection evidence, or fabricated/unsafe output. | A command/result exists but lacks revision, environment, done criteria, or scope. | Records revision, environment, exact command, observed result, cleanup, and what the evidence proves. | Triangulates focused test with safe runtime/persisted evidence and explains disagreements or failures without concealment. |
| **Trade-offs** | Presents choices as guarantees or names no costs/failure modes. | Names generic pros/cons without tying them to this design. | Explains at least two concrete design trade-offs, one failure mode/control, and residual risk. | Compares credible alternatives across safety, complexity, performance, operability, and migration implications. |
| **Communication** | Unstructured, inaccurate, over time, or exposes sensitive material. | Understandable but jargon-heavy, poorly paced, or missing an audience-appropriate narrative. | Uses problem → design → trace → evidence → trade-off → boundary; stays within time and handles questions clearly. | Adapts the same truthful architecture to 2/15/45-minute depth, uses diagrams effectively, and makes uncertainty easy to understand. |
| **Honesty and scope** | Fabricates output or claims production, provider parity, pgvector, generic reflection, swarm behavior, or quality without evidence. | Includes caveats only after overbroad claims or treats mocks/fixtures as live evidence. | Places lab-vs-production limits beside claims; labels mocks, fixtures, local evidence, and unknowns; says “not verified” when needed. | Proactively separates code, wiring, tests, direct observation, UI, deployment, scale, and quality evidence, and proposes a concrete verification next step. |

## Required capstone evidence

- sanitized artifact with revision and environment;
- architecture/request trace with one alternate or failure path;
- at least three exact source-symbol bookmarks and two exact behavior-test bookmarks;
- one actually executed bounded command, or an approved non-executable trace clearly labeled as such;
- observed result and cleanup;
- at least two trade-offs and two production gaps;
- a 15-minute presentation plus concise 2-minute summary;
- no secrets, private data, hidden chain-of-thought, or unsupported status claim.

## Assessor procedure

1. Verify links and ask the learner to open one symbol and one test.
2. Compare the recorded command/result with the stated claim; do not rerun against shared or unsafe resources.
3. Ask one failure injection, one design alternative, and one production-boundary question.
4. Score each row and cite one observed reason. Any level 1 in executable evidence or honesty requires a new submission, not compensation from presentation polish.
5. Return targeted remediation: canonical module/concept, source bookmark, focused test, and revised claim language.

## Suggested questions

- Where does the runtime, rather than the model, enforce this invariant?
- Which test would fail if the exact-binding or owner-scope rule were removed?
- What evidence proves behavior, and what is only configuration or code existence?
- What side effect could make a retry unsafe?
- What would be required to turn this local observation into an RTO/RPO, SLO, scale, or public-production claim?
