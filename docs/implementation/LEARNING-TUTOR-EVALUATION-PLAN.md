# Learning Tutor Evaluation and Improvement Plan

Status: active evaluation design. The 90-case dataset is structurally validated; only the six-case basic smoke has live-provider evidence so far.

## Objective

Make the tutor useful to a learner who may not know the project's vocabulary. A successful basic answer must:

1. define the term in plain language;
2. give a small mental model or example;
3. explain how Cogentrex uses the concept, when applicable;
4. cite local evidence for Cogentrex-specific statements;
5. use bounded official web evidence when the local corpus cannot support the general definition;
6. avoid the fallback when sufficient verified evidence exists.

## Evaluation matrix

The versioned dataset contains 30 basic, 30 medium, and 30 hard cases. Results must be reported by layer rather than collapsed into one opaque score.

| Layer | Question answered |
|---|---|
| Retrieval | Did expected local evidence reach the candidate set? |
| Grounding | Did supported claims survive verification with valid citations? |
| Pedagogy | Did the answer define unfamiliar terms before implementation details? |
| Product accuracy | Are Cogentrex statements consistent with code, tests, and declared limitations? |
| Source routing | Did general knowledge use official web evidence only when required or useful? |
| Operations | What were latency, provider errors, and cost? |

Deterministic checks cover fallback avoidance, grounding, citation count, web policy, and exact forbidden phrases. Definition quality, explanation clarity, nuanced misconceptions, and completeness remain explicit manual or model-judge dimensions.

## Initial live diagnostic

A six-case basic smoke covered OOP, dependency injection, factory, preflight, observability, and Cogentrex policy.

Verified result:

- 6/6 grounded responses;
- 3/6 passed every deterministic rule;
- 5/6 began with a useful plain-language definition on manual inspection;
- average latency 28.915 seconds;
- median latency 29.139 seconds.

The three deterministic failures were caused by required-web policy not being satisfied. OOP also failed the manual definition-first check because the answer started with Cogentrex implementation details.

## Prioritized improvements

### P0 — Grounding correctness

- Keep sentence-scoped polarity verification so unrelated negation elsewhere in a chunk cannot reject an exact supporting sentence.
- Preserve the global 90% lexical threshold, numeric checks, and mixed-polarity rejection.
- Add regressions for exact claims with wrong evidence IDs and for unrelated negation in long chunks.

### P1 — Beginner answer structure

- Enforce a dedicated definition section for basic `what is` questions.
- If local evidence describes only the Cogentrex implementation, obtain a bounded official definition before generation.
- Keep general definition and Cogentrex application as separate claims with separate citations.

### P1 — Web source routing

- Improve query construction for common foundational concepts such as OOP, dependency injection, observability, async programming, and SSE.
- Measure web retrieval, extraction, verifier acceptance, and final citation selection separately.
- Do not require a web citation when the curated local corpus already contains an adequate general definition; update case policy only from observed evidence, not convenience.

### P2 — Retrieval diagnostics

- Record retrieved source IDs, ranks, scores, kinds, and embedding space in benchmark output.
- Report expected-source recall at 1, 3, and 10.
- Use failures to decide between corpus changes, metadata aliases, ranking changes, or prompt changes.
- Do not add another vector database unless retrieval measurements identify SQL-JSON as the limiting component.

### P2 — Full benchmark progression

1. Run all 30 basic cases.
2. Fix systemic failures and rerun the same frozen dataset.
3. Run the 30 medium cases.
4. Run the 30 hard cases only after basic and medium gates are stable.
5. Compare versions with identical provider, model, corpus revision, context, and rubric.

A timeout, HTTP success, retrieved source, or model-generated citation is not automatically a pass.
