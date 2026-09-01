import { authenticatedFetch } from '$lib/auth';

export type TrustState = 'untrusted' | 'pending' | 'trusted' | 'approved' | 'revoked' | 'allowlisted' | 'verified' | string;
export type ProjectInstruction = {
  id: string;
  relative_path: string;
  scope_path: string;
  revision: number | string;
  content_hash: string;
  trust_state: TrustState;
  byte_count: number;
};

export class InstructionsApiError extends Error {
  constructor(public status: number, public code: string) {
    super(status === 401 ? 'Sign in required' : status === 404 ? 'Project instructions not found' : `Instructions request failed (${code})`);
    this.name = 'InstructionsApiError';
  }
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const value = await response.json(); code = value?.detail?.code ?? value?.code ?? code; } catch { /* non-JSON */ }
    throw new InstructionsApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}
const projectPath = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}`;
export const createProjectWorkspace = (projectId: string) => request<{ project_id: string; status: string }>(`${projectPath(projectId)}/workspace`, { method: 'POST' });
export async function listProjectInstructions(projectId: string): Promise<ProjectInstruction[]> {
  const result = await request<ProjectInstruction[]>(`${projectPath(projectId)}/instructions`);
  return Array.isArray(result) ? result : [];
}
export const scanProjectWorkspace = (projectId: string, targetPath = '.') => request<ProjectInstruction[]>(`${projectPath(projectId)}/instructions/scan`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_path: targetPath, family: 'archon' }),
});
