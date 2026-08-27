import { authenticatedFetch } from '$lib/auth';

export type Run = {
  run_id: string; conversation_id: string; project_id: string; provider: string; model: string;
  status: string; started_at: string; completed_at: string | null; answer_summary: string | null;
  input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number | null;
  latency_ms: number | null; iterations: number; stop_reason: string | null;
  parent_run_id: string | null; fork_source_sequence: number | null;
  trajectory?: { tools: Record<string, unknown>[]; approvals: Record<string, unknown>[]; policy: Record<string, unknown>[]; evidence: unknown[]; workspace_restoration: string };
};
export type RunEvent = { sequence: number; event_at: string; kind: string; iteration: number; payload: Record<string, unknown> };
export type ContextManifest = {
  snapshot_id: string; schema_version: number; run_id: string; conversation_id: string; project_id: string;
  selected_message_ids: number[]; summarized_message_ids: number[]; memory_ids: string[]; skill_ids: string[];
  input_asset_fingerprints: string[]; estimated_tokens: number; summary_version: string | null;
  truncation_reason: string | null; manifest_hash: string;
};
export type ComparedRun = Pick<Run, 'run_id' | 'conversation_id' | 'project_id' | 'provider' | 'model' | 'answer_summary' | 'cost_usd' | 'latency_ms' | 'iterations' | 'stop_reason' | 'parent_run_id' | 'fork_source_sequence'> & {
  tokens: { input: number; output: number; total: number };
};

export class RunApiError extends Error { constructor(public status: number, message: string) { super(message); } }
async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) throw new RunApiError(response.status, response.status === 401 ? 'Sign in required' : response.status === 404 ? 'Run not found' : `Run request failed (${response.status})`);
  return response.json() as Promise<T>;
}
function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== '') params.set(key, String(value));
  return params.toString();
}
export async function listRuns(options: { conversationId?: string; projectId?: string; limit?: number; offset?: number } = {}): Promise<Run[]> {
  const result = await json<{ items?: Run[] }>(`/api/runs?${query({ conversation_id: options.conversationId, project_id: options.projectId, limit: options.limit ?? 50, offset: options.offset ?? 0 })}`);
  return Array.isArray(result.items) ? result.items : [];
}
export const getRun = (id: string) => json<Run>(`/api/runs/${encodeURIComponent(id)}`);
export const getRunContext = (id: string) =>
  json<ContextManifest>(`/api/runs/${encodeURIComponent(id)}/context`);
export async function getRunEvents(id: string): Promise<RunEvent[]> {
  const result = await json<{ items?: RunEvent[] }>(`/api/runs/${encodeURIComponent(id)}/events?limit=200`);
  return (Array.isArray(result.items) ? result.items : []).slice().sort((a, b) => a.sequence - b.sequence);
}
export const forkRun = (id: string, sourceSequence: number) => json<{ target_conversation_id: string; checkpoint_id: string; workspace_restoration: string }>(`/api/runs/${encodeURIComponent(id)}/fork`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_sequence: sourceSequence }) });
export const compareRuns = (a: string, b: string) => json<{ a: ComparedRun; b: ComparedRun }>(`/api/runs/compare?${query({ a, b })}`);
