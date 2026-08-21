# POCOCK-SKILLS-ADDITIONS.md — Matt Pocock's Engineering Skills Applied to Archon

**Source:** 10 skills from `github.com/mattpocock/skills` (engineering + productivity)
**Purpose:** Concrete improvements to Archon webapp plan using battle-tested engineering disciplines
**Created:** 2026-08-21

---

## Executive Summary

Matt Pocock's skills repo codifies **engineering disciplines** — not tools or frameworks, but *how* to think, build, review, and maintain software. After analyzing all 10 skills against the Archon plan (WEBAPP-PLAN.md + GOD-MODE-ADDITIONS.md), here are the highest-impact additions missing from our current approach:

1. **Deep Module Design** — Archon's module boundaries are layer-organized but not depth-optimized
2. **Vertical-Slice TDD** — Plan mentions TDD but doesn't enforce one-test-one-impl cadence
3. **Two-Axis Code Review** — No review discipline defined; Pocock's Standards+Spec split is immediately actionable
4. **Feedback-Loop Bug Diagnosis** — No bug workflow defined; critical for production maintenance
5. **Domain Modeling as Living Practice** — Plan lacks CONTEXT.md / glossary discipline
6. **Throwaway Prototypes** — No prototype workflow; critical for UI/UX and state model exploration
7. **Grilling for Design Decisions** — No structured challenge process for architecture choices
8. **Writing for Agents** — Archon's agent prompts need the same rigor as code
9. **Architecture Improvement Scanning** — No continuous codebase health discipline

---

## 1. Deep Module Design (from `codebase-design`)

### Core Principle
**Deep modules**: maximum behavior behind minimal interface. Measure depth as *leverage* (capability per unit of interface learned), not lines of code.

### Key Vocabulary (Use Exactly)
| Term | Definition | Replaces |
|------|-----------|----------|
| **Module** | Anything with an interface and implementation (scale-agnostic) | component, service, unit |
| **Interface** | Everything a caller must know (types + invariants + error modes + perf) | API, signature |
| **Seam** | Where you can alter behavior without editing in that place | boundary |
| **Adapter** | Concrete thing satisfying an interface at a seam | implementation (when at seam) |
| **Depth** | Leverage at the interface — behavior per unit of interface | — |
| **Locality** | Changes/bugs concentrate in one place, not spread across callers | — |

### What's Missing from Current Plan

**Gap 1: Archon's modules are organized by layer, not by depth.** The hexagonal architecture from GOD-MODE-ADDITIONS organizes by ports/adapters/domain, but doesn't ask "is each module *deep*?"

**Concrete additions:**

```
For every module in Archon, apply the deletion test:
  "If I delete this module, does complexity vanish (shallow/pass-through)
   or reappear across N callers (deep, earning its keep)?"

Modules that MUST be deep (lots of behavior, tiny interface):
  - CoordinatorAgent: callers say "handle this query" → all orchestration hidden
  - RAGPipeline: callers say "retrieve relevant context" → chunking/embedding/reranking hidden
  - SecurityGuard: callers say "check this input/output" → PII/injection/guardrails hidden
  - MemoryManager: callers say "remember/recall" → tiering/encryption/eviction hidden

Modules at risk of being shallow (watch for pass-through):
  - PlannerAgent: if it just forwards to LLM with a prompt, it's a thin wrapper
  - ValidatorAgent: if it just calls SecurityGuard, it's a middle-man
  - Individual route handlers: if they just call service layer, that's fine (adapters are naturally thin)
```

**Gap 2: No "one adapter = hypothetical seam, two = real" discipline.** Plan adds abstractions speculatively.

**Rule to add:** Don't introduce a seam (Protocol/Port) unless two adapters actually exist. The plan already has `MockLLM` + `FoundryAdapter` = two adapters = real seam ✓. But `notification_port.py` with only one adapter? Hypothetical — defer it.

**Gap 3: No internal vs external seam distinction.** A deep module can have internal seams (for its own tests) separate from its external seam (for callers). The RAG pipeline should have internal seams at chunker/embedder/reranker for unit testing, while presenting one external seam to the chat service.

### Phase Application
- **Phase 0:** Add depth review to PR checklist. Every new module gets the deletion test.
- **Phase 4 (Multi-Agent):** Ensure CoordinatorAgent is genuinely deep — one method (`handle_query`) hiding all orchestration.
- **Phase 8 (Polish):** Run `improve-codebase-architecture` scan for shallow modules.

