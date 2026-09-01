import { authenticatedFetch } from '$lib/auth';

export type Capability = {
  id: string;
  name: string;
  description: string;
  kind: string;
  source: string;
  version: string;
  trust_state: string;
  enabled: boolean;
  pinned: boolean;
  risk_classes: string[];
};

export class CapabilitiesApiError extends Error {
  constructor(public status: number, public code: string) {
    super(status === 401 ? 'Sign in required' : `Capabilities request failed (${code})`);
    this.name = 'CapabilitiesApiError';
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) {
    let code = `http_${response.status}`;
    try {
      const payload = await response.json();
      code = payload?.detail?.code ?? payload?.code ?? code;
    } catch { /* non-JSON error */ }
    throw new CapabilitiesApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}

const base = (projectId: string) => `/api/capabilities/projects/${encodeURIComponent(projectId)}`;
const body = (value: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
});

export async function listCapabilityInventory(projectId: string): Promise<Capability[]> {
  return request<Capability[]>('/api/capabilities/search', body({ query: '', project_id: projectId, limit: 100 }));
}

export async function listEffectiveCapabilities(projectId: string): Promise<Capability[]> {
  const result = await request<{ items?: Capability[] }>(`${base(projectId)}/effective`, body({}));
  return Array.isArray(result.items) ? result.items : [];
}

export const setCapabilityPreference = (
  projectId: string,
  capabilityId: string,
  preference: { enabled: boolean; pinned: boolean },
) => request<Capability>(`${base(projectId)}/${encodeURIComponent(capabilityId)}`, {
  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(preference),
});

export const pinCapability = (projectId: string, capability: Pick<Capability, 'id' | 'enabled'>) =>
  setCapabilityPreference(projectId, capability.id, { enabled: capability.enabled, pinned: true });
export const enableCapability = (projectId: string, capability: Pick<Capability, 'id' | 'pinned'>) =>
  setCapabilityPreference(projectId, capability.id, { enabled: true, pinned: capability.pinned });
export const disableCapability = (projectId: string, capability: Pick<Capability, 'id' | 'pinned'>) =>
  setCapabilityPreference(projectId, capability.id, { enabled: false, pinned: capability.pinned });
