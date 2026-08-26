# Verifier Benefit Benchmark

`backend/tests/fixtures/evals/verifier-benefit-v1.json` is the versioned input for the
executable baseline-versus-verifier benchmark. Its canonical SHA-256 hash excludes only
the `content_hash` field; the strict loader rejects unknown fields, duplicate JSON keys,
unsupported schema versions, invalid references, oversized text, and content drift.

## Evidence semantics

- **supported** means the supplied evidence directly entails the bounded claim. A citation
  is provenance, not proof by itself.
- **unsupported** means the supplied evidence does not entail the complete claim. The
  fixture intentionally includes a lexically plausible overclaim that the deterministic
  overlap baseline accepts.
- **no_evidence** means retrieval returned no evidence and therefore no claim can be
  evaluated or delegated.

The integration benchmark runs the grounded workflow's deterministic claim check and the
real isolated verifier service against each immutable case. It checks durable parent-child
lineage and feeds the returned `ChildVerificationResult` into the pure measurement report.
The no-evidence case proves that no child request is constructed.

`value_added` is true only when the child strictly lowers false-support rate without
exceeding the explicitly accepted false-reject rate (zero by default). Token counts and
latency are observations from child results. Cost remains `null` when no measured cost was
provided. These fixture results demonstrate behavior under controlled inputs; they are not
claims about production model quality, latency, cost, or general benchmark performance.