---

## 2. Vertical-Slice TDD (from `tdd`)

### Core Discipline
RED → GREEN, one slice at a time. No horizontal slicing (writing all tests first). Each test is a **tracer bullet** responding to what the last cycle taught you.

### What's Missing from Current Plan

**Gap 1: Plan lists tests in batches per phase.** Phase 1 lists 4 test categories at the end. This is horizontal slicing — "write all tests, then implement." Pocock says this tests *imagined* behavior.

**Concrete change:**

```
WRONG (current plan style):
  Phase 1 Tests:
  - [ ] Unit: Agent ReAct loop with MockLLM
  - [ ] Unit: SSE streaming correctness  
  - [ ] Integration: FastAPI → Agent → MockLLM → Response
  - [ ] E2E: Playwright test of chat flow

RIGHT (vertical slice):
  Phase 1, Slice 1: Agent responds to simple query
    RED:   test_agent_returns_response_for_simple_query() → FAIL
    GREEN: Minimal CoordinatorAgent that calls LLM once → PASS
    
  Phase 1, Slice 2: Agent streams response via SSE
    RED:   test_sse_endpoint_streams_tokens() → FAIL  
    GREEN: Wire SSE endpoint to agent → PASS
    
  Phase 1, Slice 3: Agent uses ReAct loop for complex query
    RED:   test_agent_uses_tool_for_multi_step_query() → FAIL
    GREEN: Add tool calling to ReAct loop → PASS
    
  Each slice: one seam, one test, one implementation.
```

**Gap 2: No pre-agreed seams.** TDD skill says "write down the seams under test and confirm them before writing any test." Archon needs an explicit seam map.

**Seam map for Archon:**

```markdown
## Pre-Agreed Test Seams

| Seam | What's Behind It | Test Strategy |
|------|------------------|---------------|
| `CoordinatorAgent.handle_query()` | Full ReAct loop, tool dispatch, memory | Integration: MockLLM + real tools |
| `RAGPipeline.retrieve()` | Chunking, embedding, vector search, rerank | Integration: real pgvector, mock embeddings |
| `SecurityGuard.check_input()` | PII detection, injection prevention, guardrails | Unit: known-bad inputs |
| `SecurityGuard.check_output()` | PII redaction, content safety | Unit: known-bad outputs |
| `MemoryManager.store/recall()` | Tiered storage, encryption, eviction | Integration: real Redis + Postgres |
| `POST /api/chat/stream` | Full request lifecycle | E2E: HTTP client → SSE stream |
| Chat UI component | User interaction → API → display | E2E: Playwright |
```

**Gap 3: Anti-patterns not called out.** Plan should explicitly warn against:
- **Implementation-coupled tests:** Don't mock internal agent collaborators. Test through the seam.
- **Tautological tests:** Don't assert `response.status == 200` when the test creates valid input. Assert on *behavior*.
- **Refactoring in the loop:** Refactoring belongs to code review, not RED→GREEN.

---

## 3. Two-Axis Code Review (from `code-review`)

### Core Discipline
Every review runs **two independent axes in parallel**:
- **Standards axis:** Does code follow repo conventions + Fowler smell baseline?
- **Spec axis:** Does code implement what the spec/ticket asked for?

A change can pass one axis and fail the other. Reporting them separately prevents masking.

### What's Missing from Current Plan

**Gap: No review discipline defined at all.** The plan has CI (lint, typecheck, test) but no human/agent review process.

**Concrete additions:**

```markdown
## Code Review Process (Add to Phase 0)

### Standards Sources
1. `CODING_STANDARDS.md` — project conventions (create in Phase 0)
2. Fowler smell baseline (always active):
   - Mysterious Name, Duplicated Code, Feature Envy
   - Data Clumps, Primitive Obsession, Repeated Switches
   - Shotgun Surgery, Divergent Change, Speculative Generality
   - Message Chains, Middle Man, Refused Bequest

### Review Workflow
1. Pin fixed point: `git diff main...HEAD`
2. Identify spec source (ticket/issue)
3. Run Standards review: violations + smell baseline against diff
4. Run Spec review: missing requirements, scope creep, wrong implementation
5. Report both axes independently

### Self-Review Checklist (Before PR)
- [ ] Every new module passes deletion test (not shallow)
- [ ] Tests are at pre-agreed seams only
- [ ] No implementation-coupled tests
- [ ] Domain terms match CONTEXT.md glossary
- [ ] No speculative generality (YAGNI)
```

