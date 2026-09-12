# Tutor v2: verified streaming, official web context, and local semantic embeddings

## Goal

Improve the Visual Learning tutor from Luis's runtime feedback without weakening grounding or adding unnecessary infrastructure.

## Architecture decisions

1. Keep PostgreSQL SQL-JSON storage. A vector database stores vectors but does not generate them; adding Qdrant or pgvector would not solve the Foundry embedding HTTP 429.
2. Add a local FastEmbed provider using `BAAI/bge-small-en-v1.5` (384 dimensions) and persist the model in the backend image so indexing and query embeddings use the same semantic space without provider calls.
3. Add bounded web supplementation through the existing search implementation, but filter to HTTPS official documentation domains before page extraction. Web evidence remains ephemeral, untrusted, separately labeled, and subject to the same claim verifier.
4. Add an SSE tutor endpoint with visible retrieval/web/generation/verification phases. Deliver the final verified answer in chunks; never expose unverified model output as final content.
5. Keep captions available for accessibility but remove automatic activation by deleting the `default` attribute.

## Acceptance criteria

- Local embeddings produce normalized 384-dimensional vectors and work in batches.
- The full learning corpus is indexed with the local model and queried with the same provider/model.
- A conceptual question can combine official web evidence with local Cogentrex evidence and cite both distinctly.
- Web URLs are HTTPS and match a server-owned domain allowlist before content fetching.
- Web failure degrades to local evidence and never blocks an otherwise answerable question.
- The browser receives SSE status events and multiple verified answer chunks before the final result event.
- The stored session contains one canonical completed answer, not partial fragments.
- Video captions are off by default; the CC track and accessible transcript remain available.
- Focused backend/frontend tests, full CI-equivalent gates, container build, local readiness, live-provider tutor acceptance, and browser verification pass.

## Delivery sequence

1. Add failing tests for local embeddings, official-domain filtering, tutor web augmentation, SSE contract, frontend stream parsing, progress rendering, and caption default state.
2. Implement the local embedding provider and image/runtime configuration.
3. Implement web supplements and external citation rendering.
4. Implement backend SSE and frontend progressive rendering.
5. Remove automatic caption activation.
6. Run focused and aggregate gates.
7. Commit on a feature branch, push, open PR, wait for exact-SHA CI, merge, update canonical main, and hot-swap affected services.
8. Reindex with local semantic embeddings, run live tutor acceptance, and verify the browser.
