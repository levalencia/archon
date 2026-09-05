import type { SourceReference } from '$lib/source-links';

export interface NodeTeaching {
  definition: string;
  receives: string[];
  responsibility: string;
  produces: string[];
  controls: string[];
  failure_behavior: string;
  why_it_matters: string;
}

export interface EdgeTeaching {
  payload: string;
  transformation: string;
  trust_boundary: string;
  precondition: string;
  failure_behavior: string;
  why_it_matters: string;
}

export interface LearningNode {
  id: string;
  label: string;
  kind: string;
  summary?: string;
  details?: string;
  teaching?: NodeTeaching;
  sources?: SourceReference[];
  position?: { x: number; y: number };
}

export interface LearningEdge {
  id?: string;
  source: string;
  target: string;
  label: string;
  explanation?: string;
  teaching?: EdgeTeaching;
  sources?: SourceReference[];
  style?: string;
}

export interface TeachingModule {
  id: string;
  label: string;
  category: 'principle' | 'architecture' | 'impact';
  summary: string;
  details: string;
  sources?: SourceReference[];
}
