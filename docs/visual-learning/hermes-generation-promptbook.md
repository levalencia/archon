# Hermes Learning Artifact Promptbook

Hermes uses these contracts to create English derivative learning material from allowlisted Cogentrex sources. Generated material never replaces canonical implementation evidence.

## Source priority

1. `docs/IMPLEMENTATION-EVIDENCE.md`
2. `docs/implementation/CAPABILITY-ACCEPTANCE.yaml`
3. `docs/REMAINING-DEFERRED-GAPS.md`
4. `docs/ARCHITECTURE-DIAGRAMS.md`
5. Course modules and concept pages

## Universal generation contract

- Write all learner-facing content in English.
- Use only files named by the selected learning pack.
- Attach source paths to every slide, diagram, card, question, and guide section.
- Distinguish code, deterministic tests, local observation, live-provider evidence, and public deployment.
- Never turn partial, local-only, mock, or deferred evidence into a stronger claim.
- Include explicit limitations and a “What this does not prove” section.
- Produce the requested versioned JSON schema; do not emit executable code inside content fields.

## Presentation

Create 12–15 slides for a 15-minute engineering walkthrough. Each slide has one message, speaker notes, source references, and a diagram or visual concept whenever it improves understanding. Prefer progressive, labeled relationships over paragraphs.

## Diagrams and infographic

Use at most eight active components. Label every arrow with the data, decision, or state transition crossing the boundary. Use semantic component types and include a complete text description.

## Audio and podcast

Write a structured English script with chapters, speaker names, source references, and pronunciation notes for technical terms. A single narrator is the default. A second voice is allowed only after both voices pass the listening review.

## Mind map

Organize by runtime stage, component, responsibility, evidence, and limitation. Use no more than six top-level branches. Never mix runtime flow with learning prerequisites.

## Flashcards

Target understanding: 40% responsibility, 30% relationship/sequence, 20% failure/trade-off, and 10% evidence/limitations. Every answer explains why and names a misconception.

## Quiz

Create difficult, scenario-based questions. Include one best answer, explanations, source grounding, and no unsupported questions.

## Study guide

Include outcomes, vocabulary, mental model, architecture/request diagrams, evidence, limitations, misconceptions, self-checks, and an interview-ready explanation.

## Video storyboard

Use one idea per scene, deterministic timing, English narration, readable on-screen labels, safe margins, and an accessible transcript. HyperFrames validation and representative-frame review are mandatory before publication.