**Create `CODING_STANDARDS.md` in Phase 0** with:
- Import ordering (stdlib → third-party → local)
- Naming: snake_case functions, PascalCase classes, UPPER_CASE constants
- Error handling: explicit exceptions with context, never bare `except:`
- Async: always `async def` for I/O, never blocking calls in async context
- Type hints: all public functions fully typed, use `Protocol` for interfaces
- Logging: structlog with correlation IDs, never `print()`

---

## 4. Feedback-Loop Bug Diagnosis (from `diagnosing-bugs`)

### Core Discipline
**Building the feedback loop IS the skill.** If you have a tight pass/fail signal for the bug, you will find the cause. Everything else (hypotheses, instrumentation, fixes) just consumes the loop.

### Phase: Production Maintenance & Debugging

**What's missing:** No bug workflow. When Archon breaks in production, what's the process?

**Add to project documentation:**

```markdown
## Bug Diagnosis Protocol

### Phase 1: Build a Feedback Loop (spend disproportionate effort here)
Priority order:
1. Failing test at the nearest seam
2. curl/HTTP script against dev server
3. CLI invocation with fixture input
4. Playwright script driving the UI
5. Replay captured trace (OTel spans → reproduce)
6. Throwaway harness (minimal subset of system)

Tighten the loop:
- Can I make it faster? (Skip unrelated init)
- Can I make the signal sharper? (Assert specific symptom)
- Can I make it deterministic? (Pin time, seed RNG)

### Phase 2: Reproduce + Minimize
- Confirm it's the SAME bug the user reported
- Shrink to smallest scenario that still goes red
- Every remaining element must be load-bearing

### Phase 3: Hypothesize (3-5 ranked, falsifiable)
Format: "If <X> is cause, then <changing Y> will make bug disappear"

### Phase 4: Instrument (one variable at a time)
- Debugger first, targeted logs second, never "log everything"
- Tag debug logs: [DEBUG-xxxx] for easy cleanup

### Phase 5: Fix + Regression Test
- Write regression test BEFORE fix (at correct seam)
- Watch it fail → apply fix → watch it pass
- Re-run original feedback loop

### Phase 6: Cleanup
- [ ] Original repro no longer reproduces
- [ ] Regression test passes
- [ ] All [DEBUG-...] instrumentation removed
- [ ] Hypothesis stated in commit message
```

**Archon-specific application:** The OTel trace viewer we're building becomes a **diagnostic superpower** — replay captured traces as bug reproduction loops.

---

## 5. Domain Modeling with CONTEXT.md (from `domain-modeling`)

### Core Discipline
Actively build and sharpen the project's domain model. Challenge terms, invent edge cases, write the glossary the moment terms crystallize.

### What's Missing from Current Plan

**Gap: No domain glossary.** The plan uses terms like "agent," "conversation," "memory," "tool" loosely. These need precise definitions.

**Create `/CONTEXT.md` in Phase 0:**

```markdown
# CONTEXT.md — Archon Domain Glossary

## Core Concepts

**Conversation**: A bounded sequence of Turns between a User and the System, 
persisted with encryption. Not "chat" or "thread" — a Conversation has exactly 
one owner User and one continuous context window.

**Turn**: A single User Message followed by a System Response. A Conversation 
is a sequence of Turns. Not "exchange" or "round."

**Message**: An atomic text payload within a Turn, either from User or System. 
Has a role (user/assistant/system/tool), content, and metadata.

**Agent**: An autonomous process that receives a Goal, reasons about it, and 
produces a Result by calling Tools. Not "bot" or "assistant" — an Agent has 
a defined capability contract and completion signal.

**Tool**: A deterministic operation an Agent can invoke. Has typed input/output 
schemas. Not "function" or "action" — a Tool is registered, sandboxed, and auditable.

**Query**: A User's information need expressed as a Message. Distinct from a 
Command (an instruction to perform an action).

**Retrieval**: The process of finding relevant Context from stored Documents 
for a given Query. Not "search" — Retrieval includes embedding, vector search, 
reranking, and filtering.

**Context**: Information fed to an Agent alongside a Query to ground its response. 
Includes retrieved document chunks, conversation history, and system instructions.
Not "prompt" (which is the full text sent to LLM).

**Document**: An uploaded file processed into Chunks for Retrieval. Has metadata 
(source, upload date, owner).

**Chunk**: A segment of a Document, sized for embedding and retrieval. Has a 
vector embedding and a reference back to its source Document.

**Trace**: A tree of Spans recording the execution of a single request through 
the system. OTel-standard. Not "log" — a Trace has structure (parent-child spans).

**Span**: A single timed operation within a Trace. Has a name, duration, 
attributes, and optional parent Span.

**Circuit Breaker**: A resilience pattern that stops calling a failing external 
service after N failures. States: CLOSED (normal), OPEN (blocking), HALF-OPEN (testing).

**Guardrail**: A check applied to Agent input or output that can block, modify, 
or flag content. Includes PII detection, injection prevention, content safety.
```

