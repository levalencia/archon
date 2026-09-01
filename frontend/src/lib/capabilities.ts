import { authenticatedFetch } from "$lib/auth";

export type Permission = "allow" | "ask" | "deny";
export type Capability = {
  id: string;
  name: string;
  description: string;
  kind: "native_tool" | "mcp_tool" | "skill";
  source: string;
  version: string;
  risk_classes: string[];
  visible: boolean;
  selected: boolean;
  executable: boolean;
  pinned: boolean;
  permission: Permission;
  transport?: "stdio" | "streamable_http" | null;
  health?: "healthy" | "degraded" | "unavailable" | "unknown" | null;
  schema_hash?: string | null;
  estimated_tokens?: number;
  selection_reason?: string | null;
};
export class CapabilitiesApiError extends Error { constructor(public status: number, message: string) { super(message); } }
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) throw new CapabilitiesApiError(response.status, `Capabilities request failed (${response.status})`);
  return response.json() as Promise<T>;
}
const base = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/capabilities`;
export async function listEffectiveCapabilities(projectId: string): Promise<Capability[]> {
  const result = await request<Capability[] | { items?: Capability[] }>(`${base(projectId)}/effective`);
  return Array.isArray(result) ? result : Array.isArray(result.items) ? result.items : [];
}
export const pinCapability = (projectId: string, capabilityId: string) => request<Capability>(`${base(projectId)}/${encodeURIComponent(capabilityId)}/pin`, { method: "POST" });
export const disableCapability = (projectId: string, capabilityId: string) => request<Capability>(`${base(projectId)}/${encodeURIComponent(capabilityId)}/disable`, { method: "POST" });
