import { ARCHON_THEME } from '$lib/archon-theme';

export type ConceptStatus = 'implemented' | 'partial' | 'deferred';

export interface LearningLink {
  path: string;
  label: string;
  href: string;
}

export interface LearningConcept {
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
  proof: { code: boolean; tests: boolean; evidence: boolean };
}

export interface LearningModule {
  id: string;
  title: string;
  summary: string;
  mental_model: string;
  href: string;
  concept_ids: string[];
  concept_count: number;
}

export interface RoadmapPhase {
  id: string;
  title: string;
  question: string;
  outcome: string;
  module_ids: string[];
}

export interface StoryStep {
  number: number;
  title: string;
  from: string;
  to: string;
  relationship: string;
  explanation: string;
  concept_ids: string[];
}

export interface LearningStory {
  id: string;
  title: string;
  description: string;
  steps: StoryStep[];
}

export interface ArchitectureComponent {
  id: string;
  title: string;
  responsibility: string;
  concept_ids: string[];
}

export interface ArchitectureLayer {
  id: string;
  title: string;
  description: string;
  components: ArchitectureComponent[];
}

export interface ArchitectureRelation {
  source: string;
  target: string;
  type: string;
  label: string;
}

export interface LearningPackRecipe {
  id: string;
  title: string;
  purpose: string;
  sources: string[];
  source_count: number;
  artifacts: string[];
}

export interface VisualLearningStudio {
  schema: 'archon.visual-learning-studio';
  version: 3;
  generated_from: string[];
  stats: {
    concepts: number;
    modules: number;
    stories: number;
    architecture_layers: number;
    learning_packs: number;
    statuses: Record<ConceptStatus, number>;
  };
  roadmap: RoadmapPhase[];
  modules: LearningModule[];
  concepts: LearningConcept[];
  stories: LearningStory[];
  architecture: {
    layers: ArchitectureLayer[];
    relations: ArchitectureRelation[];
  };
  learning_library: {
    version: number;
    language: 'en';
    source_priority: string[];
    promptbook_href: string;
    runbook_href: string;
    packs: LearningPackRecipe[];
  };
}

export const STATUS_META: Record<ConceptStatus, { label: string; color: string }> = {
  implemented: { label: 'Implemented', color: ARCHON_THEME.green },
  partial: { label: 'Partial', color: '#f0bd62' },
  deferred: { label: 'Deferred', color: '#7f8b9b' },
};

export const RELATION_META: Record<string, { label: string; color: string }> = {
  CALLS: { label: 'Calls', color: ARCHON_THEME.blue },
  ROUTES: { label: 'Routes', color: ARCHON_THEME.blue },
  AUTHORIZES: { label: 'Authorizes', color: ARCHON_THEME.green },
  BUILDS_CONTEXT_FOR: { label: 'Builds context for', color: ARCHON_THEME.purple },
  PROPOSES: { label: 'Proposes', color: ARCHON_THEME.orange },
  GATES: { label: 'Gates', color: ARCHON_THEME.coral },
  PERSISTS_TO: { label: 'Persists to', color: ARCHON_THEME.purple },
  READS: { label: 'Reads', color: ARCHON_THEME.blue },
  EMITS: { label: 'Emits', color: ARCHON_THEME.purple },
  SUPPLIES_RUNS_TO: { label: 'Supplies runs to', color: ARCHON_THEME.orange },
  CONSTRAINS: { label: 'Constrains', color: ARCHON_THEME.coral },
  PROVES_READY: { label: 'Proves ready', color: ARCHON_THEME.green },
};

export async function loadVisualLearningStudio(
  fetcher: typeof fetch = fetch,
): Promise<VisualLearningStudio> {
  const response = await fetcher('/learning/archon-studio.json');
  if (!response.ok) throw new Error(`Visual Learning Studio request failed (${response.status})`);
  const studio = (await response.json()) as VisualLearningStudio;
  if (
    studio.schema !== 'archon.visual-learning-studio'
    || studio.version !== 3
    || studio.stats.concepts !== 66
    || studio.stats.modules !== 16
  ) {
    throw new Error('Visual Learning Studio schema or canonical counts are invalid');
  }
  return studio;
}

export function conceptsForModule(
  studio: VisualLearningStudio,
  moduleId: string,
): LearningConcept[] {
  return studio.concepts.filter(concept => concept.module_id === moduleId);
}

export function evidenceFilter(
  concepts: LearningConcept[],
  query: string,
  status: ConceptStatus | 'all',
): LearningConcept[] {
  const normalized = query.trim().toLowerCase();
  return concepts.filter(concept => {
    const matchesStatus = status === 'all' || concept.status === status;
    const haystack = `${concept.title} ${concept.module_title} ${concept.limitations}`.toLowerCase();
    return matchesStatus && (!normalized || haystack.includes(normalized));
  });
}
