# Faithfulness

**Status:** partial

## Definition
Faithfulness asks whether an answer stays within what its provided context supports, without contradiction or unsupported additions. It is evaluated after retrieval/generation and differs from whether retrieval found the best evidence.

## Archon implementation
The grounded workflow’s `_supports_claim` is the strongest current operational proxy: citation identity, content-hash integrity, substantive-token coverage, numeric containment, and polarity. `backend/app/eval/evaluators.py::evaluate_faithfulness` is a lightweight sentence/keyword-overlap heuristic (over 30%) and explicitly suggests a stronger production judge.

## Failure modes
Lexical overlap can accept word salad or reject valid paraphrase; a cited source may be wrong; multi-hop support and qualifiers are difficult; judge models add bias and nondeterminism. Report the evaluator and dataset alongside every score—never just “faithfulness = 0.9.”

## Evidence and limits
`backend/tests/unit/test_grounded_rag.py::test_claim_support_is_conservative_about_negation_numbers_and_partial_claims`; `backend/tests/unit/test_eval.py` covers the basic harness, not semantic validity. No calibrated production faithfulness benchmark is established.

## Interview prompt
“Faithfulness is support relative to context. Archon uses conservative deterministic proxies, useful for regression but not equivalent to semantic entailment.”
