# Learning Tutor Quality Evaluation

Status: final local evaluation for merged revision `212e84f`.

This report separates deterministic acceptance, retrieval, operations, and subjective pedagogical review. It does not claim public deployment or production-scale performance. The machine-readable summary is [`learning-tutor-quality-final.json`](learning-tutor-quality-final.json).

## Evaluation design

- Dataset: `backend/evals/learning_tutor/concepts-v1.json`, version 1.
- Cases: 90 total — 30 basic, 30 medium, 30 hard.
- Provider: configured Foundry `claude-opus-4-6` deployment.
- Retrieval: local `BAAI/bge-small-en-v1.5` embeddings, 384 dimensions, SQL-JSON cosine plus lexical/context ranking.
- Execution: three isolated users, one sequential shard per difficulty.
- Deterministic scoring: fallback avoidance, grounding, citation minimum, web policy, and forbidden exact phrases.
- Pedagogical scoring: separate blinded model-rubric review over all 90 rendered answers.
- Runtime validity: stack status, `/healthz`, and `/readyz` passed before and after the matrix.

The baseline and final run used the same versioned questions and scoring contract. The final corpus contained 3,302 sources and 4,450 chunks. Raw responses and authenticated run records remain local; only aggregate, sanitized evidence is committed.

## Result summary

| Measure | Baseline | Final | Delta |
|---|---:|---:|---:|
| Deterministic pass | 65/90 (72.2%) | 80/90 (88.9%) | +16.7 pp |
| Grounded | 75/90 (83.3%) | 88/90 (97.8%) | +14.4 pp |
| Non-fallback | 75/90 (83.3%) | 88/90 (97.8%) | +14.4 pp |
| Citation requirement met | 71/90 (78.9%) | 85/90 (94.4%) | +15.6 pp |
| Web policy met | 85/90 (94.4%) | 86/90 (95.6%) | +1.1 pp |
| Execution errors | 1 | 0 | -1 |
| Fallbacks | 14 | 2 | -12 |
| Pedagogical pass | 35/90 (38.9%) | 44/90 (48.9%) | +10.0 pp |
| Correct Cogentrex application | 45/90 (50.0%) | 63/90 (70.0%) | +20.0 pp |
| Misleading/unsupported flag | 3/90 | 1/90 | -2 |

Paired deterministic changes were statistically directional on this dataset:

- pass: bootstrap 95% CI `[+6.67, +26.67]` percentage points; McNemar `p=0.004077`;
- grounded/non-fallback: CI `[+6.67, +22.22]`; `p=0.000977`;
- citation requirement: CI `[+6.67, +24.44]`; `p=0.002577`.

Pedagogical pass improved by 10.0 points, but its paired 95% CI `[-2.22, +22.22]` includes zero (`p=0.149613`), so the run does not establish a statistically reliable general pedagogical improvement. Correct Cogentrex application improved by 20.0 points with CI `[+8.89, +32.22]` and `p=0.002102`.

## Results by difficulty

| Difficulty | Deterministic pass | Grounded | Citation requirement | Pedagogical pass | Cogentrex application |
|---|---:|---:|---:|---:|---:|
| Basic | 30/30 | 30/30 | 30/30 | 18/30 | 24/30 |
| Medium | 23/30 | 28/30 | 26/30 | 15/30 | 21/30 |
| Hard | 27/30 | 30/30 | 29/30 | 11/30 | 18/30 |
| Overall | 80/90 | 88/90 | 85/90 | 44/90 | 63/90 |

The model-rubric review classified concept coverage as 20 full, 49 partial, and 21 poor. Basic definition-first passed 24/30. One answer was flagged misleading or unsupported. These judgments remain subjective evidence and are not folded into deterministic pass.

## Retrieval and grounding

| Metric | Final result |
|---|---:|
| Mean recall@1 | 0.2120 |
| Mean recall@3 | 0.3769 |
| Mean recall@10 | 0.5268 |
| Full expected-source recall@10 | 26/90 |
| Supported claims | 413 |
| Unsupported claims | 585 |
| Claim support rate | 41.38% |
| Web evidence items | 34 |
| Verified web claims | 11 |
| Final web citations | 11 |

The corpus correction materially improved retrieval of the tutor's own implementation files. Recall remains incomplete: a mean recall@10 of 0.5268 means the expected source set was often only partially present.

Grounding repair ran for 47 weak initial generations. Forty repairs produced strictly more supported claims and were adopted; seven were not better and the initial response was retained. The global 90% lexical threshold, citation binding, numeric checks, and polarity checks were not weakened. Three structured-output parse retries and one structured-output fallback occurred.

## Latency, tokens, and cost

| Measure | Baseline | Final |
|---|---:|---:|
| Average latency | 34.589 s | 31.317 s |
| Median latency | 31.912 s | 30.239 s |
| P95 latency | 52.428 s | 62.678 s |
| Maximum latency | 90.904 s | 75.435 s |
| Total tokens | 466,831 | 649,469 |

The paired mean latency delta was `-2.984 s`, with bootstrap 95% CI `[-7.3126, +1.3045]`; the interval includes zero. Median latency improved slightly, while P95 worsened by 19.6% because low-grounding answers can invoke one additional provider call.

Final token use was 497,873 input plus 151,596 output, or 649,469 total and 7,216.3 per case. This is 39.1% more total tokens than baseline. The local charge ledger recorded 140 reconciled charges totaling 6,206,050,750 nUSD, or USD 6.20605075. Baseline pricing was unavailable, so no cost delta is claimed.

## Remaining failures

Ten cases failed at least one deterministic rule:

- fallback/ungrounded: `MEDIUM-002`, `MEDIUM-005`;
- insufficient citations: `MEDIUM-005`, `MEDIUM-011`, `MEDIUM-020`, `MEDIUM-026`, `HARD-022`;
- web-policy mismatch: `MEDIUM-016`, `MEDIUM-022`, `HARD-007`, `HARD-028`.

The pedagogical judge still found frequent adjacent-topic and thin-answer failures, especially for implementation-heavy questions. Deterministic grounding prevents fabrication more reliably than it guarantees complete teaching.

## Acceptance statement

The final local candidate improves deterministic pass, grounding, fallback avoidance, citation sufficiency, expected-source recall, Cogentrex application, and web citation flow over the frozen baseline. It eliminates execution errors in this matrix.

It does **not** prove production readiness, public deployment, complete retrieval, universally strong pedagogy, or improved tail latency. The remaining work is primarily retrieval completeness and pedagogical coverage, not another vector database or a weaker verifier.
