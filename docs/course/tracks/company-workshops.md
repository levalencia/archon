# Company workshops

> **Track status:** current at revision `3577b00`
> **Format:** eight 90-minute workshops; reading and concepts remain canonical in modules

Use the [instructor guide](../workshops/instructor-guide.md), [student guide](../workshops/student-guide.md), [exercise sheets](../workshops/exercises.md), private [solution guide](../workshops/solutions.md), and [capstone rubric](../workshops/capstone-rubric.md). Each session uses disposable local data and no real secrets.

## Eight-workshop program

| # | Learning outcome | Preread | Instructor demo | Learner exercise | Artifact | Self-check |
|---:|---|---|---|---|---|---|
| 1. Agent anatomy | Trace input → model → tool → evidence → stop | [Module 00](../modules/00-agent-anatomy/README.md), [glossary](../reference/glossary.md) | Walk [`AgentRuntime.run`](../../../backend/app/runtime/engine.py) with a scripted response | [E1 lifecycle map](../workshops/exercises.md#e1-lifecycle-map) | Annotated lifecycle map | Which decisions are model-driven and which are deterministic? |
| 2. Python boundaries | Explain OOP, Protocols, DI, and async composition | [Module 01](../modules/01-python-architecture/README.md) | Swap a provider double through `create_chat_runtime` | [E2 dependency trace](../workshops/exercises.md#e2-dependency-trace) | Dependency diagram | Does the runtime import a concrete provider? |
| 3. Bounded ReAct | Predict terminal behavior from budgets and responses | [Modules 02](../modules/02-typed-runtime/README.md) and [03](../modules/03-react-loop/README.md) | Run one completion and one exhausted loop | [E3 stop-reason matrix](../workshops/exercises.md#e3-stop-reason-matrix) | Runtime trace | Why is tool-error feedback not generic self-reflection? |
| 4. Governed tools | Trace schema → policy → approval → execution | [Modules 04](../modules/04-tools-and-schemas/README.md) and [05](../modules/05-policy-and-approvals/README.md) | Show allow, ask, deny, and mismatched binding | [E4 policy probe](../workshops/exercises.md#e4-policy-probe) | Decision/evidence table | What exact values bind an approval? |
| 5. Memory boundaries | Separate request, conversation, encrypted memory, and ownership | [Module 06](../modules/06-context-and-memory/README.md) | Inspect ciphertext and owner/project scoping | [E5 context boundary](../workshops/exercises.md#e5-context-boundary) | Data-boundary note | What may persist, and where is plaintext forbidden? |
| 6. Durable evidence | Read ordered run events and explain replay/fork/compare | [Module 07](../modules/07-run-ledger/README.md), [event catalog](../reference/event-catalog.md) | Query a run and events | [E6 evidence timeline](../workshops/exercises.md#e6-evidence-timeline) | Timeline with limitations | Does replay invoke a provider or tool? |
| 7. Grounding and evaluation | Distinguish retrieval, verification, citation, and post-run scoring | [Modules 08](../modules/08-rag-grounding/README.md) and [09](../modules/09-evaluation-harness/README.md) | Inspect SQL-JSON cosine result and recorded evaluation | [E7 grounded evaluation](../workshops/exercises.md#e7-grounded-evaluation) | Cited answer plus eval note | What does a passing fixture not establish? |
| 8. Reliability capstone | Select controls, demonstrate one failure, and defend boundaries | [Module 10](../modules/10-resilience/README.md), [operations track](operations-and-reliability.md) | Trigger a bounded failure and follow evidence | [E8 capstone](../workshops/exercises.md#e8-reliability-capstone) | 15-minute walkthrough and failure report | Can every claim be tied to source, test, observation, and scope? |

## Standard 90-minute rhythm

- 0–10: retrieval prompt and vocabulary check.
- 10–30: architecture explanation using canonical module links.
- 30–45: instructor demonstration with revision and command visible.
- 45–70: pairs complete the bounded exercise.
- 70–82: artifact review against done criteria.
- 82–90: self-check, limitation statement, and exit ticket.

## Completion

A learner completes the track after submitting all eight artifacts and a capstone scoring at least **3 in every rubric dimension**. Executable evidence may come from a documented local run; screenshots alone are insufficient. Never penalize an honest “not verified” when evidence is absent.
