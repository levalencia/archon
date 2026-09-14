# Visual Learning Vocabulary Evaluation

Status: local candidate evaluation for revision `53b62d73003a9d73abc40458e8ca870ce72e62b1`.

This report separates functional acceptance of the vocabulary system from its effect on Learning Tutor quality. It does not claim public deployment or production readiness. Aggregates are available in [`visual-learning-vocabulary-evaluation.json`](visual-learning-vocabulary-evaluation.json). Raw answers, authenticated run records, and blinded judge inputs remain local and are not committed.

## Decision

**Do not promote the combined candidate yet.**

The canonical catalog, generated glossary, Visual Learning UI, trusted Tutor context, and per-term indexing all pass their functional gates. Basic teaching improves under paired blind review. However, the full 90-case matrix does not show a global Tutor-quality improvement: deterministic pass, grounding, citation sufficiency, and expected-source recall all decline slightly or materially. The candidate therefore fails the global promotion gate.

A safe next candidate should either:

1. constrain vocabulary retrieval to explicit `vocabulary_id` context and definition-oriented questions while preserving prior ranking elsewhere; or
2. split the catalog/UI work from global Tutor retrieval behavior behind a controlled routing boundary.

That change must be driven by the seven regressed cases rather than a global weight adjustment.

## Implemented capability

The candidate provides:

- a canonical `vocabulary.yaml` with 299 terms and 540 aliases;
- generated Markdown with one heading-scoped entry per term;
- coverage of 67 official concepts, 37 evaluation concept IDs, and all 80 vocabulary labels declared by modules and concept pages;
- Visual Learning Studio schema v4 and `/learn?view=glossary`;
- search by term, alias, definition, Cogentrex application, category, and level;
- exact handling for short aliases such as `DI`;
- server-side validation of `vocabulary_id` rather than browser-supplied paths or text;
- one retrievable `visual:vocabulary:<id>` source per vocabulary entry;
- definition-oriented and explicit-vocabulary ranking signals.

The candidate index contained 3,901 sources and 5,044 chunks:

- 299 vocabulary sources;
- 64 review-ready video transcript segments;
- local `BAAI/bge-small-en-v1.5` embeddings with 384 dimensions;
- documentation revision `53b62d7` and media revision `33c56af` recorded separately.

## Deterministic gates

| Gate | Result |
|---|---:|
| Backend suite | 1,902 passed, 7 skipped |
| Frontend unit tests | 5 passed |
| Svelte check | 0 errors, 0 warnings |
| Production frontend build | PASS |
| Playwright desktop/mobile | 9 passed |
| Ruff format/check and Bandit | PASS |
| Vocabulary and Studio reproducibility | PASS |
| Course-document validation | PASS |

The retained baseline and isolated candidate both passed status, `/healthz`, and `/readyz` before valid live batches. The candidate used separate PostgreSQL and Redis storage. The retained stack was not replaced.

## Evaluation design

- Dataset: `backend/evals/learning_tutor/concepts-v1.json`, version 1.
- Cases: 90 — 30 basic, 30 medium, 30 hard.
- LLM: Foundry `claude-opus-4-6`.
- Embeddings: local `BAAI/bge-small-en-v1.5`, 384 dimensions.
- Runtime controls aligned before comparison: media enabled, web supplement enabled, verifier enabled, same verifier model and retries.
- Execution: one isolated user per difficulty, sequential requests.
- Baseline: the final 90-case artifact for merged revision `212e84f`; a current paired 12-case smoke also produced 12/12 deterministic and grounded results.
- Candidate smoke: 12/12 deterministic, 12/12 grounded, and zero errors after configuration alignment.
- Pedagogical review: randomized A/B labels, one blind reviewer per difficulty, 90 unique IDs validated before labels were revealed.

Two diagnostic batches were excluded:

1. Foundry embeddings returned HTTP 429 before any candidate corpus was persisted.
2. An initially misaligned candidate had media and web supplement disabled, producing 8/12 plus one HTTP 404.

Neither invalid batch is included in acceptance statistics.

## Full 90-case results

| Measure | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Deterministic pass | 80/90 | 79/90 | -1 |
| Grounded | 88/90 | 83/90 | -5 |
| Citation requirement met | 85/90 | 84/90 | -1 |
| Web policy met | 86/90 | 87/90 | +1 |
| Execution errors | 0 | 0 | 0 |

### By difficulty

| Difficulty | Baseline pass | Candidate pass | Baseline grounded | Candidate grounded |
|---|---:|---:|---:|---:|
| Basic | 30/30 | 30/30 | 30/30 | 30/30 |
| Medium | 23/30 | 26/30 | 28/30 | 27/30 |
| Hard | 27/30 | 23/30 | 30/30 | 26/30 |

The candidate improves deterministic pass for medium questions but loses more ground on hard questions. Seven previously passing cases regress: `MEDIUM-013`, `MEDIUM-023`, `HARD-002`, `HARD-012`, `HARD-017`, `HARD-026`, and `HARD-030`. Six previously failing cases improve: `MEDIUM-005`, `MEDIUM-011`, `MEDIUM-016`, `MEDIUM-020`, `MEDIUM-026`, and `HARD-022`.

Paired changes are not statistically conclusive, but the point estimates do not meet the no-regression promotion contract:

