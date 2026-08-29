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
  model_revision?: string | null;
  provider_revision?: string | null;
  config_revision?: string | null;
};

export type RevisionIdentity = Record<string, string | number | boolean | null>;
export type DriftWarning = {
  metric: string;
  direction: string;
  threshold?: number;
  delta?: number;
  observed_ratio?: number | null;
  baseline_count?: number;
  candidate_count?: number;
};
export type DriftReport = {
  id: string;
  owner_id: string;
  project_id: string;
  baseline_eval_id: string;
  candidate_eval_id: string;
  baseline_identity: RevisionIdentity;
  candidate_identity: RevisionIdentity;
  baseline_summary: Record<string, unknown>;
  candidate_summary: Record<string, unknown>;
  deltas: Record<string, unknown>;
  warnings: DriftWarning[];
  minimum_sample_size: number;
  created_at: string;
};

export type CandidateType = 'prompt' | 'policy' | 'retrieval' | 'config';
export type CandidateState = 'proposed' | 'approved' | 'rejected' | 'promoted' | 'rolled_back';
export type OptimizationCandidate = {
  id: string; owner_id: string; project_id: string; candidate_type: CandidateType;
  change_summary: string; proposal_metadata: Record<string, unknown>; rollback_plan: string;
  target_revision: string; baseline_eval_id: string; candidate_eval_id: string;
  drift_report_id: string | null; state: CandidateState; version: number;
  approval_id: string | null; created_at: string; updated_at: string;
  promoted_at: string | null; rolled_back_at: string | null;
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
      if (typeof body.detail === 'string') detail = body.detail.slice(0, 300);
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
}, signal?: AbortSignal): Promise<Evaluation> {
  const result = await request<Evaluation>('/api/evals/runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
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

export async function listEvaluations(options: { projectId?: string; limit?: number; offset?: number; signal?: AbortSignal } = {}): Promise<Evaluation[]> {
  const result = await request<{ items?: Evaluation[] }>(`/api/evals?${query({ project_id: options.projectId, limit: options.limit ?? 50, offset: options.offset ?? 0 })}`, { signal: options.signal });
  return (Array.isArray(result.items) ? result.items : []).map(normalizeEvaluation);
}

export async function getEvaluation(id: string, signal?: AbortSignal): Promise<Evaluation> {
  return normalizeEvaluation(await request<Evaluation>(`/api/evals/${encodeURIComponent(id)}`, { signal }));
}

export async function compareEvaluations(a: string, b: string, signal?: AbortSignal): Promise<EvaluationComparison> {
  const result = await request<EvaluationComparison>(`/api/evals/compare?${query({ a, b })}`, { signal });
  return {
    a: normalizeEvaluation(result.a),
    b: normalizeEvaluation(result.b),
    metric_delta_b_minus_a: numbers(result.metric_delta_b_minus_a),
  };
}

export function isInsufficientSample(report: DriftReport): boolean {
  return report.warnings.some((warning) => warning.metric === 'sample_count' && warning.direction === 'insufficient_sample');
}

export async function createDriftReport(input: { projectId: string; baselineEvalId: string; candidateEvalId: string; minimumSampleSize: number }, signal?: AbortSignal): Promise<DriftReport> {
  return request<DriftReport>('/api/evals/drift', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ project_id: input.projectId, baseline_eval_id: input.baselineEvalId, candidate_eval_id: input.candidateEvalId, minimum_sample_size: input.minimumSampleSize }),
  });
}

export async function getDriftReport(reportId: string, projectId: string, signal?: AbortSignal): Promise<DriftReport> {
  return request<DriftReport>(`/api/evals/drift/${encodeURIComponent(reportId)}?${query({ project_id: projectId })}`, { signal });
}

export async function listCandidates(projectId: string, signal?: AbortSignal): Promise<OptimizationCandidate[]> {
  const result = await request<{ items?: OptimizationCandidate[] }>(`/api/evals/candidates?${query({ project_id: projectId, limit: 50 })}`, { signal });
  return Array.isArray(result.items) ? result.items : [];
}

export async function createCandidate(input: {
  projectId: string; candidateType: CandidateType; changeSummary: string;
  proposalMetadata?: Record<string, unknown>; rollbackPlan: string; targetRevision: string;
  baselineEvalId: string; candidateEvalId: string; driftReportId?: string;
}): Promise<OptimizationCandidate> {
  return request<OptimizationCandidate>('/api/evals/candidates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
    project_id: input.projectId, candidate_type: input.candidateType, change_summary: input.changeSummary,
    proposal_metadata: input.proposalMetadata ?? {}, rollback_plan: input.rollbackPlan,
    target_revision: input.targetRevision, baseline_eval_id: input.baselineEvalId,
    candidate_eval_id: input.candidateEvalId, drift_report_id: input.driftReportId || null,
  }) });
}

export type CandidateAction = 'approval' | 'approve' | 'reject' | 'promote' | 'rollback';
export type CandidateActionInput = { projectId: string; expectedVersion: number; approvalId?: string; reasonCode?: string };

/** The caller passes an immutable version snapshot so delayed clicks cannot target a newer candidate. */
export type CandidateApprovalReceipt = { approval_id: string; tool_call_id: string };

export async function decideCandidateApproval(
  toolCallId: string,
  candidateId: string,
  approved: boolean,
): Promise<void> {
  await request(`/api/chat/approve/${encodeURIComponent(toolCallId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: candidateId, approved }),
  });
}

export async function transitionCandidate(candidateId: string, action: CandidateAction, input: CandidateActionInput): Promise<OptimizationCandidate | CandidateApprovalReceipt> {
  const body: Record<string, unknown> = { project_id: input.projectId, expected_version: input.expectedVersion };
  if (action === 'approve') body.approval_id = input.approvalId;
  if (action === 'reject' || action === 'rollback') body.reason_code = input.reasonCode;
  return request(`/api/evals/candidates/${encodeURIComponent(candidateId)}/${action}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
}
