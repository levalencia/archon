import { authenticatedFetch } from '$lib/auth';
import { SSEParser } from '$lib/sse';

export type LearningView = 'roadmap' | 'stories' | 'architecture' | 'evidence' | 'present' | 'listen' | 'study';

export interface LearningTutorContext {
  view: LearningView;
  concept_id?: string;
  module_id?: string;
  story_id?: string;
  step_index?: number;
  artifact_id?: string;
  playback_seconds?: number;
  selected_node_id?: string;
  selected_edge_id?: string;
}

export interface TutorCitation {
  id: string;
  kind: 'documentation' | 'code' | 'test' | 'video' | 'visual' | 'web';
  title: string;
  excerpt: string;
  score: number;
  source_commit: string;
  locator: {
    path?: string;
    line_start?: number;
    line_end?: number;
    symbol?: string;
    language?: string;
    artifact_id?: string;
    pack_id?: string;
    chapter?: string;
    start_seconds?: number;
    end_seconds?: number;
    route?: string;
    concept_id?: string;
    url?: string;
    domain?: string;
    retrieved_at?: number;
    search_source?: string;
  };
}

export interface TutorDiagramNode {
  id: string;
  label: string;
  evidence_ids: string[];
}

export interface TutorDiagramEdge {
  from: string;
  to: string;
  label: string;
  evidence_ids: string[];
}

export interface TutorDiagram {
  title: string;
  kind: 'flow' | 'sequence' | 'architecture';
  nodes: TutorDiagramNode[];
  edges: TutorDiagramEdge[];
  reading_order: string[];
}

export interface LearningTutorAnswer {
  run_id: string;
  session_id: string;
  answer_markdown: string;
  citations: TutorCitation[];
  related_questions: string[];
  diagram: TutorDiagram | null;
  grounded: boolean;
  unsupported: string[];
  metrics: Record<string, unknown>;
}

export interface TutorTurn {
  id: string;
  question: string;
  answer_markdown: string;
  context: LearningTutorContext;
  citations: TutorCitation[];
  diagram: TutorDiagram | null;
  metrics: Record<string, unknown>;
  created_at: string;
}

export interface TutorSession {
  id: string;
  project_id: string;
  context_key: string;
  title: string;
  turns: TutorTurn[];
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export async function askLearningTutor(
  question: string,
  context: LearningTutorContext,
  fetcher: Fetcher = authenticatedFetch,
): Promise<LearningTutorAnswer> {
  const response = await fetcher('/api/learning-tutor/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, project_id: 'default', context }),
  });
  if (!response.ok) throw new Error(`Learning tutor request failed (${response.status})`);
  return await response.json() as LearningTutorAnswer;
}

// ---------------------------------------------------------------------------
// Streaming SSE client — delivers verified answer incrementally
// ---------------------------------------------------------------------------

export interface TutorStreamCallbacks {
  onStatus?: (data: { run_id: string; phase: string; message: string }) => void;
  onProgress?: (data: { run_id: string; phase: string; message: string }) => void;
  onAnswerDelta?: (data: { run_id: string; index: number; delta: string }) => void;
  onResult?: (data: LearningTutorAnswer) => void;
  onError?: (data: { run_id: string; message: string }) => void;
  onDone?: (data: { run_id: string }) => void;
}

export async function streamLearningTutor(
  question: string,
  context: LearningTutorContext,
  callbacks: TutorStreamCallbacks,
  fetcher: Fetcher = authenticatedFetch,
  parser?: SSEParser,
): Promise<void> {
  const response = await fetcher('/api/learning-tutor/answer/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, project_id: 'default', context }),
  });
  if (!response.ok) throw new Error(`Learning tutor stream failed (${response.status})`);
  if (!response.body) throw new Error('No response body for SSE stream');

  const sseParser = parser ?? new SSEParser();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      const text = value ? decoder.decode(value, { stream: !done }) : '';
      const events = sseParser.push(text, done);
      for (const evt of events) {
        const data = JSON.parse(evt.data);
        switch (evt.event) {
          case 'status': callbacks.onStatus?.(data); break;
          case 'progress': callbacks.onProgress?.(data); break;
          case 'answer_delta': callbacks.onAnswerDelta?.(data); break;
          case 'result': callbacks.onResult?.(data); break;
          case 'error': callbacks.onError?.(data); break;
          case 'done': callbacks.onDone?.(data); break;
        }
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}

export async function getLearningTutorSession(
  sessionId: string,
  fetcher: Fetcher = authenticatedFetch,
): Promise<TutorSession> {
  const response = await fetcher(`/api/learning-tutor/sessions/${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new Error(`Learning tutor history failed (${response.status})`);
  return await response.json() as TutorSession;
}

/** Allowed domains for web citation hrefs (HTTPS only). */
const WEB_CITATION_ALLOWED_DOMAINS: ReadonlySet<string> = new Set([
  'docs.python.org',
  'learn.microsoft.com',
  'developer.mozilla.org',
  'docs.aws.amazon.com',
  'cloud.google.com',
  'kubernetes.io',
  'docs.docker.com',
  'fastapi.tiangolo.com',
  'starlette.io',
  'pydantic-docs.helpmanual.io',
  'docs.pydantic.dev',
  'www.postgresql.org',
  'redis.io',
  'opentelemetry.io',
  'swagger.io',
  'spec.openapis.org',
  'www.rfc-editor.org',
  'datatracker.ietf.org',
]);

function isAllowedWebDomain(hostname: string): boolean {
  const h = hostname.toLowerCase().replace(/\.$/, '');
  for (const allowed of WEB_CITATION_ALLOWED_DOMAINS) {
    if (h === allowed || h.endsWith(`.${allowed}`)) return true;
  }
  return false;
}

export function citationHref(citation: TutorCitation): string | undefined {
  const locator = citation.locator;
  // Web citations: validate URL is HTTPS and domain-allowlisted
  if (citation.kind === 'web' && locator.url) {
    try {
      const parsed = new URL(locator.url);
      if (parsed.protocol === 'https:' && isAllowedWebDomain(parsed.hostname)) {
        return locator.url;
      }
    } catch {
      // Invalid URL
    }
    return undefined;
  }
  if (citation.kind === 'video' && locator.artifact_id && locator.start_seconds !== undefined) {
    const params = new URLSearchParams({
      view: 'present',
      pack: locator.pack_id || 'code-first-series',
      artifact: locator.artifact_id,
      t: String(locator.start_seconds),
    });
    return `/learn?${params.toString()}`;
  }
  if (citation.kind === 'visual' && locator.route) return locator.route;
  if (!locator.path || !/^[0-9a-f]{40}$/.test(citation.source_commit)) return undefined;
  const safe = locator.path.split('/');
  if (safe.some(part => !part || part === '..') || locator.path.startsWith('/')) return undefined;
  let anchor = '';
  if (Number.isInteger(locator.line_start) && (locator.line_start ?? 0) > 0) {
    anchor = `#L${locator.line_start}`;
    if (Number.isInteger(locator.line_end) && (locator.line_end ?? 0) >= (locator.line_start ?? 0)) {
      anchor += `-L${locator.line_end}`;
    }
  }
  return `https://github.com/levalencia/cogentrex/blob/${citation.source_commit}/${safe.map(encodeURIComponent).join('/')}${anchor}`;
}