**Ongoing discipline:**
- When any new term emerges during development, add it to CONTEXT.md immediately
- When code uses a term differently than the glossary, surface the conflict
- CONTEXT.md is glossary ONLY — no implementation details, no specs

---

## 6. Throwaway Prototypes (from `prototype`)

### Core Discipline
A prototype is **throwaway code that answers a question**. Two branches:
- "Does this logic/state model feel right?" → Logic prototype (HTML demo)
- "What should this look like?" → UI prototype (route variations)

### What's Missing from Current Plan

**Gap: Plan jumps from design to implementation.** No exploration phase for risky decisions.

**Questions that need prototypes before building:**

```markdown
## Prototype Candidates

### P1: Agent Orchestration State Model (Logic)
Question: "Does the ReAct loop with multi-agent dispatch feel right?"
Build: Single HTML file with buttons to step through:
  - Query decomposition → Plan steps
  - Parallel agent dispatch → Results
  - Validation → Accept/Reject/Retry
  - Synthesis → Final answer
Answer needed before: Phase 1 implementation

### P2: Trace Viewer UX (UI)
Question: "What should the trace visualization look like?"
Build: 3 variations as Svelte route params:
  - ?variant=waterfall (Jaeger-style horizontal spans)
  - ?variant=flamegraph (nested call stacks)
  - ?variant=tree (collapsible tree with timing)
Answer needed before: Phase 5 implementation

### P3: Chat + Observability Split Screen (UI)
Question: "How should chat and traces coexist?"
Build: Variations:
  - ?variant=drawer (slide-out panel)
  - ?variant=split (side-by-side always visible)
  - ?variant=tab (switch between views)
Answer needed before: Phase 5 implementation

### P4: Memory Tier Transitions (Logic)
Question: "Does hot→warm→cold memory eviction feel right?"
Build: HTML demo showing messages aging through tiers:
  - Redis (hot) → PostgreSQL (warm) → Archive (cold)
  - Visualize what's in each tier as time passes
Answer needed before: Phase 6 implementation
```

**Rules:**
- Prototype goes in a branch, never main
- Name it obviously: `prototype-trace-viewer/`, not mixed into prod code
- No tests, no error handling, no abstractions
- Capture the *answer* (verdict + question settled) in the issue, then delete

---

## 7. Grilling for Design Decisions (from `grilling`)

### Core Discipline
Interview relentlessly until shared understanding. Map decisions as a **design tree**. Work in **rounds** — ask the full frontier (questions whose prerequisites are settled) in each round.

### What's Missing from Current Plan

**Gap: Architecture decisions are stated, not challenged.** The plan says "PostgreSQL for storage" without documenting the decision tree.

**Design decisions that need grilling:**

```markdown
## Decisions Requiring Grilling Sessions

### D1: Agent Framework Choice
Frontier questions:
- Use PydanticAI, LangGraph, or raw ReAct loop?
- How much framework lock-in is acceptable?
- Do we need graph-based orchestration or is sequential + parallel enough?

### D2: Vector DB Choice
- pgvector in Postgres vs. dedicated Qdrant?
- Performance requirements for retrieval (latency, scale)?
- Will we need metadata filtering on vectors?

### D3: Memory Architecture
- How many tiers? (Redis hot → Postgres warm → archive cold?)
- What triggers promotion/eviction?
- Encryption at rest vs. in transit vs. both?

### D4: Auth Strategy
- JWT + API keys for MVP, or full OAuth2 from start?
- Multi-tenant from day 1 or add later?
- Row-level security in Postgres — worth the complexity?

### D5: Deployment Target
- Docker Compose local → Azure App Service → ACA?
- Or straight to containers with Docker Compose for dev?
- Kubernetes manifests: real deployment or just "show we can"?
```

