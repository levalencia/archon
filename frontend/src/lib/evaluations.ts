import { authenticatedFetch } from '$lib/auth';
import { listRuns, type Run } from '$lib/runs';

export const EVALUATION_DATASET_ID = 'grounded-v1' as const;
export const EVALUATION_CASE_KEYS = ['grounded-citation', 'safe-abstention'] as const;
export type EvaluationCaseKey = (typeof EVALUATION_CASE_KEYS)[number];

export type EvaluationCheck = {
  name: string;
  passed: boolean;
  expected?: unknown;
  actual?: unknown;
  [key: string]: unknown;
};

export type EvaluationCase = {
  source_run_id: string;
  case_key: string;
  metrics: Record<string, number>;
  checks: EvaluationCheck[];
  passed: boolean;
};

export type Evaluation = {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_version: string;
  dataset_hash: string;
  status: string;
  source_run_ids: string[];
  threshold: number;
  aggregate_metrics: Record<string, number>;
  passed: boolean | null;
  created_at: string;
  completed_at: string | null;
  cases: EvaluationCase[];
};

export type EvaluationComparison = {
  a: Evaluation;
  b: Evaluation;
  metric_delta_b_minus_a: Record<string, number>;
};

export class EvaluationApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'EvaluationApiError';
  }
}

const statusMessages: Record<number, string> = {
  401: 'Sign in required',
  404: 'Recorded run or evaluation not found',
  409: 'A selected run is not ready for evaluation',
  422: 'The evaluation request is invalid',
  429: 'Too many evaluation requests. Try again shortly.',
};

function numbers(value: unknown): Record<string, number> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, number] => typeof entry[1] === 'number' && Number.isFinite(entry[1])));
}

function normalizeEvaluation(value: Evaluation): Evaluation {
  return {
    ...value,
    source_run_ids: Array.isArray(value.source_run_ids) ? value.source_run_ids : [],
    aggregate_metrics: numbers(value.aggregate_metrics),
    cases: Array.isArray(value.cases) ? value.cases.map((item) => ({
      ...item,
      metrics: numbers(item.metrics),
      checks: Array.isArray(item.checks) ? item.checks : [],
    })) : [],
  };
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* use the stable status message */ }
    throw new EvaluationApiError(response.status, detail || statusMessages[response.status] || `Evaluation request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value));
  return params.toString();
}

/** Runs eligible for the recorded evaluation selector. No model endpoint is invoked. */
export async function listRecordedRuns(): Promise<Run[]> {
  return (await listRuns({ limit: 100 })).filter((run) => run.status === 'completed' && Boolean(run.completed_at));
}

export async function createEvaluation(input: {
  projectId: string;
  threshold: number;
  groundedCitationRunId: string;
  safeAbstentionRunId: string;
}): Promise<Evaluation> {
  const result = await request<Evaluation>('/api/evals/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_id: input.projectId,
      dataset_id: EVALUATION_DATASET_ID,
      threshold: input.threshold,
      items: [
        { run_id: input.groundedCitationRunId, case_key: EVALUATION_CASE_KEYS[0] },
        { run_id: input.safeAbstentionRunId, case_key: EVALUATION_CASE_KEYS[1] },
      ],
    }),
  });
  return normalizeEvaluation(result);
}

export async function listEvaluations(options: { projectId?: string; limit?: number; offset?: number } = {}): Promise<Evaluation[]> {
  const result = await request<{ items?: Evaluation[] }>(`/api/evals?${query({ project_id: options.projectId, limit: options.limit ?? 50, offset: options.offset ?? 0 })}`);
  return (Array.isArray(result.items) ? result.items : []).map(normalizeEvaluation);
}

export async function getEvaluation(id: string): Promise<Evaluation> {
  return normalizeEvaluation(await request<Evaluation>(`/api/evals/${encodeURIComponent(id)}`));
}

export async function compareEvaluations(a: string, b: string): Promise<EvaluationComparison> {
  const result = await request<EvaluationComparison>(`/api/evals/compare?${query({ a, b })}`);
  return {
    a: normalizeEvaluation(result.a),
    b: normalizeEvaluation(result.b),
    metric_delta_b_minus_a: numbers(result.metric_delta_b_minus_a),
  };
}