- deterministic pass: -1.11 percentage points, 95% bootstrap CI `[-8.89, +6.67]`, exact McNemar `p=1.0`;
- grounded: -5.56 points, CI `[-11.11, 0.0]`, `p=0.125`;
- citation requirement: -1.11 points, CI `[-7.78, +5.56]`, `p=1.0`;
- web policy: +1.11 points, CI `[0.0, +3.33]`, `p=1.0`.

## Retrieval and grounding

| Measure | Baseline | Candidate |
|---|---:|---:|
| Mean recall@1 | 0.2120 | 0.1657 |
| Mean recall@3 | 0.3769 | 0.3546 |
| Mean recall@10 | 0.5268 | 0.4731 |
| Supported claims | 413 | 459 |
| Unsupported claims | 585 | 516 |
| Glossary citations | 13 | 116 |

The vocabulary system materially increases glossary use and improves the supported-to-unsupported claim mix. It also lowers expected-source recall, indicating that new concise sources can displace concept, code, or test evidence expected by medium and hard questions. The failed cases did not simply cite the glossary directly, so this evidence does not justify a global demotion rule without further case-level diagnosis.

## Blind pedagogical review

The same paired judge scored both versions in one randomized A/B pass. Its baseline totals differ slightly from the previously published standalone judge because this is a new paired calibration; only within-pass comparisons are used here.

| Measure | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Pedagogical pass | 46/90 | 47/90 | +1 |
| Correct Cogentrex application | 69/90 | 68/90 | -1 |
| Full concept coverage | 21/90 | 24/90 | +3 |
| Poor concept coverage | 17/90 | 22/90 | +5 poor |
| Misleading/unsupported flag | 1/90 | 1/90 | 0 |

Preference was candidate 41, baseline 31, tie 18. By difficulty:

| Difficulty | Baseline pedagogy | Candidate pedagogy | Baseline application | Candidate application |
|---|---:|---:|---:|---:|
| Basic | 19/30 | 24/30 | 22/30 | 29/30 |
| Medium | 10/30 | 7/30 | 21/30 | 17/30 |
| Hard | 17/30 | 16/30 | 26/30 | 22/30 |

The useful effect is concentrated in beginner definitions. Overall pedagogical pass changes by only +1.11 percentage points, with CI `[-8.89, +11.11]` and exact McNemar `p=1.0`. Correct Cogentrex application changes by -1.11 points, also inconclusive. These results do not establish a global pedagogical improvement.

## Operations and accounting

| Measure | Baseline | Candidate |
|---|---:|---:|
| Mean latency | 31.317 s | 30.404 s |
| Median latency | 30.239 s | 29.093 s |
| P95 latency | 62.678 s | 59.477 s |
| Maximum latency | 75.435 s | 65.734 s |
| Total tokens | 649,469 | 641,888 |
| Reconciled cost | USD 6.20605075 | USD 6.30831325 |

All 144 candidate model charges were reconciled. Candidate usage was 481,679 input tokens and 160,209 output tokens. Lower token use did not reduce recorded cost because the input/output/cache mix differs.

## Media limitation

The external learning-media library was mounted read-only and not modified. Its 52 review-ready artifacts remain sourced from revision `33c56af`, 49 commits behind the candidate base history. The candidate indexed 64 transcript segments for runtime parity, but this does not make the media current or published. Regeneration and human acceptance remain separate work after the vocabulary candidate is redesigned and accepted.

## Promotion recommendation

- **Canonical catalog, generated glossary, UI, trusted context, and deterministic tests:** functional acceptance passed.
- **Combined candidate including global Tutor retrieval behavior:** **NO-GO**.
- **Push, PR, merge, stable deployment, or media regeneration:** not performed.

The next repair should preserve the demonstrated basic-question benefit while restoring medium/hard expected-source recall and grounding. It should be evaluated first on the seven regressions plus the six improvements, then on the 12-case smoke, and finally on the frozen 90-case matrix only if those gates pass.

## Post-evaluation diagnosis

The proposed query-aware ranking repair was not implemented because the defect could not be reproduced deterministically.

An offline ablation ran all 90 questions against the same 3,902-source local-embedding index, then removed only the 299 `visual:vocabulary:*` sources and repeated retrieval. Recall changed for eight cases: seven basic cases and `HARD-007`. None of the seven deterministic live regressions changed. `HARD-007` already failed both baseline and candidate because of web policy, not grounding. The vocabulary-source displacement hypothesis therefore does not explain the observed live regressions.

A live stability replay then reran the seven regressions plus six improvements:

- 13 attempted and completed;
- 8 deterministic passes;
- 9 grounded answers;
- zero execution errors;
- previous regressions `MEDIUM-013`, `HARD-012`, and `HARD-017` recovered;
- `MEDIUM-023`, `HARD-002`, `HARD-026`, and `HARD-030` remained failed;
- previously improved `HARD-022` failed the replay.

The replay used 80,218 input plus 22,963 output tokens across 23 reconciled charges, costing USD 0.946344. The mixed transitions confirm provider-generation and verifier instability rather than a stable vocabulary-ranking defect. Because the 13-case gate failed, no further 12-case smoke or second 90-case matrix was run.

The revised recommendation is to avoid an unsupported ranking tweak. Either split the deterministic catalog/glossary/UI capability from Tutor activation, or put Tutor vocabulary retrieval behind a controlled rollout that can require repeated stability acceptance. A broader generation/verifier reliability change belongs in a separate evaluated initiative.
