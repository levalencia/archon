# Visual Learning Vocabulary System

> **Historical plan:** Vocabulary and Visual Learning remain active, but all Learning Tutor retrieval goals in this document were retired by migration `20260917_24`.

## Goal

Create one canonical, extensive vocabulary system that covers the terms used across course Markdown, Visual Learning, published media, Learning Tutor evaluations, and implementation walkthroughs. Make the vocabulary searchable in `/learn`, heading-scoped for Tutor retrieval, and continuously audited for drift.

## Architecture

```text
vocabulary.yaml (canonical structured source)
    -> build-learning-vocabulary.py
       -> glossary.md (beginner-readable, heading-scoped)
       -> vocabulary-audit.json (coverage and exclusions)
    -> build-visual-learning.py
       -> cogentrex-studio.json vocabulary index
    -> VocabularyView.svelte
       -> searchable/filterable /learn?view=glossary
    -> Learning Tutor corpus
       -> one heading-scoped chunk per term
```

The vocabulary catalog distinguishes:

- canonical terms;
- aliases and acronyms;
- concept IDs;
- beginner definitions;
- Cogentrex-specific application;
- related terms;
- canonical documentation links;
- optional media references;
- category and level.

Source titles and explanatory sentences that are not genuine terms are recorded as covered aliases or explicit exclusions, not inflated into glossary entries.

## Acceptance

1. Every existing glossary entry is preserved or intentionally superseded.
2. Every concept-catalog entry maps to at least one vocabulary entry.
3. Every identifier-like `expected_concepts` value in all 90 Tutor evals maps to vocabulary.
4. Every bold term in module/concept prerequisite-vocabulary sections is covered or explicitly excluded with a reason.
5. Every term explicitly introduced in published video vocabulary chapters maps to vocabulary and may carry a timestamp reference.
6. Visual Learning Studio schema contains vocabulary and aliases, generated from canonical source.
7. `/learn?view=glossary` supports text, alias, category, level, and concept navigation.
8. Learning Tutor indexes heading-scoped glossary entries; focused retrieval tests prove basic definition queries rank glossary/concept evidence.
9. Course validator and Studio `--check` fail on stale generated outputs or orphan concept references.
10. External media remains marked stale until regenerated from the committed revision; no dirty-tree artifact claims.

## Phases

### 1. Contracts and audit

- Add failing backend tests for vocabulary schema, coverage, glossary generation, Studio generation, and Tutor indexing.
- Add failing frontend tests for loading/filtering vocabulary and the new view.
- Implement deterministic source inventory and exclusion reporting.

### 2. Canonical vocabulary

- Convert the current glossary into structured entries.
- Add terms from catalog concepts, prerequisite sections, eval IDs, video vocabulary, and curated pack terminology.
- Curate aliases and reject duplicate normalized terms.
- Generate a heading-scoped Markdown glossary.

### 3. Visual Learning integration

- Bump Studio schema.
- Add vocabulary stats and generated-source dependency.
- Implement typed helpers and `VocabularyView.svelte`.
- Add accessible search/filter/navigation and Tutor context selection.

### 4. Tutor retrieval

- Preserve the glossary in the allowlisted corpus.
- Add source-kind/definition-query ranking so glossary and concept pages outrank unrelated code for basic “what is X?” questions.
- Verify representative basic cases deterministically before any live provider spend.

### 5. Media and freshness

- Create transcript-to-term coverage evidence for the four published videos.
- Add media references to canonical terms where a definition timestamp exists.
- Do not rewrite or republish external media until the repo change is committed and reviewed.

### 6. Verification and evidence

- Course documentation validation.
- Vocabulary generation `--check`.
- Visual Learning generation `--check`.
- Backend focused and full gates.
- Frontend Svelte/Vitest/Playwright focused gates.
- Targeted paired live basic-question smoke only after deterministic retrieval improves.
- Document exact limitations and external-media stale status.
