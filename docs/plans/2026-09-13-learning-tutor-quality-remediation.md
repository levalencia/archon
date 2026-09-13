# Learning Tutor Quality Remediation Plan

Date: 2026-09-13
Status: approved for full execution

## Goal

Improve the Contextual Visual Learning tutor against the frozen 90-case dataset without weakening grounding or changing the vector database. The target is not merely more HTTP successes: answers must retrieve the expected evidence, define unfamiliar concepts first, apply them accurately to Cogentrex, cite valid local/web evidence, and remain observable within explicit latency and token limits.

## Frozen baseline

Live Foundry evaluation on dataset v1:

- 90 attempted; 89 completed; one reproducible structured-output HTTP error.
- deterministic pass: 65/90;
- grounded/non-fallback: 75/90;
- citation requirement met: 71/90;
- pedagogical model-judge pass: 35/90;
- definition-first on basic cases: 19/30;
- median latency: 31.912 s; P95: 52.428 s;
- 409 supported claims and 928 rejected claims;
- 15 web evidence items retrieved across 10 cases; zero web citations accepted;
- 466,831 total provider tokens; cost unavailable because pricing was not configured.

The raw artifacts remain under `/private/tmp/cogentrex-full-eval/` and a sanitized baseline summary will be committed with this work.

## Non-negotiable constraints

- Preserve the conservative 90% lexical support threshold, numeric checks, hash binding, and sentence-scoped polarity.
- Local repository evidence remains authoritative for Cogentrex-specific claims.
- Official web evidence is ephemeral, allowlisted, HTTPS-only, SSRF-checked, and never promoted into the trusted corpus automatically.
- Do not introduce a new vector database without retrieval measurements proving SQL-JSON is the bottleneck.
- No raw model tokens may be presented as verified answer text.
- All behavior changes use RED → GREEN → REFACTOR.

## Acceptance targets

The post-change run uses the same 90 canonical questions, provider/model, local corpus, and contexts.

Required gates:

1. 90/90 requests complete without transport or structured-output errors.
2. No malformed provider JSON is misclassified as HTTP 404.
3. Expected-source diagnostics are present for every completed case: rank, score components, source kind, locator, and embedding space.
4. Basic definition-first model-judge pass improves from 19/30 to at least 24/30.
5. Overall grounded responses improve from 75/90 to at least 82/90.
6. Deterministic pass improves from 65/90 to at least 75/90 on unchanged dataset v1; known rubric-policy defects are reported separately, not silently edited.
7. At least one valid official web claim survives to a web citation in a required-web basic case.
8. Median latency does not regress; target <= 30 s. P95 target <= 50 s.
9. Complete backend, frontend, browser, security, image, live-provider, and local readiness gates pass.

Pedagogical target is directional rather than a merge blocker for hard cases: model-judge pass must improve overall, but its subjective score remains separate from deterministic acceptance.

## Phase 1 — Structured output and error semantics

Files:

- `backend/app/learning_tutor/workflow.py`
- `backend/app/learning_tutor/context.py`
- `backend/app/learning_tutor/service.py`
- `backend/app/routes/learning_tutor.py`
- corresponding unit/integration tests

Tasks:

1. Add a bounded second attempt when provider completion or local contract parsing reports malformed structured output.
2. Append a narrow repair instruction and accumulate token usage across attempts.
3. On repeated invalid output, return a controlled grounded fallback with explicit metrics rather than leaking parser detail.
4. Introduce a typed learning-context resolution error so only unknown context maps to HTTP 404.
5. Map provider/generation failures to sanitized HTTP 502 for JSON and sanitized SSE error events for streaming.
6. Record attempt count and structured-output failure category in metrics/run events.

## Phase 2 — Retrieval diagnostics and reranking

Files:

- `backend/app/learning_tutor/repository.py`
- `backend/app/learning_tutor/workflow.py`
- `backend/app/learning_tutor/evaluation.py`
- `backend/scripts/run_learning_tutor_benchmark.py`
- repository/workflow/evaluation tests

Tasks:

1. Preserve dense, lexical, context, exact-symbol, and final score components per result.
2. Add deterministic concept aliases for beginner abbreviations and colloquial forms: OOP, DI, factory, preflight, observability, policy, RAG, SSE, and chunking.
3. Add exact symbol/file/path matching for internal implementation questions.
4. Keep existing dense/lexical/context behavior for queries without aliases or symbols.
5. Expose safe retrieval diagnostics in tutor metrics and run events.
6. Extend benchmark reports with expected-source recall@1/@3/@10 and failure categorization.

## Phase 3 — Pedagogical structure and atomic claims

Files:

- `backend/app/learning_tutor/workflow.py`
- workflow tests and live acceptance cases

Tasks:

1. Classify simple definition questions deterministically.
2. Require the first section to be `Definition` and its first claim to define the requested concept without leading with Cogentrex implementation details.
3. Require a separate `How Cogentrex uses it` section for product-specific claims.
4. Require one sentence per claim and reduce maximum claim length.
5. Use fewer local candidates for simple definitions to reduce topic drift while retaining more candidates for implementation/system questions.
6. Preserve abstention when no evidence can support even one atomic claim.

## Phase 4 — Official web evidence

Files:

- `backend/app/learning_tutor/web_supplement.py`
- `backend/app/learning_tutor/workflow.py`
- web supplement/workflow tests

Tasks:

1. Replace the universal `FastAPI Starlette` suffix with concept-aware official-source queries.
2. Add official routes for Python/OOP/async, FastAPI DI, OpenTelemetry observability, MDN SSE, and relevant platform concepts.
3. Extract query-relevant sentences rather than the first arbitrary 2,000 page characters; preserve snippet fallback.
4. Record raw results, allowed results, extraction success, generated web claims, verified web claims, and cited web claims separately.
5. Keep all existing URL, DNS, redirect, and prompt-injection defenses.

## Phase 5 — Measured latency reduction

1. Record retrieval, web, provider, verification, persistence, and total durations.
2. Use an evidence/output budget based on question class: smaller for simple definitions, larger for implementation/system questions.
3. Do not add caches or concurrency until timings identify the bottleneck.
4. Re-run a focused latency sample after each change and retain before/after numbers.

## Phase 6 — Verification and release

1. Run focused unit/integration tests after each phase.
2. Run full backend suite, lint, format, Bandit, frontend check/test/build, and Playwright.
3. Run independent spec-compliance and security/quality reviews.
4. Commit on feature branch, push, open PR, wait for exact-head CI, merge, and hot-swap only affected local services.
5. Prove `local-stack.sh status`, `/healthz`, and `/readyz`.
6. Re-run all 90 cases with isolated shards.
7. Blind-score pedagogical quality and publish paired baseline-vs-candidate statistics with limitations and token/cost accounting.
