# Groundedness

**Status:** implemented with conservative deterministic semantics

## Definition
Groundedness asks whether factual answer claims are supported by the evidence supplied for this run. It is not retrieval relevance (useful chunks), global truth, answer relevance, or stylistic quality.

## Archon implementation
`GroundedDocumentWorkflow` parses atomic model claims and `E#` IDs. `_verify_document_claims` rechecks evidence hashes and `_supports_claim` requires known citations, at least 90% substantive-token overlap, numeric literal containment, and matching relevant polarity. Only supported claims are reconstructed into the answer; no accepted claims yields abstention. `grounded` is `bool(claims)`.

## Interpretation
This high-precision rule rejects many paraphrases. It is deliberately not semantic entailment/NLI. The legacy `evaluate_faithfulness` 30% keyword heuristic is separate and weaker. A grounded statement can still rely on a false source.

## Evidence
`backend/tests/unit/test_grounded_rag.py` covers missing/unknown citations, overclaims, negation, numbers, tampered evidence, and abstention. Safe counts/hashes appear as Run Ledger events. `docs/evidence/local-portfolio-benchmark.json` is deterministic mock evidence only.

## Interview prompt
“Groundedness is claim support relative to supplied evidence; it does not certify source truth or answer usefulness.”
