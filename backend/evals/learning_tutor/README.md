# Learning Tutor Evaluation Suite

This directory contains the versioned concept-learning benchmark for the Cogentrex tutor.

## Dataset

`concepts-v1.json` contains 90 cases:

- 30 basic questions: plain-language definitions followed by Cogentrex application.
- 30 medium questions: comparisons, lifecycle traces, and implementation trade-offs.
- 30 hard questions: system design, failure analysis, security, evaluation, and migration boundaries.

Each case declares expected concepts, expected Cogentrex source areas, forbidden misconceptions, citation requirements, web policy, and canonical UI context.

`web_policy` has three values:

- `required`: general knowledge should be supported by an approved official web source and Cogentrex claims by local evidence.
- `allowed`: local evidence may be enough; bounded official web evidence may supplement it.
- `forbidden`: the question is specifically about Cogentrex and must not outsource authority to the web.

## Evaluation layers

Do not collapse these into one score:

1. Retrieval: expected evidence appears in the candidate set.
2. Grounding: claims survive deterministic verification and citations bind to the supporting evidence.
3. Pedagogy: a beginner receives a plain definition before implementation details.
4. Product accuracy: Cogentrex-specific statements match repository evidence and declared limitations.
5. Source routing: web evidence is used only according to the case policy.
6. Operations: latency, failures, and provider cost are reported independently from answer quality.

The runner computes only deterministic checks. Definition quality, explanation clarity, concept coverage, and nuanced misconceptions remain explicit manual or model-judge checks; they are not disguised as string-match accuracy.

## Safe execution sequence

Validate the dataset without provider calls:

```bash
cd backend
uv run python scripts/run_learning_tutor_benchmark.py
```

Run a small live diagnostic before spending on all 90 cases:

```bash
export COGENTREX_EVAL_TOKEN='replace-with-a-temporary-token'
uv run python scripts/run_learning_tutor_benchmark.py \
  --live \
  --difficulty basic \
  --limit 5 \
  --output ../artifacts/learning-tutor-eval/basic-smoke.json
```

Run selected regressions:

```bash
uv run python scripts/run_learning_tutor_benchmark.py \
  --live \
  --case-id BASIC-004 \
  --case-id BASIC-005 \
  --case-id BASIC-007 \
  --case-id BASIC-008
```

Only run all 90 cases after the diagnostic batch confirms authentication, latency, web availability, and grounding behavior. A timeout or provider error is not a pass.

## Improvement decisions

Use the failure layer to choose the intervention:

- Expected source absent from top-k: improve corpus, chunking, metadata, aliases, or ranking.
- Correct source retrieved but no supported claims: inspect citation binding and deterministic verification.
- Grounded but confusing answer: improve pedagogical prompt/examples, not retrieval.
- General concept lacks authoritative context: improve bounded official-web routing.
- Cogentrex claim cites only web evidence: fix source authority and prompt constraints.
- High latency with good quality: optimize provider calls, extraction, or retrieval separately.

Do not introduce another vector database unless retrieval metrics show that SQL-JSON is the limiting factor.
