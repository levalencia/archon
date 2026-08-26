import { authenticatedFetch } from '$lib/auth';

export type MCPHealth = 'healthy' | 'error' | 'unknown' | 'disabled' | string;

export interface MCPProfile {
  id: string;
  display_name: string;
}

export interface MCPServer {
  id: string;
  project_id: string;
  name: string;
  profile_id: string;
  transport: string;
  enabled: boolean;
  health: MCPHealth;
  last_error_code: string | null;
  last_seen: string | null;
  created_at: string;
  updated_at: string;
}

export interface MCPTool {
  id: string;
  server_id: string;
  name: string;
  title: string | null;
  description: string | null;
  input_schema: Record<string, unknown>;
  read_only: boolean;
  destructive: boolean;
  enabled: boolean;
  version: string | null;
}

export class MCPApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
    this.name = 'MCPApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(`/api/mcp${path}`, init);
  if (!response.ok) {
    let code = response.status === 401 ? 'unauthorized' : `http_${response.status}`;
    try {
      const payload = await response.json();
      code = payload?.detail?.code ?? payload?.code ?? code;
    } catch { /* non-JSON error */ }
    throw new MCPApiError(response.status, code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const query = (projectId: string) => `?project_id=${encodeURIComponent(projectId)}`;
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const listProfiles = () => request<MCPProfile[]>('/profiles');
export const listServers = (projectId: string) => request<MCPServer[]>(`/servers${query(projectId)}`);
export const getServer = (projectId: string, id: string) => request<MCPServer>(`/servers/${encodeURIComponent(id)}${query(projectId)}`);
export const createServer = (projectId: string, name: string, profileId: string) =>
  request<MCPServer>('/servers', json({ project_id: projectId, name, profile_id: profileId, enabled: true }));
export const updateServer = (projectId: string, id: string, changes: Partial<Pick<MCPServer, 'name' | 'profile_id' | 'enabled'>>) =>
  request<MCPServer>(`/servers/${encodeURIComponent(id)}${query(projectId)}`, {
    ...json(changes), method: 'PATCH',
  });
export const deleteServer = (projectId: string, id: string) =>
  request<void>(`/servers/${encodeURIComponent(id)}${query(projectId)}`, { method: 'DELETE' });
export const discoverTools = (projectId: string, id: string) =>
  request<MCPTool[]>(`/servers/${encodeURIComponent(id)}/discover${query(projectId)}`, { method: 'POST' });
export const listTools = (projectId: string, id: string) =>
  request<MCPTool[]>(`/servers/${encodeURIComponent(id)}/tools${query(projectId)}`);
export const toggleTool = (projectId: string, serverId: string, toolName: string, enabled: boolean) =>
  request<MCPTool>(`/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolName)}${query(projectId)}`, {
    ...json({ enabled }), method: 'PATCH',
  });
