# Embeddings

**Status:** partial

## Definition
An embedding is a fixed-length numeric representation used to rank semantic similarity. Similarity is not truth, entailment, authorization, or citation correctness.

## Archon implementation
`backend/app/services/chunker.py::EmbeddingService` supports `mock` and `openai`. `validate_embedding` requires exact dimensions, numeric non-boolean finite values. The OpenAI path validates HTTPS/allowlisted host, resolves DNS with a deadline, pins an IP while setting Host/SNI, disables redirects and environment proxies, uses a 30-second client timeout, and validates response indexes/counts. `capability.mock` exposes readiness.

## Mock warning
`_mock_embed` deterministically derives numbers from SHA-256. It is useful for repeatable control tests but has no demonstrated semantic geometry. Final acceptance evidence uses mock embeddings/provider; it is not model-quality proof.

## Failure/security modes
Reject wrong dimensions, NaN/infinity, missing real credentials, unallowlisted/private endpoints without opt-in, malformed provider payloads, and DNS failure. Model/version changes require re-embedding and dataset evaluation.

## Evidence
`backend/tests/unit/test_embedding_hardening.py`, `backend/tests/unit/test_embedding_config.py`, `backend/tests/unit/test_rag.py`. No live external embedding acceptance is claimed.

## Interview prompt
“Archon hardens embedding I/O, but its final deterministic evidence validates plumbing, not semantic retrieval quality.”
