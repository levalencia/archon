import { describe, expect, it, vi } from 'vitest';
import {
  conceptsForModule,
  evidenceFilter,
  loadVisualLearningStudio,
  type LearningConcept,
  type VocabularyEntry,
  type VisualLearningStudio,
  vocabularyFilter,
} from './visual-learning';

const concepts: LearningConcept[] = [
  {
    id: 'runtime', title: 'Typed runtime', status: 'implemented', module_id: '02-runtime',
    module_title: 'Runtime', module_href: 'https://example.test/runtime',
    detail_href: 'https://example.test/runtime-detail', content_source: 'concept',
    summary: 'Provider-neutral execution loop', mental_model: 'Guarded interpreter',
    limitations: 'Local only', sources: [], tests: [], evidence: [],
    proof: { code: true, tests: true, evidence: true },
  },
  {
    id: 'embeddings', title: 'Embeddings', status: 'partial', module_id: '08-rag',
    module_title: 'RAG', module_href: 'https://example.test/rag',
    detail_href: 'https://example.test/embeddings', content_source: 'concept',
    summary: 'Maps text into vectors', mental_model: 'Coordinates for meaning',
    limitations: 'Mock provider', sources: [], tests: [], evidence: [],
    proof: { code: true, tests: true, evidence: false },
  },
];

const vocabulary: VocabularyEntry[] = [
  {
    id: 'dependency-injection', term: 'Dependency injection', aliases: ['DI'],
    category: 'python-architecture', level: 'beginner',
    definition: 'Supply collaborators from outside the component.',
    cogentrex: 'The runtime receives provider and tool collaborators through constructors.',
    concept_ids: ['python-protocols-di'], eval_concept_ids: [], related_ids: [],
    learn_more: [{ path: 'docs/course/concepts/oop-protocols-dependency-injection.md', label: 'OOP', href: 'https://example.test/oop' }],
    media_refs: [],
  },
  {
    id: 'preflight-check', term: 'Preflight check', aliases: ['preflight'],
    category: 'python-architecture', level: 'beginner',
    definition: 'Verify required dependencies before declaring readiness.',
    cogentrex: 'Startup performs bounded checks before the service reports ready.',
    concept_ids: ['application-composition'], eval_concept_ids: ['preflight'], related_ids: [],
    learn_more: [{ path: 'docs/course/concepts/application-composition.md', label: 'Application composition', href: 'https://example.test/application' }],
    media_refs: [{ label: 'Video 1', href: '/learn?view=present&artifact=video-1&t=235.7' }],
  },
];

const studio = {
  schema: 'cogentrex.visual-learning-studio', version: 4, generated_from: [],
  stats: {
    concepts: 67, modules: 16, stories: 5, architecture_layers: 5, learning_packs: 5,
    vocabulary_terms: 2, vocabulary_aliases: 2,
    statuses: { implemented: 46, partial: 14, deferred: 6 },
  },
  roadmap: [], modules: [], concepts, vocabulary, stories: [],
  architecture: { layers: [], relations: [] },
  learning_library: { version: 1, language: 'en', source_priority: [], promptbook_href: '', runbook_href: '', packs: [] },
} satisfies VisualLearningStudio;

describe('Visual Learning Studio helpers', () => {
  it('filters evidence by text and status', () => {
    expect(evidenceFilter(concepts, 'mock', 'all')).toEqual([concepts[1]]);
    expect(evidenceFilter(concepts, '', 'implemented')).toEqual([concepts[0]]);
  });

  it('returns concepts owned by one stable module', () => {
    expect(conceptsForModule(studio, '08-rag')).toEqual([concepts[1]]);
  });

  it('filters vocabulary by term, alias, category, level, and project meaning', () => {
    expect(vocabularyFilter(vocabulary, 'DI', 'all', 'all')).toEqual([vocabulary[0]]);
    expect(vocabularyFilter(vocabulary, 'readiness', 'python-architecture', 'beginner')).toEqual([
      vocabulary[1],
    ]);
    expect(vocabularyFilter(vocabulary, '', 'python-architecture', 'beginner')).toEqual(vocabulary);
  });

  it('loads and validates the multi-view schema', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(studio), { status: 200 }));
    await expect(loadVisualLearningStudio(fetcher)).resolves.toEqual(studio);
    expect(fetcher).toHaveBeenCalledWith('/learning/cogentrex-studio.json');
  });

  it('rejects stale counts or schema versions', async () => {
    const malformed = { ...studio, stats: { ...studio.stats, modules: 15 } };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    await expect(loadVisualLearningStudio(fetcher)).rejects.toThrow('canonical counts');
  });
});
