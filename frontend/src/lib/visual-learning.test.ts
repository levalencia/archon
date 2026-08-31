import { describe, expect, it, vi } from 'vitest';
import {
  conceptsForModule,
  evidenceFilter,
  loadVisualLearningStudio,
  type LearningConcept,
  type VisualLearningStudio,
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

const studio = {
  schema: 'archon.visual-learning-studio', version: 2, generated_from: [],
  stats: {
    concepts: 66, modules: 16, stories: 5, architecture_layers: 5, notebooks: 5,
    statuses: { implemented: 46, partial: 14, deferred: 6 },
  },
  roadmap: [], modules: [], concepts, stories: [],
  architecture: { layers: [], relations: [] },
  notebooklm: { version: 1, source_priority: [], promptbook_href: '', runbook_href: '', notebooks: [] },
} satisfies VisualLearningStudio;

describe('Visual Learning Studio helpers', () => {
  it('filters evidence by text and status', () => {
    expect(evidenceFilter(concepts, 'mock', 'all')).toEqual([concepts[1]]);
    expect(evidenceFilter(concepts, '', 'implemented')).toEqual([concepts[0]]);
  });

  it('returns concepts owned by one stable module', () => {
    expect(conceptsForModule(studio, '08-rag')).toEqual([concepts[1]]);
  });

  it('loads and validates the multi-view schema', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(studio), { status: 200 }));
    await expect(loadVisualLearningStudio(fetcher)).resolves.toEqual(studio);
    expect(fetcher).toHaveBeenCalledWith('/learning/archon-studio.json');
  });

  it('rejects stale counts or schema versions', async () => {
    const malformed = { ...studio, stats: { ...studio.stats, modules: 15 } };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    await expect(loadVisualLearningStudio(fetcher)).rejects.toThrow('canonical counts');
  });
});
