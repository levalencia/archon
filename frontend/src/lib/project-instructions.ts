import { authenticatedFetch } from "$lib/auth";

export type TrustState = "untrusted" | "pending" | "trusted" | "revoked" | "allowlisted" | "verified";
export type ProjectInstruction = {
  id: string;
  relative_path: string;
  scope_path: string;
  revision: string;
  content_hash: string;
  trust_state: TrustState;
  byte_count: number;
};
export type ProjectWorkspace = {
  id: string;
  project_id: string;
  display_name: string;
  source_type: "manual" | "mounted_local" | "github_pinned";
  trust_state: TrustState;
  repository_url?: string | null;
  pinned_commit?: string | null;
};

export class InstructionsApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) throw new InstructionsApiError(response.status, response.status === 404 ? "Project workspace not configured" : `Instructions request failed (${response.status})`);
  return response.json() as Promise<T>;
}
const projectPath = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}`;
export const getProjectWorkspace = (projectId: string) => request<ProjectWorkspace>(`${projectPath(projectId)}/workspace`);
export async function listProjectInstructions(projectId: string): Promise<ProjectInstruction[]> {
  const result = await request<ProjectInstruction[] | { items?: ProjectInstruction[] }>(`${projectPath(projectId)}/instructions`);
  return Array.isArray(result) ? result : Array.isArray(result.items) ? result.items : [];
}
export const scanProjectWorkspace = (projectId: string) => request<{ items?: ProjectInstruction[]; scan_id?: string }>(`${projectPath(projectId)}/workspace/scan`, { method: "POST" });