**Process:** For each decision, run a grilling session:
1. List frontier questions (those whose prerequisites are settled)
2. Provide recommended answer for each
3. Wait for user decision
4. Recompute frontier, ask next round
5. Done when frontier is empty

---

## 8. Writing Agent Prompts as Documents (from `writing-for-agents`)

### Core Discipline
Agent-consumed documents (prompts, skills, AGENTS.md) follow the same principles as code: **progressive disclosure**, **leading words**, **pruning**, **no negation**.

### What's Missing from Current Plan

**Gap: Agent system prompts are treated as strings, not engineered documents.**

**Concrete additions:**

```markdown
## Agent Prompt Engineering Principles

### 1. Information Hierarchy
Every agent prompt has:
- **Steps**: ordered actions the agent performs (primary)
- **Reference**: rules/facts consulted on demand (secondary)
- **Disclosed reference**: pushed to tool descriptions, loaded on demand

### 2. Leading Words
Use compact concepts that anchor behavior:
- "tracer bullet" — one test proving the full path works
- "tight loop" — fast, deterministic feedback cycle
- "deep module" — lots of behavior behind small interface
- "seam" — where behavior can be altered without editing

### 3. Context Pointers
Agent tool descriptions ARE context pointers. They must:
- Front-load the triggering word
- One trigger per branch (no synonym bloat)
- State what the tool does AND when to use it

### 4. Pruning Rules
- Each fact appears in ONE place (single source of truth)
- Don't restate what the environment provides (tool schemas, config)
- Delete no-ops (instructions the model already follows by default)
- Hunt for negation ("don't do X") and replace with positive ("do Y instead")

### 5. Apply to Archon Agent Prompts
The Coordinator agent's system prompt should be written as a skill document:
- Steps: how to handle a query (decompose → retrieve → validate → synthesize)
- Reference: when to use each tool, quality criteria
- Completion criteria: explicit and checkable, not "produce a good answer"

Example completion criterion:
  VAGUE: "Provide a helpful answer"
  SHARP: "Answer includes ≥1 citation, passes factual consistency check, 
          contains no PII, and was validated by the Validator agent"
```

---

## 9. Architecture Improvement Scanning (from `improve-codebase-architecture`)

### Core Discipline
Periodically scan the codebase for **deepening opportunities**: shallow modules that could become deep ones. Prioritize hot spots (recently changed files).

### What's Missing from Current Plan

**Gap: No continuous architecture health practice.**

**Add to development workflow:**

```markdown
## Architecture Review Cadence

### Weekly: Hot Spot Scan
1. `git log --oneline -50` — find files that keep changing
2. For each hot spot, apply deletion test
3. Look for: shallow modules, feature envy, shotgun surgery

### Per-Phase: Deepening Review
After each phase completion:
1. Spawn sub-agent to walk new code
2. Look for friction: "understanding this requires bouncing between many files"
3. Apply Fowler smells from code-review baseline
4. Generate candidates with before/after visualization
5. Pick one to deepen before starting next phase

### Signals of Shallow Modules
- Module's interface is nearly as complex as its implementation
- Pure functions extracted "for testability" but real bugs hide in how they're called
- Pass-through classes that just delegate
- Tests that mock everything (sign the seam is wrong)

### Deepening Checklist
For each candidate:
- [ ] Does it pass the deletion test? (If deleted, does complexity reappear in callers?)
- [ ] Are there two real adapters at this seam? (Not hypothetical)
- [ ] Can tests exercise behavior through the interface?
- [ ] Does the module name match CONTEXT.md vocabulary?
```

---

## 10. Implementation Workflow (from `implement`)

### Core Discipline
Build from spec with TDD at seams. Run typechecking regularly. Review with two-axis code review when done.

### Archon Implementation Cadence

```markdown
## Per-Feature Implementation Loop

1. UNDERSTAND: Read spec/ticket. Read CONTEXT.md for domain terms.
2. AGREE SEAMS: Write down which seams this feature tests at. Confirm.
3. TDD LOOP (vertical slices):
   a. RED: Write one failing test at agreed seam
   b. GREEN: Minimal implementation to pass
   c. Repeat for next slice
4. TYPECHECK: Run mypy after every 2-3 slices
5. SINGLE FILE TESTS: Run test file after each slice
6. FULL SUITE: Run once when feature complete
7. REVIEW: Two-axis review (Standards + Spec) on the diff
8. COMMIT: To current branch with clear message

## Per-Phase Completion
1. All slices pass
2. Full test suite green
3. mypy clean
4. Two-axis review complete
5. CONTEXT.md updated if new terms introduced
6. Architecture scan for new shallow modules
```

