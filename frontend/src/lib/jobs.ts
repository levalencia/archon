import { authenticatedFetch } from '$lib/auth';

export const JOB_KINDS = ['echo', 'run_export'] as const;
export const JOB_STATUSES = ['pending', 'running', 'succeeded', 'failed', 'dead_letter', 'cancelled'] as const;

export type JobKind = (typeof JOB_KINDS)[number];
export type JobStatus = (typeof JOB_STATUSES)[number];
export type DurableJob = {
  job_id: string;
  owner_id: string;
  project_id: string;
  kind: JobKind;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  result: Record<string, unknown> | null;
  error_code: string | null;
};
export type CreateJobInput = {
  kind: JobKind;
  projectId: string;
  payload: Record<string, unknown>;
  idempotencyKey?: string;
  maxAttempts?: number;
};

export class JobApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'JobApiError';
  }
}

const statusMessages: Record<number, string> = {
  401: 'Sign in required',
  404: 'Job not found or no longer actionable',
  422: 'The job request is invalid',
  429: 'Too many job requests. Try again shortly.',
};

const REQUEST_TIMEOUT_MS = 10_000;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await authenticatedFetch(url, { ...init, signal: controller.signal });
  } catch (cause) {
    if (controller.signal.aborted) throw new JobApiError(408, 'Job request timed out');
    throw cause;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === 'string' && body.detail.length <= 300) detail = body.detail;
    } catch { /* use a stable status message */ }
    throw new JobApiError(response.status, detail || statusMessages[response.status] || `Job request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') params.set(key, String(value));
  }
  return params.toString();
}

export async function createJob(input: CreateJobInput): Promise<DurableJob> {
  return request<DurableJob>('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: input.kind,
      project_id: input.projectId,
      payload: input.payload,
      idempotency_key: input.idempotencyKey,
      max_attempts: input.maxAttempts ?? 3,
    }),
  });
}

export async function listJobs(options: { projectId?: string; limit?: number; offset?: number } = {}): Promise<DurableJob[]> {
  const response = await request<{ items?: DurableJob[] }>(`/api/tasks?${query({
    project_id: options.projectId,
    limit: options.limit ?? 50,
    offset: options.offset ?? 0,
  })}`);
  return Array.isArray(response.items) ? response.items : [];
}

export const getJob = (jobId: string, projectId: string) => request<DurableJob>(`/api/tasks/${encodeURIComponent(jobId)}?${query({ project_id: projectId })}`);
export const cancelJob = (jobId: string, projectId: string) => request<{ job_id: string; status: 'cancelled' }>(`/api/tasks/${encodeURIComponent(jobId)}/cancel?${query({ project_id: projectId })}`, { method: 'POST' });
export const retryJob = (jobId: string, projectId: string) => request<{ job_id: string; status: 'pending' }>(`/api/tasks/${encodeURIComponent(jobId)}/retry?${query({ project_id: projectId })}`, { method: 'POST' });
