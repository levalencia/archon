export type ConceptStatus = 'implemented' | 'partial' | 'deferred';

export interface LearningLink {
  path: string;
  label: string;
  href: string;
}

export interface LearningNode {
  id: string;
  title: string;
  status: ConceptStatus;
  module_id: string;
  module_title: string;
  module_href: string;
  detail_href: string;
  content_source: 'concept' | 'module';
  summary: string;
  mental_model: string;
  limitations: string;
  sources: LearningLink[];
  tests: LearningLink[];
  evidence: LearningLink[];
}

export interface LearningEdge {
  source: string;
  target: string;
  kinds: string[];
  labels: string[];
}

export interface LearningTour {
  id: string;
  title: string;
  description: string;
  concept_ids: string[];
}

export interface LearningModule {
  id: string;
  title: string;
  summary: string;
  mental_model: string;
  href: string;
  concept_count: number;
}

export interface LearningGraph {
  schema: 'archon.visual-learning-graph';
  version: number;
  generated_from: string[];
  stats: {
    concepts: number;
    modules: number;
    edges: number;
    tours: number;
    statuses: Record<ConceptStatus, number>;
  };
  modules: LearningModule[];
  nodes: LearningNode[];
  edges: LearningEdge[];
  tours: LearningTour[];
}

export interface LearningFilters {
  query: string;
  status: ConceptStatus | 'all';
  moduleId: string;
}

export const STATUS_META: Record<ConceptStatus, { label: string; color: string }> = {
  implemented: { label: 'Implemented', color: '#55d6be' },
  partial: { label: 'Partial', color: '#f0bd62' },
  deferred: { label: 'Deferred', color: '#7f8b9b' },
};

export function filterLearningNodes(
  nodes: LearningNode[],
  filters: LearningFilters,
): LearningNode[] {
  const query = filters.query.trim().toLowerCase();
  return nodes.filter(node => {
    const matchesStatus = filters.status === 'all' || node.status === filters.status;
    const matchesModule = !filters.moduleId || node.module_id === filters.moduleId;
    const haystack = `${node.title} ${node.id} ${node.module_title} ${node.summary}`.toLowerCase();
    return matchesStatus && matchesModule && (!query || haystack.includes(query));
  });
}

export function relatedConceptIds(graph: LearningGraph, conceptId: string): Set<string> {
  const related = new Set<string>([conceptId]);
  for (const edge of graph.edges) {
    if (edge.source === conceptId) related.add(edge.target);
    if (edge.target === conceptId) related.add(edge.source);
  }
  return related;
}

export async function loadLearningGraph(
  fetcher: typeof fetch = fetch,
): Promise<LearningGraph> {
  const response = await fetcher('/learning/archon-graph.json');
  if (!response.ok) throw new Error(`Learning graph request failed (${response.status})`);
  const graph = (await response.json()) as LearningGraph;
  if (graph.schema !== 'archon.visual-learning-graph' || graph.stats.concepts !== 66) {
    throw new Error('Learning graph schema or concept count is invalid');
  }
  return graph;
}
