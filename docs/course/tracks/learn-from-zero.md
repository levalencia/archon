# Learn from zero

> **Track status:** current at revision `3577b00`
> **Audience:** programmers new to agent systems
> **Time:** 20–30 hours for the current modules, plus optional labs

This is a navigation route, not a second textbook. Follow the linked module and concept pages for canonical explanations. Check unfamiliar words in the [beginner glossary](../reference/glossary.md).

## Before you start

You need basic Python, HTTP/JSON, command-line, and Git familiarity. Start by reading the [syllabus prerequisites and evidence policy](../syllabus.md). You may do every reading and paper exercise without credentials. Executable labs require the setup named by their module.

## Route

| Stage | Read | Make | You are ready to continue when… |
|---|---|---|---|
| 1. What an agent is | [00 — Agent anatomy](../modules/00-agent-anatomy/README.md) | Lifecycle map | You can separate model, runtime, tools, policy, and evidence. |
| 2. How Python parts fit | [01 — Python architecture](../modules/01-python-architecture/README.md) | Dependency diagram | You can explain OOP, Protocol, DI, and async in plain English. |
| 3. How a run is represented | [02 — Typed runtime](../modules/02-typed-runtime/README.md) | Runtime trace | You can name inputs, state, output, and terminal result. |
| 4. How action stays bounded | [03 — ReAct loop](../modules/03-react-loop/README.md) | Bounded-loop trace | You can distinguish ReAct from generic self-reflection. |
| 5. How tools form contracts | [04 — Tools and schemas](../modules/04-tools-and-schemas/README.md) | Typed tool | You can trace validation before execution. |
| 6. How risky action is governed | [05 — Policy and approvals](../modules/05-policy-and-approvals/README.md) | Deny/ask/allow probe | You can explain exact binding and fail-closed behavior. |
| 7. What persists | [06 — Context and memory](../modules/06-context-and-memory/README.md) | Context-boundary note | You can separate request, conversation, and encrypted memory. |
| 8. How evidence becomes durable | [07 — Run Ledger](../modules/07-run-ledger/README.md) | Event timeline | You can explain replay/fork/compare limits. |
| 9. How answers use documents | [08 — RAG and grounding](../modules/08-rag-grounding/README.md) | Cited answer | You can separate retrieval, groundedness, faithfulness, and citation. |
| 10. How behavior is measured | [09 — Evaluation harness](../modules/09-evaluation-harness/README.md) | Recorded-run evaluation | You can state what a fixture proves and does not prove. |
| 11. How failures are bounded | [10 — Resilience](../modules/10-resilience/README.md) | Failure drill | You can choose retry, timeout, idempotency, breaker, fallback, or rate limit for a scenario. |

## Beginner checkpoints

After stages 1–4, explain one request using only boxes and arrows. After stages 5–8, add trust boundaries and durable evidence. After stages 9–11, add a measurable claim and one controlled failure. If you cannot answer a module self-check without reading its answer guide, revisit its linked concept rather than memorizing this route.

## Safe lab habits

- Copy `.env.example`; never commit a real token, password, document, or memory export.
- Prefer the mock/scripted provider when the exercise permits it.
- Use disposable local data and the exact cleanup step in each module.
- Record revision, command, environment, result, and limitation.
- Do not call local Compose “production,” JSON embeddings “pgvector,” or one verifier child a “swarm.”

## Next routes

- Present the system: [Interview preparation](interview-preparation.md).
- Learn with a cohort: [Company workshops](company-workshops.md).
- Operate the local target: [Operations and reliability](operations-and-reliability.md).
- Find implementation detail: [Code bookmarks](../reference/code-bookmarks.md), [API map](../reference/api-map.md), and [test map](../reference/test-map.md).
