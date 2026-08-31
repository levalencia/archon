# Archon NotebookLM Promptbook

These prompts turn curated, public Archon documentation into learning artifacts. NotebookLM output is derivative study material, not canonical evidence.

## Source priority and non-negotiable boundaries

Include this instruction in every artifact customization field:

```text
Use only the selected Archon sources. When sources differ, prioritize IMPLEMENTATION-EVIDENCE.md, then CAPABILITY-ACCEPTANCE.yaml, then REMAINING-DEFERRED-GAPS.md, then ARCHITECTURE-DIAGRAMS.md, then course material.

Never claim public production deployment, provider-live embeddings, native JSON Schema parity, Jaeger/Azure Monitor tracing, autonomous production optimization, or real inference when the evidence only shows deterministic mock execution. Distinguish process health, dependency readiness, user-facing functionality, and provider-live evidence. Explicitly identify implemented, partial, local-only, and deferred boundaries.
```

## Audio Overview — system deep dive

Recommended notebook: `system-overview`

```text
Create a 12–15 minute deep-dive conversation for a software engineer learning Archon.

Explain the problem Archon solves, its five architectural layers, the lifecycle of one user request, how policy and approvals govern tools, how the Run Ledger preserves evidence, and how evaluation and observability differ.

Use concrete analogies, but do not invent functionality. Explicitly distinguish infrastructure health from agent functionality, mock mode from Foundry live inference, local deployment from production deployment, and code existence from observed evidence.

After every major section, pose one reflection question. Finish with five statements that Luis should be able to explain in an interview.
```

Settings: `Deep Dive`, `Long`, preferred learning language.

## Audio Overview — technical debate

Recommended notebook: `memory-rag-evaluation`

```text
Create a technical debate between two senior AI engineers.

Engineer A argues that similarity retrieval is enough for useful RAG. Engineer B argues that retrieval similarity is not proof and that grounding, citations, and faithfulness require separate evaluation.

Use Archon's actual chunking, embedding, retrieval, grounding, citation, and evaluation boundaries. Discuss mock versus provider-live embeddings. End with a shared checklist for deciding whether an answer is trustworthy.
```

Settings: `Debate`, `Long`.

## Video Overview — request lifecycle

Recommended notebook: `request-lifecycle`

```text
Create a whiteboard-style technical explainer following one user request through Archon.

Show these stages in order:
Browser → Gateway → Authentication → Runtime → Model decision → Policy → Approval when required → Tool execution → Run Ledger → Evaluation → Workbench result.

Every arrow must name the data or decision crossing the boundary. Highlight ownership checks, effect gates, idempotency, persisted evidence, and failure stop points. Use progressive disclosure and no more than eight active components per scene.
```

Settings: `Explainer`, `Whiteboard`.

## Slide Deck — engineering walkthrough

Recommended notebook: `system-overview` or `interview-demo`

```text
Create a detailed presenter deck for a 15-minute Founding AI Engineer walkthrough of Archon.

Use 12–15 slides:
1. Problem and design goals
2. System boundary
3. Architecture layers
4. Request lifecycle
5. Typed bounded runtime
6. Tool contracts
7. Policy and approvals
8. Memory and RAG
9. Run Ledger and evidence
10. Evaluation and observability
11. Security and sandboxing
12. Local deployment and readiness
13. Verified evidence
14. Known limitations
15. Engineering trade-offs

Each slide must communicate one message, prefer diagrams over paragraphs, include presenter notes, and identify source grounding. Never promote partial or deferred capabilities to implemented.
```

Settings: `Presenter`, default length. Create a second `Detailed` version only after review.

## Infographic — governed tool execution

Recommended notebook: `request-lifecycle`

```text
Create a detailed landscape infographic titled “How Archon Executes a Tool Safely.”

Show a left-to-right flow:
Structured model intent → schema validation → ALLOW/ASK/DENY policy → durable approval binding → idempotency/effect control → isolated execution → structured result → Run Ledger evidence.

Use distinct visual styles for data flow, policy gates, persistent evidence, and failure paths. Add a bottom section titled “What this does not prove” containing the relevant limitations from the selected sources.
```

Settings: `Landscape`, `Detailed`.

## Mind Map

Recommended notebook: generate separately in each focused notebook. Do not select all five packs at once.

If customization is available:

```text
Organize first by runtime stage, then component, responsibility, evidence, and limitation. Do not organize by filename. Do not mix learning prerequisites with runtime calls. Keep relationship labels explicit and limit the first level to six branches.
```

If customization is unavailable, notebook scope and source selection are the control mechanism.

## Flashcards

Recommended notebook: any focused notebook, never the entire corpus.

```text
Generate understanding-focused flashcards:
- 40% component responsibility;
- 30% relationship or sequence;
- 20% trade-off or failure scenario;
- 10% evidence and limitation.

Each answer should explain why it is correct and name one common misconception. Include distinctions such as health vs readiness, mock vs live, retrieval vs grounding, replay vs re-execution, tool-error feedback vs generic reflection, and code existence vs observed evidence.
```

Settings: `Medium` or `Hard`, `More`.

## Quiz

Recommended notebook: any focused notebook.

```text
Create a hard scenario-based assessment for a senior Agentic AI engineer. Prefer architecture, debugging, and trade-off scenarios over vocabulary recall.

For every question provide one best answer, explain why it is correct, explain why distractors are wrong, and ground the explanation in selected sources.

Cover request lifecycle, governance, idempotency, memory boundaries, RAG grounding, evaluation, observability, sandboxing, readiness, and known limitations. Do not ask questions whose answer is unsupported by the selected sources.
```

Settings: `Hard`, `More`.

## Artifact acceptance rubric

Score every generated artifact from 1–5:

| Criterion | Question |
|---|---|
| Comprehension | Did Luis understand more after using it? |
| Structure | Is there a clear beginning, progression, and end? |
| Relationships | Are directions and relationship meanings explicit? |
| Accuracy | Are claims supported by selected sources? |
| Boundaries | Are partial, deferred, mock, local, and live states honest? |
| Interview value | Can Luis reuse the explanation professionally? |

Reject an artifact immediately if it invents production deployment, live-provider evidence, performance results, or capabilities not supported by canonical evidence.
