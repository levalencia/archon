import { describe, expect, it, vi } from 'vitest';
import {
  filterLearningNodes,
  loadLearningGraph,
  relatedConceptIds,
  type LearningGraph,
  type LearningNode,
} from './visual-learning';

const nodes: LearningNode[] = [
  {
    id: 'runtime',
    title: 'Typed runtime',
    status: 'implemented',
    module_id: '02-runtime',
    module_title: 'Runtime',
    module_href: 'https://example.test/runtime',
    detail_href: 'https://example.test/runtime-detail',
    content_source: 'concept',
    summary: 'Provider-neutral execution loop',
    mental_model: 'Guarded interpreter',
    limitations: 'Local only',
    sources: [], tests: [], evidence: [],
  },
  {
    id: 'embeddings',
    title: 'Embeddings',
    status: 'partial',
    module_id: '08-rag',
    module_title: 'RAG',
    module_href: 'https://example.test/rag',
    detail_href: 'https://example.test/embeddings',
    content_source: 'concept',
    summary: 'Maps text into vectors',
    mental_model: 'Coordinates for meaning',
    limitations: 'Mock provider',
    sources: [], tests: [], evidence: [],
  },
];

const graph = {
  schema: 'archon.visual-learning-graph',
  version: 1,
  generated_from: [],
  stats: {
    concepts: 66,
    modules: 15,
    edges: 1,
    tours: 1,
    statuses: { implemented: 46, partial: 14, deferred: 6 },
  },
  modules: [],
  nodes,
  edges: [{ source: 'runtime', target: 'embeddings', kinds: ['curated'], labels: [] }],
  tours: [],
} satisfies LearningGraph;

describe('visual learning graph helpers', () => {
  it('filters by text, status, and module', () => {
    expect(filterLearningNodes(nodes, { query: 'vector', status: 'all', moduleId: '' }))
      .toEqual([nodes[1]]);
    expect(filterLearningNodes(nodes, { query: '', status: 'implemented', moduleId: '' }))
      .toEqual([nodes[0]]);
    expect(filterLearningNodes(nodes, { query: '', status: 'all', moduleId: '08-rag' }))
      .toEqual([nodes[1]]);
  });

  it('returns the selected concept and direct graph neighbors', () => {
    expect([...relatedConceptIds(graph, 'runtime')].sort()).toEqual(['embeddings', 'runtime']);
  });

  it('loads and validates the generated graph contract', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(graph), { status: 200 }));
    await expect(loadLearningGraph(fetcher)).resolves.toEqual(graph);
    expect(fetcher).toHaveBeenCalledWith('/learning/archon-graph.json');
  });

  it('rejects stale or malformed graph payloads', async () => {
    const malformed = { ...graph, stats: { ...graph.stats, concepts: 65 } };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(malformed), { status: 200 }));
    await expect(loadLearningGraph(fetcher)).rejects.toThrow('schema or concept count');
  });
});