---

## Consolidated: Additions by Project Phase

### Phase 0: Foundation (Week 1)
- [ ] Create `CONTEXT.md` with domain glossary (Section 5)
- [ ] Create `CODING_STANDARDS.md` for review baseline (Section 3)
- [ ] Create `docs/adr/` directory with ADR-001 (modular monolith decision)
- [ ] Define pre-agreed test seam map (Section 2)
- [ ] Add depth review to PR checklist (Section 1)
- [ ] Write bug diagnosis protocol in `docs/BUG-PROTOCOL.md` (Section 4)

### Phase 1: Core Agent (Weeks 2-3)
- [ ] **Prototype first:** P1 — Agent orchestration state model (Section 6)
- [ ] Rewrite test plan as vertical slices, not batch (Section 2)
- [ ] Ensure CoordinatorAgent is deep: one `handle_query()` method (Section 1)
- [ ] Write agent system prompt as engineered document (Section 8)
- [ ] Grill: Agent framework choice (PydanticAI vs raw) (Section 7)

### Phase 2: Security (Week 4)
- [ ] SecurityGuard as deep module: one `check()` seam hiding all security logic (Section 1)
- [ ] Vertical-slice TDD for each security probe (Section 2)
- [ ] Update CONTEXT.md with security domain terms (Section 5)

### Phase 3: RAG Pipeline (Weeks 5-6)
- [ ] **Prototype first:** P4 — Memory tier transitions (Section 6)
- [ ] RAGPipeline as deep module: internal seams at chunker/embedder/reranker (Section 1)
- [ ] Grill: pgvector vs. Qdrant decision (Section 7)
- [ ] Vertical-slice TDD: naive RAG → hybrid search → reranking (Section 2)

### Phase 4: Multi-Agent (Week 7)
- [ ] Apply deletion test to PlannerAgent, ValidatorAgent (are they shallow?) (Section 1)
- [ ] Each agent implements UniformTool interface (from GOD-MODE-ADDITIONS)
- [ ] Grill: sequential vs. DAG execution model (Section 7)

### Phase 5: Observability (Week 8)
- [ ] **Prototype first:** P2 — Trace viewer UX, P3 — Chat+traces split (Section 6)
- [ ] Write trace viewer as deep module with small interface (Section 1)

### Phase 6: Memory (Week 9)
- [ ] Grill: memory tier architecture (Section 7)
- [ ] MemoryManager as deep module: `store()` and `recall()` hide all tiering (Section 1)

### Phase 7: Evaluation (Week 10)
- [ ] Apply two-axis review to all existing code (Section 3)
- [ ] Architecture improvement scan: find and deepen shallow modules (Section 9)

### Phase 8: Polish + Deploy (Weeks 11-12)
- [ ] Full architecture scan with HTML report (Section 9)
- [ ] Final CONTEXT.md review — all terms precise? (Section 5)
- [ ] Final code review: Standards + Spec on full diff from initial commit (Section 3)
- [ ] Bug diagnosis protocol tested with planted bugs (Section 4)

---

## Key Insights: What Pocock Gets Right That Most Plans Miss

1. **"Building the feedback loop IS the skill."** — Not hypothesizing about bugs, not reading code. The loop comes first, always.

2. **"Test only at pre-agreed seams."** — You can't test everything. Agreeing seams up front lands effort on critical paths.

3. **"One adapter = hypothetical seam. Two = real."** — Don't abstract speculatively. Wait for the second implementation.

4. **"The deletion test."** — Imagine deleting the module. If complexity reappears in callers, it was deep. If it vanishes, it was pass-through.

5. **"Vertical slices, not horizontal."** — One test → one implementation → repeat. Each test responds to what the last cycle taught you.

6. **"Refactoring is NOT part of the RED→GREEN loop."** — It belongs to code review. Don't mix building with polishing.

7. **"A prototype is throwaway code that answers a question."** — The question decides the shape. No question = no prototype.

8. **"Prompt the positive."** — Never steer agents by prohibition. State the target behavior so the banned one is never spoken.

9. **"Leading words recruit priors."** — Use compact concepts (tight, deep, seam, red) that anchor agent behavior in fewer tokens.

10. **"CONTEXT.md is glossary ONLY."** — No implementation details, no specs, no scratch notes. Pure domain vocabulary.
