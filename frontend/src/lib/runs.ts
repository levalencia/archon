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
export type EffectiveContextEntry = {
  id: string; name?: string; relative_path?: string; scope_path?: string; revision?: string; version?: string;
  content_hash?: string; schema_hash?: string; selection_reason?: string; reason?: string;
  estimated_tokens?: number; byte_count?: number; permission?: 'allow' | 'ask' | 'deny';
};
export type EffectiveContextManifest = {
  run_id: string; project_id: string; manifest_hash: string;
  instruction_revisions: EffectiveContextEntry[]; skill_revisions: EffectiveContextEntry[];
  capabilities: EffectiveContextEntry[];
  context_cost: { estimated_tokens: number; byte_count: number };
  omission_reasons: string[];
};
export type RunExport = {
  export_id: string; run_id: string; schema_version: number; content_checksum: string;
  manifest_checksum: string; created_at: string;
};
export type ShareGrant = {
  grant_id: string; export_id: string; recipient_user_id: string; purpose: string;
  created_at: string; expires_at: string; revoked_at: string | null;
};
export type CreatedShareGrant = ShareGrant & { token: string };
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
export async function getRunEffectiveContext(id: string): Promise<EffectiveContextManifest> {
  const value = await json<Partial<EffectiveContextManifest>>(`/api/runs/${encodeURIComponent(id)}/effective-context`);
  return {
    run_id: value.run_id || id, project_id: value.project_id || '', manifest_hash: value.manifest_hash || '',
    instruction_revisions: Array.isArray(value.instruction_revisions) ? value.instruction_revisions : [],
    skill_revisions: Array.isArray(value.skill_revisions) ? value.skill_revisions : [],
    capabilities: Array.isArray(value.capabilities) ? value.capabilities : [],
    context_cost: value.context_cost || { estimated_tokens: 0, byte_count: 0 },
    omission_reasons: Array.isArray(value.omission_reasons) ? value.omission_reasons : [],
  };
}
export async function getRunEvents(id: string): Promise<RunEvent[]> {
  const result = await json<{ items?: RunEvent[] }>(`/api/runs/${encodeURIComponent(id)}/events?limit=200`);
  return (Array.isArray(result.items) ? result.items : []).slice().sort((a, b) => a.sequence - b.sequence);
}
export const forkRun = (id: string, sourceSequence: number) => json<{ target_conversation_id: string; checkpoint_id: string; workspace_restoration: string }>(`/api/runs/${encodeURIComponent(id)}/fork`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_sequence: sourceSequence }) });
export const compareRuns = (a: string, b: string) => json<{ a: ComparedRun; b: ComparedRun }>(`/api/runs/compare?${query({ a, b })}`);
export const createRunExport = (runId: string) =>
  json<RunExport>(`/api/runs/${encodeURIComponent(runId)}/exports`, { method: 'POST' });
export async function listRunExports(runId: string): Promise<RunExport[]> {
  const result = await json<{ items?: RunExport[] }>(`/api/runs/${encodeURIComponent(runId)}/exports`);
  return Array.isArray(result.items) ? result.items : [];
}
export const downloadRunExport = (runId: string, exportId: string) =>
  json<Record<string, unknown>>(`/api/runs/${encodeURIComponent(runId)}/exports/${encodeURIComponent(exportId)}/download`);
export const createShareGrant = (
  runId: string,
  exportId: string,
  recipientUserId: string,
  purpose: 'audit' | 'incident_review' | 'evaluation' | 'support',
  expiresInSeconds: number,
) => json<CreatedShareGrant>(`/api/runs/${encodeURIComponent(runId)}/exports/${encodeURIComponent(exportId)}/shares`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ recipient_user_id: recipientUserId, purpose, expires_in_seconds: expiresInSeconds }),
});
export async function listShareGrants(runId: string, exportId: string): Promise<ShareGrant[]> {
  const result = await json<{ items?: ShareGrant[] }>(`/api/runs/${encodeURIComponent(runId)}/exports/${encodeURIComponent(exportId)}/shares`);
  return Array.isArray(result.items) ? result.items : [];
}
export async function revokeShareGrant(grantId: string): Promise<void> {
  const response = await authenticatedFetch(`/api/shares/${encodeURIComponent(grantId)}`, { method: 'DELETE' });
  if (!response.ok) throw new RunApiError(response.status, response.status === 404 ? 'Share grant not found' : `Share request failed (${response.status})`);
}
